from __future__ import annotations

import re
from pathlib import Path

from app.schemas.editing import CaptionCue


class CaptionService:
    """Writes portable caption files from the authoritative edit timeline."""

    def __init__(self, *, font_name: str = "Microsoft YaHei", font_size: int = 78, outline: int = 5,
                 title_font_size: int = 118, highlight_color: str = "FFE500", shadow: int = 3, pop_in: bool = True):
        self.font_name = font_name.strip() or "Microsoft YaHei"
        self.font_size = max(24, int(font_size))
        self.outline = max(0, int(outline))
        self.title_font_size = max(40, int(title_font_size))
        self.highlight_color = self._normalize_hex(highlight_color)
        self.shadow = max(0, int(shadow))
        self.pop_in = bool(pop_in)

    @staticmethod
    def _normalize_hex(value: str) -> str:
        cleaned = re.sub(r"[^0-9A-Fa-f]", "", value or "")
        return cleaned.upper() if len(cleaned) == 6 else "FFE500"

    @staticmethod
    def _ass_color(hex_rgb: str) -> str:
        """RGB hex -> ASS &HBBGGRR& (no alpha)."""
        red, green, blue = hex_rgb[0:2], hex_rgb[2:4], hex_rgb[4:6]
        return f"&H{blue}{green}{red}&"

    @staticmethod
    def hex_to_rgb_floats(hex_rgb: str) -> tuple[float, float, float]:
        cleaned = re.sub(r"[^0-9A-Fa-f]", "", hex_rgb or "")
        if len(cleaned) != 6:
            cleaned = "FFE500"
        return tuple(int(cleaned[index : index + 2], 16) / 255 for index in (0, 2, 4))  # type: ignore[return-value]

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
    def segment_text(text: str, max_chars: int = 16, *, sentence_per_chunk: bool = False) -> list[str]:
        """Split narration into caption-sized chunks at phrase boundaries.

        With ``sentence_per_chunk`` a sentence end (。！？!?) always closes the chunk,
        so one narration beat becomes one on-screen caption; longer sentences still
        wrap by ``max_chars``. A dangling punctuation-only remainder is never emitted
        on its own line.
        """
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
                pieces = [phrase[index : index + max_chars] for index in range(0, len(phrase), max_chars)]
                if len(pieces) > 1 and not re.search(r"[^，。！？!?；;、]", pieces[-1]):
                    tail = pieces.pop()
                    pieces[-1] += tail
                chunks.extend(pieces)
                continue
            if current and len(current) + len(phrase) > max_chars:
                chunks.append(current)
                current = phrase
            else:
                current += phrase
            if sentence_per_chunk and current and current[-1] in "。！？!?":
                chunks.append(current)
                current = ""
        if current:
            chunks.append(current)
        return chunks

    @staticmethod
    def display_text(text: str) -> str:
        """On-screen form of a caption: no trailing sentence punctuation (reference-cut style)."""
        return text.rstrip("。！？!?；;，,").strip() or text

    @classmethod
    def _wrap(cls, text: str, limit: int = 16) -> str:
        """Display wrapping: pack phrases into lines of at most ``limit`` chars; a phrase
        longer than a line is split into balanced pieces (7 + 6, never 11 + 2)."""
        compact = "".join(cls.display_text(text).split())
        phrases = [cls.display_text(item) for item in re.findall(r"[^，。！？!?；;、]+[，。！？!?；;、]?", compact)] or [compact]
        lines: list[str] = []
        current = ""
        for phrase in phrases:
            if not phrase:
                continue
            if len(phrase) > limit:
                if current:
                    lines.append(current)
                    current = ""
                count = -(-len(phrase) // limit)
                per_line = -(-len(phrase) // count)
                lines.extend(phrase[index : index + per_line] for index in range(0, len(phrase), per_line))
                continue
            if current and len(current) + len(phrase) > limit:
                lines.append(current)
                current = phrase
            else:
                current += phrase
        if current:
            lines.append(current)
        return "\n".join(lines)

    @staticmethod
    def _escape_ass_literal(text: str) -> str:
        return text.replace("\\", r"\\").replace("{", r"\{").replace("}", r"\}")

    def _ass_text(self, cue: CaptionCue, *, limit: int = 16) -> str:
        cls = type(self)
        wrapped = cls._wrap(cue.text, limit=limit)
        terms = sorted({term for term in cue.emphasis_terms if term}, key=len, reverse=True)
        if not terms:
            return cls._escape_ass_literal(wrapped).replace("\n", r"\N")
        base_size = self.title_font_size if cue.style == "title" else self.font_size
        accent_size = round(base_size * 1.2)
        accent = self._ass_color(self.highlight_color)
        pattern = re.compile("(" + "|".join(re.escape(term) for term in terms) + ")")
        parts = []
        for part in pattern.split(wrapped):
            if not part:
                continue
            escaped = cls._escape_ass_literal(part).replace("\n", r"\N")
            if part in terms:
                # Punch word: accent colour, 15 % larger, then back to the style's white/size
                # explicitly (not \r, which would also cancel the pop-in scale mid-line).
                parts.append(rf"{{\c{accent}\fs{accent_size}}}" + escaped + rf"{{\c&HFFFFFF&\fs{base_size}}}")
            else:
                parts.append(escaped)
        return "".join(parts)

    def _entrance(self, cue: CaptionCue) -> str:
        """Pop-in: start slightly oversized and settle within ~0.1 s, like a Jianying 弹入."""
        if not self.pop_in:
            return ""
        if cue.style == "title":
            return r"{\fad(0,120)\fscx135\fscy135\t(0,150,\fscx100\fscy100)}"
        return r"{\fad(40,30)\fscx118\fscy118\t(0,110,\fscx100\fscy100)}"

    def _ass_header(self) -> str:
        font, size, outline, shadow = self.font_name, self.font_size, self.outline, self.shadow
        title_outline = max(outline + 2, 5)
        return f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: CaptionBottom,{font},{size},&H00FFFFFF,&H000000FF,&H0016161A,&H60000000,-1,0,0,0,100,100,1.5,0,1,{outline},{shadow},2,74,74,240,1
Style: CaptionTop,{font},{size},&H00FFFFFF,&H000000FF,&H0016161A,&H60000000,-1,0,0,0,100,100,1.5,0,1,{outline},{shadow},8,74,74,190,1
Style: CaptionMiddle,{font},{size},&H00FFFFFF,&H000000FF,&H0016161A,&H60000000,-1,0,0,0,100,100,1.5,0,1,{outline},{shadow},5,74,74,0,1
Style: Title,{font},{self.title_font_size},&H00FFFFFF,&H000000FF,&H0016161A,&H40000000,-1,0,0,0,100,100,3,0,1,{title_outline},{max(shadow, 4)},8,74,74,560,1
Style: TitleGlow,{font},{self.title_font_size},&H00FFFFFF,&H000000FF,&H00000000,&H00000000,-1,0,0,0,100,100,3,0,1,{title_outline + 12},0,8,74,74,560,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    def write_ass(self, captions: list[CaptionCue], output: Path) -> Path:
        cls = type(self)
        resolved = output.resolve()
        resolved.parent.mkdir(parents=True, exist_ok=True)
        header = self._ass_header()
        # Wrap by what fits the 1080 px canvas at this font size (margins 74 px each side).
        chars_per_line = max(6, (1080 - 2 * 74) // max(24, self.font_size))
        rows: list[str] = []
        for cue in captions:
            text = self._ass_text(cue, limit=chars_per_line)
            entrance = self._entrance(cue)
            style = (
                "Title"
                if cue.style == "title"
                else {"top": "CaptionTop", "middle": "CaptionMiddle"}.get(cue.placement, "CaptionBottom")
            )
            timing = f"{cls._ass_time(cue.start_seconds)},{cls._ass_time(cue.end_seconds)}"
            if cue.style == "title":
                # Soft dark glow behind the product name so it reads on bright packaging.
                glow_text = cls._escape_ass_literal(cls._wrap(cue.text, limit=chars_per_line)).replace("\n", r"\N")
                rows.append(f"Dialogue: 0,{timing},TitleGlow,,0,0,0,,{entrance}{{\\blur16\\3a&H70&\\1a&HFF&}}{glow_text}")
                rows.append(f"Dialogue: 1,{timing},{style},,0,0,0,,{entrance}{text}")
                continue
            rows.append(f"Dialogue: 0,{timing},{style},,0,0,0,,{entrance}{text}")
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
