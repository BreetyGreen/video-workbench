import importlib
import importlib.util

import pytest

from app.schemas.editing import CaptionCue, TranscriptResult, TranscriptSegment, TranscriptWord


def align(text, words, duration=20):
    name = "app.services.narration_alignment_service"
    assert importlib.util.find_spec(name) is not None, "alignment helper is not implemented"
    transcript = TranscriptResult.model_construct(segments=[TranscriptSegment.model_construct(
        text="unused segment text", start_seconds=0, end_seconds=20,
        words=[TranscriptWord.model_construct(text=t, start_seconds=s, end_seconds=e)
               for t, s, e in words],
    )])
    return importlib.import_module(name).align_narration(text, transcript, duration)


def test_leading_silence_and_actual_word_end_are_preserved():
    result = align("你好，世界！", [("你好", 1.2, 1.8), ("世界", 2.1, 2.7)])
    assert result.status == "word_aligned"
    assert result.captions[0].text == "你好，世界！"
    assert result.captions[0].start_seconds == 1.2
    assert result.captions[0].end_seconds == 2.7
    assert result.captions[0].source_start_seconds == 1.2
    assert result.captions[0].source_end_seconds == 2.7


def test_punctuation_case_and_whitespace_do_not_change_match():
    result = align("Hello, WORLD!", [("hello", 1, 2), ("world", 2, 3)])
    assert result.status == "word_aligned"
    assert result.captions[0].text == "Hello,WORLD!"


def test_original_leading_punctuation_is_not_lost():
    result = align("！你好。", [("你好", 1, 2)])
    assert result.captions[0].text == "！你好。"


def test_word_crossing_caption_boundary_merges_groups_without_interpolation():
    text = "甲" * 15 + "绿豆沙很好喝。"
    result = align(text, [("甲" * 15, 1, 3), ("绿豆沙", 3.5, 4), ("很好喝", 4.2, 5)])
    assert result.status == "word_aligned"
    assert len(result.captions) == 1
    assert result.captions[0].text == text
    assert result.captions[0].start_seconds == 1
    assert result.captions[0].end_seconds == 5


def test_long_text_splits_at_real_word_boundaries():
    text = "甲" * 16 + "乙" * 16 + "丙。"
    result = align(text, [("甲" * 16, 1, 3), ("乙" * 16, 4, 6), ("丙", 7, 8)])
    assert [c.text for c in result.captions] == ["甲" * 16, "乙" * 16, "丙。"]
    assert [(c.start_seconds, c.end_seconds) for c in result.captions] == [(1, 3), (4, 6), (7, 8)]


@pytest.mark.parametrize("words", [[], [("不同", 1, 2)], [("你好", 1, 2)],
                                   [("你好世界多余", 1, 2)]])
def test_missing_partial_or_hallucinated_speech_is_unavailable(words):
    result = align("你好世界", words)
    assert result.status == "unavailable"
    assert result.reason in {"missing_timed_words", "narration_text_mismatch"}
    assert result.captions == []


@pytest.mark.parametrize("start,end", [(float("nan"), 2), (1, float("inf")),
                                      (-0.01, 2), (2, 2), (3, 2), (1, 20.06)])
def test_invalid_word_times_are_rejected(start, end):
    result = align("你好", [("你好", start, end)])
    assert result.status == "unavailable"
    assert result.reason == "invalid_word_timestamps"
    assert result.captions == []


@pytest.mark.parametrize("duration", [0, -1, float("inf"), float("nan")])
def test_invalid_audio_duration_is_rejected(duration):
    result = align("你好", [("你好", 1, 2)], duration)
    assert result.reason == "invalid_duration"
    assert result.captions == []


def test_overlapping_or_out_of_order_words_are_rejected():
    result = align("你好世界", [("你好", 1, 3), ("世界", 2.9, 4)])
    assert result.reason == "invalid_word_timestamps"
    assert result.captions == []


def test_duration_tolerance_does_not_fabricate_clamped_times():
    result = align("你好", [("你好", 1, 2.04)], duration=2)
    assert result.status == "word_aligned"
    assert result.captions[0].end_seconds == 2.04


@pytest.mark.parametrize("text", ["", " ，！ "])
def test_empty_narration_is_unavailable(text):
    result = align(text, [("你好", 1, 2)])
    assert result.reason == "empty_narration"
    assert result.captions == []


def caption(text, start=1, end=2, placement='bottom', terms=None):
    return CaptionCue(material_id='narration', text=text, start_seconds=start,
        end_seconds=end, source_start_seconds=start, source_end_seconds=end,
        placement=placement, emphasis_terms=terms or [])


def test_aligned_exact_text_inherits_style_but_not_estimated_timing():
    module = importlib.import_module('app.services.narration_alignment_service')
    assert hasattr(module, 'inherit_caption_styles')
    aligned = [caption('清凉绿豆沙', 2, 3)]
    originals = [caption('清凉绿豆沙', 0, 5, 'top', ['绿豆沙', '无关'])]
    before = [cue.model_dump() for cue in aligned + originals]
    result = module.inherit_caption_styles(aligned, originals)
    assert result[0].placement == 'top'
    assert result[0].emphasis_terms == ['绿豆沙']
    assert (result[0].start_seconds, result[0].end_seconds) == (2, 3)
    assert (result[0].source_start_seconds, result[0].source_end_seconds) == (2, 3)
    assert result[0].text == '清凉绿豆沙'
    assert [cue.model_dump() for cue in aligned + originals] == before
    assert result[0] is not aligned[0]


def test_regrouped_alignment_preserves_opening_placement_and_existing_terms():
    module = importlib.import_module('app.services.narration_alignment_service')
    assert hasattr(module, 'inherit_caption_styles')
    aligned = [caption('清凉'), caption('绿豆沙很好喝')]
    originals = [caption('清凉绿豆沙', placement='top', terms=['绿豆沙']),
                 caption('很好喝', placement='middle', terms=['很好喝', '不在字幕'])]
    result = module.inherit_caption_styles(aligned, originals)
    assert [cue.placement for cue in result] == ['top', 'bottom']
    assert [cue.emphasis_terms for cue in result] == [[], ['绿豆沙', '很好喝']]


def test_style_inheritance_handles_empty_inputs():
    module = importlib.import_module('app.services.narration_alignment_service')
    assert hasattr(module, 'inherit_caption_styles')
    assert module.inherit_caption_styles([], [caption('旧字幕')]) == []
    result = module.inherit_caption_styles([caption('新字幕')], [])
    assert result[0].placement == 'bottom'
    assert result[0].emphasis_terms == []


def test_tolerant_match_accepts_homophones_and_digit_spelling_with_real_word_times():
    from app.services.narration_alignment_service import _chinese_numeral_to_int, _digits_normalized

    assert _chinese_numeral_to_int("两百四十五") == 245 and _chinese_numeral_to_int("十二") == 12
    assert _chinese_numeral_to_int("零") == 0 and _chinese_numeral_to_int("一千零五") == 1005
    assert _digits_normalized("整箱两百四十五克十瓶，零脂肪") == "整箱245克10瓶，0脂肪"

    # ASR heard 果汁纯 for 果知纯 and spelled the numbers as digits.
    words = [("换成", 0.2, 0.6), ("果汁", 0.6, 1.0), ("纯", 1.0, 1.2), ("绿豆沙", 1.2, 1.8),
             ("整箱", 2.0, 2.4), ("245", 2.4, 3.0), ("克", 3.0, 3.2), ("10", 3.2, 3.4), ("瓶", 3.4, 3.6)]
    result = align("换成果知纯绿豆沙。整箱两百四十五克十瓶。", words, duration=4)
    assert result.status == "word_aligned"
    assert result.reason.startswith("tolerant_match:ratio=")
    assert [c.text for c in result.captions] == ["换成果知纯绿豆沙。", "整箱两百四十五克十瓶。"]
    assert [(c.start_seconds, c.end_seconds) for c in result.captions] == [(0.2, 1.8), (2.0, 3.6)]


def test_tolerant_match_still_rejects_missing_or_extra_phrases():
    assert align("换成果知纯绿豆沙", [("换成", 0.2, 0.6), ("果汁", 0.6, 1.0)], duration=4).reason == "narration_text_mismatch"
    assert align("你好世界", [("你好", 1, 2), ("世界", 2, 3), ("再见朋友", 3, 4)], duration=5).reason == "narration_text_mismatch"
    assert align("你好世界", [("再见", 1, 2), ("世界", 2, 3)], duration=5).reason == "narration_text_mismatch"


def test_inherited_emphasis_does_not_leak_between_exact_text_cues():
    from app.schemas.editing import CaptionCue
    from app.services.narration_alignment_service import inherit_caption_styles

    def cue(text, terms, start):
        return CaptionCue(material_id="voiceover", text=text, start_seconds=start, end_seconds=start + 1,
                          source_start_seconds=start, source_end_seconds=start + 1, emphasis_terms=terms, placement="top")

    originals = [cue("冰爽一口透心凉。", ["透心凉"], 0), cue("果知纯冰爽绿豆沙。", ["冰爽"], 1)]
    aligned = [cue("冰爽一口透心凉。", [], 0), cue("果知纯冰爽绿豆沙。", [], 1), cue("冰爽的一口", [], 2)]
    result = inherit_caption_styles(aligned, originals)
    assert [c.emphasis_terms for c in result] == [["透心凉"], ["冰爽"], ["冰爽"]]
