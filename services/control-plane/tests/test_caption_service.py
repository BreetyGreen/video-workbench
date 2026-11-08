import re
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

    CaptionService().write_ass([cue], output)
    content = output.read_text(encoding="utf-8-sig")

    assert "Style: CaptionTop" in content
    assert "Style: CaptionBottom" in content
    assert "CaptionTop" in content
    assert r"{\c&H" in content
    assert "不再粘毛" in content


def test_title_card_uses_dedicated_large_style(tmp_path: Path):
    output = tmp_path / "captions.ass"
    title = CaptionCue(
        material_id="title",
        text="果知纯绿豆沙",
        start_seconds=0,
        end_seconds=1.4,
        source_start_seconds=0,
        source_end_seconds=1.4,
        placement="middle",
        style="title",
    )
    narration = CaptionCue(
        material_id="narration",
        text="先来一口",
        start_seconds=0.3,
        end_seconds=1.2,
        source_start_seconds=0.3,
        source_end_seconds=1.2,
        placement="top",
    )

    CaptionService().write_ass([title, narration], output)
    content = output.read_text(encoding="utf-8-sig")

    assert "Style: Title," in content
    assert ",Title,,0,0,0,," in content and "果知纯绿豆沙" in content
    assert ",CaptionTop,,0,0,0,," in content and "先来一口" in content
    assert ",Title,,0,0,0,,果知纯绿豆沙" in re.sub(r"\{[^}]*\}", "", content)
    assert CaptionCue.model_validate(narration.model_dump()).style == "caption"


def test_large_fonts_wrap_to_what_fits_the_canvas(tmp_path: Path):
    cue = CaptionCue(material_id="narration", text="绿豆熬制零脂肪倒出来绵细密腻", start_seconds=0, end_seconds=2,
                     source_start_seconds=0, source_end_seconds=2, placement="top")
    big = CaptionService(font_name="Microsoft YaHei", font_size=78).write_ass([cue], tmp_path / "big.ass").read_text(encoding="utf-8-sig")
    small = CaptionService(font_size=48).write_ass([cue], tmp_path / "small.ass").read_text(encoding="utf-8-six" if False else "utf-8-sig")
    assert "Style: CaptionTop,Microsoft YaHei,78," in big
    assert big.count(r"\N") >= 1  # 14 chars cannot fit one 78 px line
    assert r"\N" not in small.splitlines()[-1]


def test_sentence_per_chunk_and_display_text_drop_orphan_punctuation(tmp_path: Path):
    text = "绿豆熬制零脂肪。倒出来绵细密腻。快换成这个果知纯绿豆沙。"
    assert CaptionService.segment_text(text, max_chars=16) == ["绿豆熬制零脂肪。倒出来绵细密腻。", "快换成这个果知纯绿豆沙。"]
    assert CaptionService.segment_text(text, max_chars=16, sentence_per_chunk=True) == [
        "绿豆熬制零脂肪。", "倒出来绵细密腻。", "快换成这个果知纯绿豆沙。"]
    # 11 chars per line at 78 px: the sentence-final period must not become its own line.
    assert CaptionService.segment_text("快换成这个果知纯绿豆沙。", max_chars=11) == ["快换成这个果知纯绿豆沙。"]
    assert CaptionService.display_text("快换成这个果知纯绿豆沙。") == "快换成这个果知纯绿豆沙"
    cue = CaptionCue(material_id="narration", text="快换成这个果知纯绿豆沙。", start_seconds=0, end_seconds=2,
                     source_start_seconds=0, source_end_seconds=2, placement="top")
    ass = CaptionService(font_size=78).write_ass([cue], tmp_path / "c.ass").read_text(encoding="utf-8-sig")
    last = re.sub(r"\{[^}]*\}", "", ass.strip().splitlines()[-1])
    assert last.endswith(",,快换成这个果知纯绿豆沙") and r"\N" not in last


def test_long_captions_wrap_into_balanced_lines_without_orphans():
    assert CaptionService._wrap("植物饮料常温保质十二个月。", limit=11) == "植物饮料常温\n保质十二个月"
    assert CaptionService._wrap("绿豆熬制零脂肪。", limit=11) == "绿豆熬制零脂肪"
    assert [len(line) for line in CaptionService._wrap("字" * 30, limit=11).split("\n")] == [10, 10, 10]
    assert CaptionService._wrap("下午犯困口干，奶茶甜腻又长胖。", limit=11) == "下午犯困口干\n奶茶甜腻又长胖"


def test_punch_words_get_accent_colour_size_and_pop_in(tmp_path: Path):
    cue = CaptionCue(material_id="narration", text="整箱十瓶两百四十五克。", start_seconds=0, end_seconds=2,
                     source_start_seconds=0, source_end_seconds=2, placement="top", emphasis_terms=["十瓶", "两百四十五克"])
    service = CaptionService(font_size=80, highlight_color="#ffe500", shadow=3)
    ass = service.write_ass([cue], tmp_path / "c.ass").read_text(encoding="utf-8-sig")
    line = ass.strip().splitlines()[-1]

    # accent colour is RGB FFE500 written as ASS &HBBGGRR&, 15 % larger, then back to white/80
    assert r"{\c&H00E5FF&\fs96}十瓶{\c&HFFFFFF&\fs80}" in line
    assert r"{\c&H00E5FF&\fs96}两百四十五克{\c&HFFFFFF&\fs80}" in line
    assert line.split(",,0,0,0,,", 1)[1].startswith(r"{\fad(40,30)\fscx118\fscy118\t(0,110,\fscx100\fscy100)}")
    assert ",1,5,3,8,74,74,190,1" in ass  # BorderStyle 1, outline 5, shadow 3 on the top style
    assert re.sub(r"\{[^}]*\}", "", line).endswith(",,整箱十瓶两百四十五克")

    plain = CaptionService(pop_in=False).write_ass([cue], tmp_path / "p.ass").read_text(encoding="utf-8-sig")
    assert r"\fscx118" not in plain and r"\c&H00E5FF&" in plain


def test_title_card_gets_glow_layer_and_zoom_in(tmp_path: Path):
    title = CaptionCue(material_id="title", text="果知纯绿豆沙", start_seconds=0, end_seconds=1.2,
                       source_start_seconds=0, source_end_seconds=1.2, placement="middle", style="title")
    ass = CaptionService().write_ass([title], tmp_path / "t.ass").read_text(encoding="utf-8-sig")
    lines = [line for line in ass.splitlines() if line.startswith("Dialogue:")]
    assert len(lines) == 2
    assert lines[0].startswith("Dialogue: 0,") and ",TitleGlow,," in lines[0] and r"\blur16" in lines[0]
    assert lines[1].startswith("Dialogue: 1,") and ",Title,," in lines[1]
    assert all(r"\fscx135" in line for line in lines)
    assert "Style: TitleGlow," in ass
