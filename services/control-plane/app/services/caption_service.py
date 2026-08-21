from __future__ import annotations

import re
from pathlib import Path

from app.schemas.editing import CaptionCue


class CaptionService:
    """Writes portable caption files from the authoritative edit timeline."""

    @staticmethod
    def _ass_time(seconds: float) -> str:
        centiseconds = max(0, round(seconds * 100))
        hours, remainder = divmod(centiseconds, 360_000)
        minutes, remainder = divmod(remainder, 6_000)
        secs, centis = divmod(remainder, 100)
        return f"{hours}:{minutes:02d}:{secs:02d}.{centis:02d}"

    @staticmethod
    def _srt_time(seconds: float) -> str:
        milliseconds = max(0, round(seconds * 1000))
        hours, remainder = divmod(milliseconds, 3_600_000)
        minutes, remainder = divmod(remainder, 60_000)
        secs, millis = divmod(remainder, 1_000)
        return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"

    @staticmethod
    def segment_text(text: str, max_chars: int = 16) -> list[str]:
        compact = "".join(text.replace("\n", " ").split())
        if not compact:
            return []
        phrases = re.findall(r"[^，。！？!?；;、]+[，。！？!?；;、]?", compact)
        chunks: list[str] = []
        current = ""
        for phrase in phrases or [compact]:
            if len(phrase) > max_chars:
                if current:
                    chunks.append(current)
                    current = ""
                chunks.extend(phrase[index : index + max_chars] for index in range(0, len(phrase), max_chars))
                continue
            if current and len(current) + len(phrase) > max_chars:
                chunks.append(current)
                current = phrase
            else:
                current += phrase
        if current:
            chunks.append(current)
        return chunks

    @classmethod
    def _wrap(cls, text: str, limit: int = 16) -> str:
        return "\n".join(cls.segment_text(text, max_chars=limit))

    @staticmethod
    def _escape_ass_literal(text: str) -> str:
        return text.replace("\\", r"\\").replace("{", r"\{").replace("}", r"\}")

    @classmethod
    def _ass_text(cls, cue: CaptionCue) -> str:
        wrapped = cls._wrap(cue.text)
        terms = sorted({term for term in cue.emphasis_terms if term}, key=len, reverse=True)
        if not terms:
            return cls._escape_ass_literal(wrapped).replace("\n", r"\N")
        pattern = re.compile("(" + "|".join(re.escape(term) for term in terms) + ")")
        parts = []
        for part in pattern.split(wrapped):
            if not part:
                continue
            escaped = cls._escape_ass_literal(part).replace("\n", r"\N")
            if part in terms:
                parts.append(r"{\c&H006D5BEF&}" + escaped + r"{\c&H00FFFFFF&}")
            else:
                parts.append(escaped)
        return "".join(parts)

    @classmethod
    def write_ass(cls, captions: list[CaptionCue], output: Path) -> Path:
        resolved = output.resolve()
        resolved.parent.mkdir(parents=True, exist_ok=True)
        header = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: CaptionBottom,Noto Sans CJK SC,60,&H00FFFFFF,&H000000FF,&H0016161A,&H00000000,-1,0,0,0,100,100,1,0,1,4,0,2,74,74,240,1
Style: CaptionTop,Noto Sans CJK SC,60,&H00FFFFFF,&H000000FF,&H0016161A,&H00000000,-1,0,0,0,100,100,1,0,1,4,0,8,74,74,190,1
Style: CaptionMiddle,Noto Sans CJK SC,60,&H00FFFFFF,&H000000FF,&H0016161A,&H00000000,-1,0,0,0,100,100,1,0,1,4,0,5,74,74,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
        rows: list[str] = []
        for cue in captions:
            text = cls._ass_text(cue)
            style = {"top": "CaptionTop", "middle": "CaptionMiddle"}.get(cue.placement, "CaptionBottom")
            rows.append(
                "Dialogue: 0,"
                f"{cls._ass_time(cue.start_seconds)},{cls._ass_time(cue.end_seconds)},"
                f"{style},,0,0,0,,{text}"
            )
        resolved.write_text(header + "\n".join(rows) + "\n", encoding="utf-8-sig")
        return resolved

    @classmethod
    def write_srt(cls, captions: list[CaptionCue], output: Path) -> Path:
        resolved = output.resolve()
        resolved.parent.mkdir(parents=True, exist_ok=True)
        blocks = []
        for index, cue in enumerate(captions, start=1):
            blocks.append(
                f"{index}\n{cls._srt_time(cue.start_seconds)} --> {cls._srt_time(cue.end_seconds)}\n"
                f"{cls._wrap(cue.text)}"
            )
        resolved.write_text("\n\n".join(blocks) + ("\n" if blocks else ""), encoding="utf-8")
        return resolved
