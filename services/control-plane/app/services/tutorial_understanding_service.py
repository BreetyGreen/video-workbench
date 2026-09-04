from __future__ import annotations

import re
import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlmodel import Session, select

from app.models import (
    Course,
    CourseAsset,
    CourseAssetRole,
    CourseProcessingRun,
    EditingRecipe,
    EditingRule,
    TutorialSegment,
    TutorialSegmentType,
)
from app.schemas.editing import FrameEvidence, MediaAnalysis, TranscriptResult


TIME_RANGE = re.compile(r"(?P<start>\d+(?:\.\d+)?)\s*[-—~至]\s*(?P<end>\d+(?:\.\d+)?)\s*秒")
# Keep decimal numbers such as "1.2 秒" intact.  ASR frequently normalizes
# spoken Chinese numbers to Arabic decimals; splitting on that dot would turn a
# pacing rule into two unrelated fragments and make it impossible to apply.
SENTENCE_BREAK = re.compile(r"[。！？；!?]+|(?<!\d)\.|\.(?!\d)")
OPERATION_TERMS = ("剪映", "capcut", "时间线", "timeline", "轨道", "track", "素材面板", "media panel", "点击", "拖到", "导入", "导出", "export", "分割", "转场", "调速")
EXAMPLE_TERMS = ("成片示例", "完成示例", "播放成片", "最终成片", "成片预览", "示例效果", "看效果", "效果如下", "final cut preview", "finished example")
INTRO_OUTRO_TERMS = ("大家好", "欢迎来到", "欢迎回到", "课程目录", "本节课程", "感谢观看", "下期再见", "course intro", "thanks for watching")
LECTURE_TERMS = ("讲解", "规则", "技巧", "建议", "注意", "应该", "需要", "不要", "必须", "先展示", "钩子", "字幕", "旁白", "背景音乐", "单镜头", "结尾")
LECTURE_REENTRY_TERMS = ("回到讲解", "继续讲解", "接下来讲解", "下面讲解", "讲解一下", "课程讲解", "老师讲解", "教学画面")


@dataclass(frozen=True)
class ExtractedTutorialSegment:
    text: str
    start_ms: int | None
    end_ms: int | None
    source_page: int
    transcript_confidence: float
    segment_type: TutorialSegmentType
    classification_confidence: float
    ocr_texts: tuple[str, ...] = ()
    visual_cues: tuple[str, ...] = ()


def _category(text: str) -> str:
    if any(token in text for token in ("前三秒", "钩子", "先展示", "结果前置")):
        return "hook"
    if any(token in text for token in ("单镜头", "节奏", "镜头不要超过", "切换")):
        return "pacing"
    if any(token in text for token in ("字幕", "每行", "字体")):
        return "captions"
    if any(token in text for token in ("背景音乐", "旁白", "原声", "噪声", "响度")):
        return "audio"
    if any(token in text for token in ("结尾", "行动提示", "引导", "下单")):
        return "cta"
    if any(token in text for token in ("特写", "细节镜头", "近景")):
        return "closeup"
    if any(token in text for token in ("对比", "使用前后", "前后变化")):
        return "comparison"
    if any(token in text for token in ("不要", "禁止", "避免", "不使用")):
        return "negative"
    return "structure"


class TutorialUnderstandingService:
    def __init__(self, transcriber: Any | None = None, *, media_analyzer: Any | None = None):
        self.transcriber = transcriber
        self.media_analyzer = media_analyzer

    @staticmethod
    def _nearby_ocr(frames: list[FrameEvidence], start_ms: int, end_ms: int) -> tuple[str, ...]:
        texts: list[str] = []
        for frame in frames:
            timestamp_ms = int(frame.timestamp_seconds * 1000)
            if start_ms <= timestamp_ms <= end_ms:
                texts.extend(item.strip() for item in frame.ocr_texts if item.strip())
        return tuple(dict.fromkeys(texts))

    @staticmethod
    def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
        lowered = text.lower()
        return any(term.lower() in lowered for term in terms)

    def _classify(
        self,
        *,
        text: str,
        ocr_texts: tuple[str, ...],
        previous_type: TutorialSegmentType,
        transcript_confidence: float,
    ) -> tuple[TutorialSegmentType, float, tuple[str, ...]]:
        combined_ocr = " ".join(ocr_texts)
        cues: list[str] = []
        operation_matches = [term for term in OPERATION_TERMS if self._contains_any(f"{text} {combined_ocr}", (term,))]
        ocr_operation_matches = [term for term in OPERATION_TERMS if self._contains_any(combined_ocr, (term,))]
        example_matches = [term for term in EXAMPLE_TERMS if self._contains_any(f"{text} {combined_ocr}", (term,))]
        intro_matches = [term for term in INTRO_OUTRO_TERMS if self._contains_any(f"{text} {combined_ocr}", (term,))]
        lecture_matches = [term for term in LECTURE_TERMS if self._contains_any(text, (term,))]
        lecture_reentry_matches = [
            term
            for term in LECTURE_REENTRY_TERMS
            if self._contains_any(f"{text} {combined_ocr}", (term,))
        ]

        if intro_matches and not lecture_matches:
            cues.extend(f"intro:{term}" for term in intro_matches)
            return TutorialSegmentType.INTRO_OUTRO, max(0.9, transcript_confidence), tuple(cues)
        # A spoken lesson may mention the editor while still teaching a general
        # editing rule.  Treat the brand alone as strong operation evidence only
        # when it is visibly present in the captured UI; spoken operation steps
        # still classify as operation when two or more operation cues agree.
        strong_editor_brand = any(term in {"剪映", "capcut"} for term in ocr_operation_matches)
        if strong_editor_brand or len(operation_matches) >= 2:
            cues.extend(f"operation:{term}" for term in operation_matches)
            return TutorialSegmentType.SOFTWARE_OPERATION, max(0.92, transcript_confidence), tuple(cues)
        if example_matches:
            cues.extend(f"example:{term}" for term in example_matches)
            return TutorialSegmentType.FINISHED_EXAMPLE, max(0.93, transcript_confidence), tuple(cues)
        # Sales copy inside a finished example commonly contains words such as
        # "需要", "不要", "字幕" and "结尾".  Those weak teaching terms must
        # not end the example state.  Only explicit instructor/lesson re-entry
        # evidence can turn the following segment back into a lecture.
        if previous_type == TutorialSegmentType.FINISHED_EXAMPLE:
            if lecture_reentry_matches:
                cues.extend(f"lecture_reentry:{term}" for term in lecture_reentry_matches)
                return TutorialSegmentType.LECTURE, max(0.9, transcript_confidence), tuple(cues)
            cues.append("continuation:finished_example")
            return TutorialSegmentType.FINISHED_EXAMPLE, min(max(transcript_confidence, 0.72), 0.86), tuple(cues)
        if lecture_matches:
            cues.extend(f"lecture:{term}" for term in lecture_matches)
            return TutorialSegmentType.LECTURE, max(0.88, transcript_confidence), tuple(cues)
        if not text.strip() and ocr_texts:
            cues.append("visual_only:ocr")
            return TutorialSegmentType.UNKNOWN, 0.45, tuple(cues)
        if text.strip():
            cues.append("fallback:spoken_explanation")
            return TutorialSegmentType.LECTURE, min(max(transcript_confidence, 0.55), 0.75), tuple(cues)
        cues.append("fallback:no_evidence")
        return TutorialSegmentType.UNKNOWN, 0.2, tuple(cues)

    @staticmethod
    def _split_transcript(transcript: TranscriptResult) -> list[tuple[str, int, int, int, float]]:
        duration_ms = int(transcript.duration_seconds * 1000)
        result: list[tuple[str, int, int, int, float]] = []
        for index, segment in enumerate(transcript.segments, start=1):
            text = segment.text.strip()
            if not text:
                continue
            start_ms = int(segment.start_seconds * 1000)
            end_ms = int(segment.end_seconds * 1000)
            if start_ms < 0 or end_ms <= start_ms or (duration_ms and end_ms > duration_ms):
                raise ValueError("tutorial_evidence_out_of_bounds")
            sentences = [item.strip() for item in SENTENCE_BREAK.split(text) if item.strip()] or [text]
            total_characters = sum(len(item) for item in sentences)
            cursor = start_ms
            for sentence_index, sentence in enumerate(sentences, start=1):
                if sentence_index == len(sentences):
                    sentence_end = end_ms
                else:
                    ratio = len(sentence) / max(1, total_characters)
                    sentence_end = min(end_ms, cursor + max(1, round((end_ms - start_ms) * ratio)))
                result.append((sentence, cursor, sentence_end, index * 1000 + sentence_index, segment.confidence))
                cursor = sentence_end
        return result

    @staticmethod
    def _insert_visual_gaps(
        transcript_segments: list[tuple[str, int, int, int, float]],
        analysis: MediaAnalysis,
    ) -> list[tuple[str, int, int, int, float]]:
        result = list(transcript_segments)
        duration_ms = int(analysis.duration_seconds * 1000)
        if duration_ms <= 0:
            return result
        occupied = sorted((start_ms, end_ms) for _, start_ms, end_ms, _, _ in transcript_segments)
        boundaries = [(0, duration_ms)] if not occupied else []
        if occupied:
            if occupied[0][0] >= 1500:
                boundaries.append((0, occupied[0][0]))
            for (_, previous_end), (next_start, _) in zip(occupied, occupied[1:]):
                if next_start - previous_end >= 1500:
                    boundaries.append((previous_end, next_start))
            if duration_ms - occupied[-1][1] >= 1500:
                boundaries.append((occupied[-1][1], duration_ms))
        for index, (start_ms, end_ms) in enumerate(boundaries, start=1):
            result.append(("", start_ms, end_ms, 900000 + index, 0.0))
        return sorted(result, key=lambda item: (item[1], item[2], item[3]))

    def _segments(
        self,
        asset: CourseAsset,
        *,
        quality_profile: str,
        cloud_processing_allowed: bool,
    ) -> list[ExtractedTutorialSegment]:
        source = Path(asset.stored_path)
        if asset.mime_type == "text/plain":
            lines = source.read_text(encoding="utf-8-sig").splitlines()
            result: list[ExtractedTutorialSegment] = []
            for line_number, line in enumerate(lines, start=1):
                text = line.strip()
                if not text:
                    continue
                match = TIME_RANGE.search(text)
                start_ms = int(float(match.group("start")) * 1000) if match else None
                end_ms = int(float(match.group("end")) * 1000) if match else None
                result.append(
                    ExtractedTutorialSegment(
                        text=text,
                        start_ms=start_ms,
                        end_ms=end_ms,
                        source_page=line_number,
                        transcript_confidence=1.0,
                        segment_type=TutorialSegmentType.LECTURE,
                        classification_confidence=1.0,
                        visual_cues=("source:plain_text",),
                    )
                )
            return result
        if asset.mime_type.startswith(("video/", "audio/")):
            analysis: MediaAnalysis | None = None
            if asset.mime_type.startswith("video/") and self.media_analyzer is not None:
                analysis = self.media_analyzer.analyze(
                    source,
                    material_id=asset.id,
                    output_dir=source.parent / "analysis" / "tutorial-evidence",
                    quality_profile=quality_profile,
                    cloud_processing_allowed=cloud_processing_allowed,
                )
                transcript = analysis.transcript
                source.with_suffix(".tutorial-analysis.json").write_text(
                    analysis.model_dump_json(indent=2),
                    encoding="utf-8",
                )
            else:
                if self.transcriber is None:
                    raise ValueError("tutorial_transcriber_unavailable")
                transcript = self.transcriber.transcribe(
                    source,
                    quality_profile=quality_profile,
                    cloud_processing_allowed=cloud_processing_allowed,
                )
            source.with_suffix(".transcript.json").write_text(
                transcript.model_dump_json(indent=2),
                encoding="utf-8",
            )
            raw_segments = self._split_transcript(transcript)
            if analysis is not None:
                raw_segments = self._insert_visual_gaps(raw_segments, analysis)
            result: list[ExtractedTutorialSegment] = []
            previous_type = TutorialSegmentType.UNKNOWN
            for text, start_ms, end_ms, source_page, confidence in raw_segments:
                ocr_texts = self._nearby_ocr(analysis.frames, start_ms, end_ms) if analysis is not None else ()
                segment_type, classification_confidence, cues = self._classify(
                    text=text,
                    ocr_texts=ocr_texts,
                    previous_type=previous_type,
                    transcript_confidence=confidence,
                )
                result.append(
                    ExtractedTutorialSegment(
                        text=text,
                        start_ms=start_ms,
                        end_ms=end_ms,
                        source_page=source_page,
                        transcript_confidence=confidence,
                        segment_type=segment_type,
                        classification_confidence=classification_confidence,
                        ocr_texts=ocr_texts,
                        visual_cues=cues,
                    )
                )
                previous_type = segment_type
            return result
        return []

    def process(
        self,
        session: Session,
        course_id: str,
        *,
        quality_profile: str = "production",
        cloud_processing_allowed: bool = False,
    ) -> EditingRecipe:
        course = session.get(Course, course_id)
        if course is None:
            raise ValueError("course_not_found")
        tutorials = list(
            session.exec(
                select(CourseAsset)
                .where(CourseAsset.course_id == course_id)
                .where(CourseAsset.role == CourseAssetRole.TUTORIAL)
                .order_by(CourseAsset.created_at, CourseAsset.id)
            ).all()
        )
        if not tutorials:
            raise ValueError("course_tutorial_required")

        run = CourseProcessingRun(course_id=course_id, state="processing")
        course.status = "processing"
        session.add_all([run, course])
        session.commit()
        try:
            extracted: list[tuple[CourseAsset, ExtractedTutorialSegment]] = []
            transcript_parts: list[str] = []
            for tutorial in tutorials:
                segments = self._segments(
                    tutorial,
                    quality_profile=quality_profile,
                    cloud_processing_allowed=cloud_processing_allowed,
                )
                for segment in segments:
                    if not 0 <= segment.transcript_confidence <= 1:
                        raise ValueError("tutorial_evidence_confidence_invalid")
                    if not 0 <= segment.classification_confidence <= 1:
                        raise ValueError("tutorial_classification_confidence_invalid")
                    extracted.append((tutorial, segment))
                    if segment.text.strip():
                        transcript_parts.append(segment.text.strip())
            if not extracted or not transcript_parts:
                raise ValueError("tutorial_text_not_extracted")
            existing = session.exec(
                select(EditingRecipe)
                .where(EditingRecipe.course_id == course_id)
                .order_by(EditingRecipe.version.desc())
            ).first()
            recipe = EditingRecipe(
                course_id=course_id,
                version=(existing.version + 1) if existing else 1,
                title=f"{course.title}剪辑规则",
                summary="从课程教程中提取的、带原文位置引用的剪辑规则",
                tutorial_asset_id=tutorials[0].id,
                transcript_sha256=hashlib.sha256(" ".join(transcript_parts).encode("utf-8")).hexdigest(),
            )
            session.add(recipe)
            session.commit()
            rule_records: list[tuple[str, ExtractedTutorialSegment, EditingRule]] = []
            rule_order = 0
            for tutorial, segment in extracted:
                if segment.segment_type != TutorialSegmentType.LECTURE or not segment.text.strip():
                    continue
                rule_order += 1
                rule = EditingRule(
                        recipe_id=recipe.id,
                        category=_category(segment.text),
                        instruction=segment.text,
                        evidence_text=segment.text,
                        confidence=segment.classification_confidence,
                        source_asset_id=tutorial.id,
                        source_start_ms=segment.start_ms,
                        source_end_ms=segment.end_ms,
                        source_page=segment.source_page,
                        sort_order=rule_order,
                    )
                session.add(rule)
                rule_records.append((tutorial.id, segment, rule))

            def distance_ms(left: ExtractedTutorialSegment, right: ExtractedTutorialSegment) -> int:
                if left.start_ms is None or left.end_ms is None or right.start_ms is None or right.end_ms is None:
                    return 2**31 - 1
                return abs((left.start_ms + left.end_ms) - (right.start_ms + right.end_ms)) // 2

            segment_rows: list[TutorialSegment] = []
            for segment_order, (tutorial, segment) in enumerate(extracted, start=1):
                related_rule_ids = [
                    rule.id
                    for asset_id, rule_segment, rule in rule_records
                    if asset_id == tutorial.id and rule_segment is segment
                ]
                if not related_rule_ids and segment.segment_type in {
                    TutorialSegmentType.SOFTWARE_OPERATION,
                    TutorialSegmentType.FINISHED_EXAMPLE,
                }:
                    candidates = [
                        record
                        for record in rule_records
                        if record[0] == tutorial.id
                        and record[1].end_ms is not None
                        and segment.start_ms is not None
                        and record[1].end_ms <= segment.start_ms
                    ]
                    if candidates:
                        nearest = min(candidates, key=lambda record: distance_ms(segment, record[1]))
                        if distance_ms(segment, nearest[1]) <= 30_000:
                            related_rule_ids = [nearest[2].id]
                segment_rows.append(
                    TutorialSegment(
                        recipe_id=recipe.id,
                        source_asset_id=tutorial.id,
                        segment_type=segment.segment_type,
                        start_ms=segment.start_ms,
                        end_ms=segment.end_ms,
                        source_page=segment.source_page,
                        transcript_text=segment.text,
                        ocr_text_json=json.dumps(segment.ocr_texts, ensure_ascii=False),
                        visual_cues_json=json.dumps(segment.visual_cues, ensure_ascii=False),
                        related_rule_ids_json=json.dumps(related_rule_ids, ensure_ascii=False),
                        confidence=segment.classification_confidence,
                        sort_order=segment_order,
                    )
                )
            session.add_all(segment_rows)
            run.state = "completed"
            run.finished_at = datetime.now(UTC)
            course.status = "processed"
            course.updated_at = datetime.now(UTC)
            session.add_all([run, course])
            session.commit()
            session.refresh(recipe)
            return recipe
        except Exception as error:
            session.rollback()
            run.state = "failed"
            run.error_code = str(error)
            run.finished_at = datetime.now(UTC)
            course.status = "failed"
            session.add_all([run, course])
            session.commit()
            raise
