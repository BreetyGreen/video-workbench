from pathlib import Path

from app.schemas.editing import CaptionCue
from app.services.caption_service import CaptionService


def test_semantic_segments_preserve_all_text_and_prefer_phrase_boundaries():
    text = "沙发不再粘毛，其实只差这一步。先逆着毛发轻轻梳开，再顺着方向带走浮毛。"

    chunks = CaptionService.segment_text(text, max_chars=14)

    assert "".join(chunks) == text
    assert all(len(chunk) <= 14 for chunk in chunks)
    assert chunks[0] == "沙发不再粘毛，"
    assert chunks[-1].endswith("。")


def test_ass_supports_keyword_emphasis_and_safe_placement(tmp_path: Path):
    output = tmp_path / "captions.ass"
    cue = CaptionCue(
        material_id="voiceover",
        text="沙发不再粘毛",
        start_seconds=0,
        end_seconds=2,
        source_start_seconds=0,
        source_end_seconds=2,
        emphasis_terms=["不再粘毛"],
        placement="top",
    )

    CaptionService.write_ass([cue], output)
    content = output.read_text(encoding="utf-8-sig")

    assert "Style: CaptionTop" in content
    assert "Style: CaptionBottom" in content
    assert "CaptionTop" in content
    assert r"{\c&H" in content
    assert "不再粘毛" in content
