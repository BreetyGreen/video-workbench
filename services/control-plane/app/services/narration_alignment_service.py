"""Validate ASR word timing against the complete narration; never estimate timing."""

from dataclasses import dataclass
from difflib import SequenceMatcher
from math import isfinite
import re

from app.schemas.editing import CaptionCue, TranscriptResult
from app.services.caption_service import CaptionService


@dataclass(frozen=True)
class AlignmentResult:
    captions: list[CaptionCue]
    status: str
    reason: str


def inherit_caption_styles(
    aligned: list[CaptionCue], originals: list[CaptionCue]
) -> list[CaptionCue]:
    """Transfer existing presentation choices without replacing actual word times."""
    exact = {}
    for cue in originals:
        exact.setdefault(cue.text, cue)
    terms = list(dict.fromkeys(term for cue in originals for term in cue.emphasis_terms if term))
    result = []
    for index, cue in enumerate(aligned):
        original = exact.get(cue.text)
        placement = (original.placement if original is not None else
                     originals[0].placement if index == 0 and originals else 'bottom')
        # A cue that kept its exact text keeps its own punch words; only re-split cues
        # fall back to the pooled terms (otherwise a word highlighted in one line leaks
        # into every other line that happens to contain it).
        own = [term for term in original.emphasis_terms if term in cue.text] if original is not None else None
        result.append(cue.model_copy(deep=True, update={
            'placement': placement,
            'emphasis_terms': own if own is not None else [term for term in terms if term in cue.text],
        }))
    return result


_CN_DIGITS = {"零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
_CN_UNITS = {"十": 10, "百": 100, "千": 1000, "万": 10000}
_CN_NUMBER = re.compile("[零〇一二两三四五六七八九十百千万]+")


def _chinese_numeral_to_int(text: str) -> int | None:
    """Convert a pure Chinese numeral run (两百四十五, 十二, 零) to an int; None when not a number."""
    total = 0
    section = 0
    number = 0
    for char in text:
        if char in _CN_DIGITS:
            number = _CN_DIGITS[char]
        elif char in _CN_UNITS:
            unit = _CN_UNITS[char]
            if unit == 10000:
                total = (total + section + (number or 0)) * unit
                section = number = 0
            else:
                section += (number or 1) * unit
                number = 0
        else:
            return None
    return total + section + number


def _digits_normalized(text: str) -> str:
    """Spell Chinese numerals as Arabic digits so ASR inverse-text-normalization matches."""
    def replace(match: re.Match) -> str:
        value = _chinese_numeral_to_int(match.group(0))
        return str(value) if value is not None else match.group(0)
    return _CN_NUMBER.sub(replace, text)


def _normalized(text: str) -> str:
    return "".join(char.casefold() for char in text if char.isalnum())


FUZZY_MIN_RATIO = 0.85
FUZZY_MAX_LENGTH_DRIFT = 0.10


def _tolerant_char_map(expected: str, spoken: str) -> tuple[list[int], float] | None:
    """Map every expected char to a spoken-char index when the texts differ only by
    homophones/ITN spelling; None when the difference is more than that."""
    if not expected or not spoken:
        return None
    if abs(len(spoken) - len(expected)) > max(0, int(FUZZY_MAX_LENGTH_DRIFT * len(expected))):
        return None
    matcher = SequenceMatcher(None, spoken, expected, autojunk=False)
    ratio = matcher.ratio()
    if ratio < FUZZY_MIN_RATIO:
        return None
    opcodes = matcher.get_opcodes()
    if opcodes[0][0] != "equal" or opcodes[-1][0] != "equal":
        return None
    mapping: list[int] = [0] * len(expected)
    for tag, i1, i2, j1, j2 in opcodes:
        if tag == "equal":
            for offset in range(j2 - j1):
                mapping[j1 + offset] = i1 + offset
        elif tag == "replace":
            span = max(1, i2 - i1)
            for offset in range(j2 - j1):
                mapping[j1 + offset] = min(i2 - 1, i1 + (offset * span) // max(1, j2 - j1))
        elif tag == "insert":  # expected has chars the ASR dropped: pin to the last spoken char
            for offset in range(j2 - j1):
                mapping[j1 + offset] = max(0, min(len(spoken) - 1, i1 - 1 if i1 > 0 else 0))
        # "delete": spoken has extra chars; nothing in expected maps to them
    return mapping, ratio


def align_narration(
    text: str, transcript: TranscriptResult, duration_seconds: float
) -> AlignmentResult:
    """Return only whole-word caption groups covering an exact full-text match.

    A word up to 50 ms beyond the probed duration is accepted unchanged; callers
    must not mistake this probe tolerance for invented/interpolated word timing.
    Punctuation and whitespace are ignored for matching, not substituted by ASR.
    The caller can rebind the synthetic ``narration`` material ID to its audio.
    """
    def unavailable(reason: str) -> AlignmentResult:
        return AlignmentResult([], "unavailable", reason)

    if not isfinite(duration_seconds) or duration_seconds <= 0:
        return unavailable("invalid_duration")
    expected = _normalized(text)
    if not expected:
        return unavailable("empty_narration")
    words = [word for segment in transcript.segments for word in segment.words]
    if not words or not any(_normalized(word.text) for word in words):
        return unavailable("missing_timed_words")
    previous_end = 0.0
    for word in words:
        start, end = word.start_seconds, word.end_seconds
        if (not isfinite(start) or not isfinite(end) or start < previous_end
                or start < 0 or end <= start or end > duration_seconds + 0.05):
            return unavailable("invalid_word_timestamps")
        previous_end = end
    # Standalone punctuation tokens carry no spoken characters. Their times are
    # validated above but never used to lengthen a caption's spoken interval.
    words = [word for word in words if _normalized(word.text)]
    spoken = "".join(_normalized(word.text) for word in words)
    status_reason = "full_narration_timed_words_match"
    char_map: list[int] | None = None
    if spoken != expected:
        # ASR spells numbers as digits and confuses homophones (品牌名尤其如此);
        # accept a close match and reuse the real word times, never invented ones.
        expected_digits = _normalized(_digits_normalized(text))
        tolerant = _tolerant_char_map(expected_digits, spoken)
        if tolerant is None:
            return unavailable("narration_text_mismatch")
        mapping, ratio = tolerant
        # Map narration (as written) chars onto the digit-normalized string first.
        written_to_digits = _written_to_digit_offsets(text)
        if written_to_digits is None or len(written_to_digits) != len(expected):
            return unavailable("narration_text_mismatch")
        char_map = [mapping[min(len(mapping) - 1, written_to_digits[index])] for index in range(len(expected))]
        status_reason = f"tolerant_match:ratio={ratio:.2f}:spoken={len(spoken)}:expected={len(expected)}"

    word_ends: dict[int, int] = {}
    offset = 0
    for index, word in enumerate(words):
        offset += len(_normalized(word.text))
        word_ends[offset] = index
    if char_map is not None:
        # Re-express word boundaries in expected-char offsets via the tolerant map:
        # an expected offset ends a word when its mapped spoken char is that word's last char.
        spoken_word_end_to_index = dict(word_ends)
        word_ends = {}
        for index in range(len(expected)):
            spoken_offset = char_map[index] + 1
            if spoken_offset in spoken_word_end_to_index:
                word_ends[index + 1] = spoken_word_end_to_index[spoken_offset]
        word_ends[len(expected)] = len(words) - 1
    # A preferred split falling inside an ASR word is dropped, merging adjacent
    # groups until an unambiguous word boundary; no character-rate interpolation.
    boundaries = []
    offset = 0
    for chunk in CaptionService.segment_text(text, sentence_per_chunk=True):
        offset += len(_normalized(chunk))
        if offset in word_ends and (not boundaries or boundaries[-1] != offset):
            boundaries.append(offset)
    if not boundaries or boundaries[-1] != len(expected):
        boundaries.append(len(expected))

    compact = "".join(text.split())
    # Recover slices from the original narration, including leading/trailing
    # punctuation which the segmenter can otherwise omit.
    raw_ends: dict[int, int] = {}
    offset = 0
    for index, char in enumerate(compact):
        offset += len(_normalized(char))
        raw_ends[offset] = index + 1
    captions = []
    first_word = raw_start = 0
    for boundary in boundaries:
        last_word = word_ends[boundary]
        raw_end = raw_ends[boundary]
        start = words[first_word].start_seconds
        end = words[last_word].end_seconds
        captions.append(CaptionCue(
            material_id="narration", text=compact[raw_start:raw_end],
            start_seconds=start, end_seconds=end,
            source_start_seconds=start, source_end_seconds=end,
        ))
        first_word = last_word + 1
        raw_start = raw_end
    return AlignmentResult(captions, "word_aligned", status_reason)


def _written_to_digit_offsets(text: str) -> list[int] | None:
    """For each normalized char of the written narration, the offset of its counterpart in the
    digit-normalized narration (a Chinese numeral run maps onto its Arabic spelling)."""
    offsets: list[int] = []
    digit_offset = 0
    position = 0
    for match in _CN_NUMBER.finditer(text):
        for char in text[position:match.start()]:
            if char.isalnum():
                offsets.append(digit_offset)
                digit_offset += 1
        value = _chinese_numeral_to_int(match.group(0))
        if value is None:
            for char in match.group(0):
                offsets.append(digit_offset)
                digit_offset += 1
        else:
            spelled = len(str(value))
            run = match.group(0)
            for index in range(len(run)):
                offsets.append(digit_offset + min(spelled - 1, (index * spelled) // len(run)))
            digit_offset += spelled
        position = match.end()
    for char in text[position:]:
        if char.isalnum():
            offsets.append(digit_offset)
            digit_offset += 1
    return offsets
