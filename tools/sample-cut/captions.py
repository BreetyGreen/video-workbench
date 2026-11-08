"""Styled, animated captions drawn with Pillow (same result on Windows and macOS, no libass needed).

- styles.json holds the style library; pick_style() chooses one per product (mood keywords + stable hash), so
  videos don't all look the same, and copy.json "style" / spec.json subtitle.style can force one.
- emphasis_terms() picks 1-2 words per cue to highlight (numbers+units, product name, punch words), or uses
  copy.json sentences[].emphasis when Codex supplied them. Highlights never add words.
- render_layer() writes one PNG per distinct frame (intro animation frames + a hold frame per cue) and an
  ffconcat list with exact durations; render.py overlays that stream once.

CLI preview: python captions.py preview <style|all> "<text>" [out.png]
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sys
from pathlib import Path

from vw_common import data_home, pil_font

HERE = Path(__file__).resolve().parent
LIB = json.loads((HERE / "styles.json").read_text(encoding="utf-8"))
STYLES: dict = LIB["styles"]
FONT_DIR = Path(os.environ.get("VIDEO_WORKBENCH_FONT_DIR") or data_home() / "fonts")
W, H = 1080, 1920
SIDE = 70  # px kept free left/right (Douyin's right-side buttons start ~ x 960 lower down; captions sit above them)

# ---------------- style choice ----------------


def pick_style(product: str, text: str = "", forced: str | None = None) -> str:
    if forced and forced != "auto":
        if forced not in STYLES:
            raise SystemExit(f"unknown caption style {forced!r}; choose from {', '.join(STYLES)}")
        return forced
    blob = f"{product} {text}"
    moods = {m for m, kws in LIB["mood_keywords"].items() if any(k in blob for k in kws)} or {"通用"}
    scored = sorted(((len(moods & set(s["moods"])), name) for name, s in STYLES.items()), reverse=True)
    best = scored[0][0]
    pool = sorted(name for score, name in scored if score == best and score > 0) or sorted(STYLES)
    h = int(hashlib.sha256(product.encode("utf-8")).hexdigest(), 16)
    return pool[h % len(pool)]


# ---------------- emphasis ----------------

_NUMERAL = r"(?:[零〇一二两三四五六七八九十百千万]{1,8}|\d+(?:\.\d+)?)"
_UNIT = (r"(?:个月|小时|分钟|毫升|大卡|mL|ml|g|kg|瓶|克|升|斤|月|天|年|倍|种|颗|粒|盒|袋|包|次|卡|"
         r"脂肪|脂|糖|能量|添加|负担|香精|色素|防腐剂)")
_NUMBER_TERM = re.compile(rf"{_NUMERAL}{_UNIT}")
PUNCH_WORDS = (
    "透心凉", "冰冰凉凉", "冰爽", "清爽", "清清爽爽", "清润", "清甜", "清香", "茶香", "花香", "原香", "香浓", "醇厚",
    "顺滑", "丝滑", "绵密", "细腻", "沙沙", "饱满", "满满", "真材实料", "现熬", "熬制", "新鲜", "解腻", "不腻",
    "无负担", "零负担", "畅快", "好喝", "回购", "上头", "绝了", "无糖", "原叶萃取", "来一瓶", "来一杯", "常备",
    "刚刚好", "冷藏", "冰镇", "随时",
)


def emphasis_terms(text: str, product_terms=(), max_terms: int = 2) -> list[str]:
    compact = "".join(text.split())
    cands = [(m.start(), m.end(), m.group(0), False) for m in _NUMBER_TERM.finditer(compact)]
    for t in sorted({p for p in product_terms if p}, key=len, reverse=True):
        i = compact.find(t)
        if i >= 0:
            cands.append((i, i + len(t), t, False))
    for w in sorted(PUNCH_WORDS, key=len, reverse=True):
        i = compact.find(w)
        if i >= 0:
            cands.append((i, i + len(w), w, True))
    chosen, punch = [], False
    for s, e, t, is_p in cands:
        if (is_p and punch) or any(not (e <= a or s >= b) for a, b, _ in chosen):
            continue
        chosen.append((s, e, t))
        punch |= is_p
        if len(chosen) >= max_terms:
            break
    return [t for _, _, t in sorted(chosen)]


def product_terms(product: str) -> list[str]:
    compact = re.sub(r"[（(].*?[)）]", "", "".join(product.split()))
    parts = [p for p in re.split(r"[｜|/\-—·,，:：\s]+", product) if len(p) >= 2]
    return list(dict.fromkeys([compact, *parts]))


def spans_of(text: str, terms) -> list[tuple[int, int]]:
    out = []
    for t in sorted(terms, key=len, reverse=True):
        i = text.find(t)
        while i >= 0:
            if all(i >= b or i + len(t) <= a for a, b in out):
                out.append((i, i + len(t)))
                break
            i = text.find(t, i + 1)
    return sorted(out)


# ---------------- cues ----------------


def max_chars_for(style: dict, spec_max: int = 15) -> int:
    scale = max(1.0, style.get("highlight", {}).get("scale", 1.0))
    return max(6, min(spec_max, int((W - 2 * SIDE) / (style["size"] * 1.03 * (1 + (scale - 1) * 0.3)))))


def build_cues(units, max_chars: int, end_all: float, emphasis_for) -> list[dict]:
    """units: [{start,end,text,i}] -> cues [{start,end,text,emph:[[a,b]]}] split at punctuation / max_chars,
    never cutting through an emphasis term."""
    cues = []
    for u in units:
        terms = emphasis_for(u)
        parts = [x for x in re.split(r"[，。！？、,!?；;：:]", u["text"]) if x.strip()]
        chunks = []
        for x in parts:
            x = x.strip()
            while len(x) > max_chars:
                n = math.ceil(len(x) / max_chars)
                cut = math.ceil(len(x) / n)
                for a, b in spans_of(x, terms):  # move the cut out of a highlighted word
                    if a < cut < b:
                        cut = a if a >= 2 else b
                chunks.append(x[:cut])
                x = x[cut:]
            if x:
                chunks.append(x)
        total = sum(len(c) for c in chunks) or 1
        t = u["start"]
        for c in chunks:
            d = (u["end"] - u["start"]) * len(c) / total
            cues.append({"start": t, "end": t + d, "text": c, "emph": [list(s) for s in spans_of(c, terms)]})
            t += d
    for i, c in enumerate(cues):  # hold until the next cue (no flicker); last one ends with the video
        c["end"] = cues[i + 1]["start"] if i + 1 < len(cues) else min(c["end"] + 0.3, end_all - 0.05)
        c["start"], c["end"] = round(c["start"], 3), round(c["end"], 3)
    return cues


# ---------------- drawing ----------------

_font_cache: dict = {}


def font(style: dict, size: int):
    key = (style["font"], style.get("weight"), size)
    if key in _font_cache:
        return _font_cache[key]
    from PIL import ImageFont
    f = None
    man = FONT_DIR / "manifest.json"
    if man.is_file():
        row = json.loads(man.read_text(encoding="utf-8")).get(style["font"])
        if row and row.get("sha256") and Path(row["path"]).is_file():
            f = ImageFont.truetype(row["path"], size)
            if style.get("weight"):
                try:
                    f.set_variation_by_axes([float(style["weight"])])
                except Exception:
                    pass
    if f is None:  # fonts_download.py not run yet: bold system CJK font
        f = pil_font(size, bold=True)
    _font_cache[key] = f
    return f


def _rgba(hex_color: str, alpha: float = 1.0):
    h = hex_color.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), int(round(255 * alpha)))


def draw_line(text: str, emph, style: dict):
    """Return an RGBA image of one caption line, horizontally centred on a W-wide canvas, plus its ink top."""
    from PIL import Image, ImageDraw, ImageFilter
    hl = style.get("highlight", {})
    size = style["size"]
    stroke = style.get("stroke", {}).get("width", 0)
    outer = style.get("outer_stroke", {}).get("width", 0)
    for _ in range(6):  # shrink until it fits the safe width
        runs, i = [], 0
        for a, b in emph:
            if a > i:
                runs.append((text[i:a], False))
            runs.append((text[a:b], True))
            i = b
        if i < len(text):
            runs.append((text[i:], False))
        fonts = [font(style, round(size * (hl.get("scale", 1.0) if e else 1.0))) for _, e in runs]
        widths = [f.getlength(t) for (t, _), f in zip(runs, fonts)]
        if sum(widths) + 2 * (stroke + outer) <= W - 2 * SIDE:
            break
        size = int(size * 0.92)
    asc = max(f.getmetrics()[0] for f in fonts)
    desc = max(f.getmetrics()[1] for f in fonts)
    sh = style.get("shadow")
    box = style.get("box")
    pad = stroke + outer + (sh["blur"] * 2 + abs(sh["dy"]) if sh else 0) + (box["pad_y"] if box else 0) + 8
    hgt = asc + desc + 2 * pad
    img = Image.new("RGBA", (W, hgt), (0, 0, 0, 0))
    tw = sum(widths)
    x0, base = (W - tw) / 2, pad + asc
    if box:
        bx = Image.new("RGBA", img.size, (0, 0, 0, 0))
        ImageDraw.Draw(bx).rounded_rectangle([x0 - box["pad_x"], pad - box["pad_y"] + asc * 0.08,
                                              x0 + tw + box["pad_x"], base + desc + box["pad_y"] - desc * 0.4],
                                             radius=box["radius"], fill=_rgba(box["color"], box.get("alpha", 1)))
        img = Image.alpha_composite(img, bx)
    # highlight boxes behind emphasised runs
    x = x0
    hb = hl.get("box")
    if hb:
        d = ImageDraw.Draw(img)
        for (t, e), f, w in zip(runs, fonts, widths):
            if e:
                _, ink_top, _, ink_bottom = f.getbbox(t, anchor="ls")  # actual glyph extent around the baseline
                d.rounded_rectangle([x - hb["pad_x"], base + ink_top - hb["pad_y"], x + w + hb["pad_x"],
                                     base + ink_bottom + hb["pad_y"]], radius=hb["radius"], fill=_rgba(hb["color"]))
            x += w
    if sh:
        sl = Image.new("RGBA", img.size, (0, 0, 0, 0))
        d = ImageDraw.Draw(sl)
        x = x0
        for (t, e), f, w in zip(runs, fonts, widths):
            d.text((x + sh["dx"], base + sh["dy"]), t, font=f, anchor="ls", fill=_rgba(sh["color"], sh["alpha"]),
                   stroke_width=stroke + outer, stroke_fill=_rgba(sh["color"], sh["alpha"]))
            x += w
        img = Image.alpha_composite(img, sl.filter(ImageFilter.GaussianBlur(sh["blur"])) if sh["blur"] else sl)
    d = ImageDraw.Draw(img)
    xs = [x0 + sum(widths[:k]) for k in range(len(runs))]
    # layer by layer over the whole line, so a run's outline never covers its neighbour's fill
    boxed = lambda e: e and bool(hb)  # text on a highlight box gets no outline (dark text on yellow)
    if outer:
        oc = _rgba(style["outer_stroke"]["color"])
        for (t, e), f, x in zip(runs, fonts, xs):
            if not boxed(e):
                d.text((x, base), t, font=f, anchor="ls", fill=oc, stroke_width=stroke + outer, stroke_fill=oc)
    if stroke:
        sc = _rgba(style["stroke"]["color"])
        for (t, e), f, x in zip(runs, fonts, xs):
            if not boxed(e):
                d.text((x, base), t, font=f, anchor="ls", fill=sc, stroke_width=stroke, stroke_fill=sc)
    for (t, e), f, x in zip(runs, fonts, xs):
        d.text((x, base), t, font=f, anchor="ls", fill=_rgba(hl.get("fill", style["fill"]) if e else style["fill"]))
    return img, pad


def _frame(line, style: dict, k: int, n: int):
    """Intro animation frame k of n (k == n is the settled look)."""
    from PIL import Image
    p = min(1.0, k / max(1, n))
    ease = 1 - (1 - p) ** 3
    anim = style.get("anim", "none")
    out = line
    if anim == "pop" and p < 1:
        s = 1.28 - 0.28 * ease
        w, h = line.size
        big = line.resize((max(1, int(w * s)), max(1, int(h * s))))
        out = Image.new("RGBA", line.size, (0, 0, 0, 0))
        out.alpha_composite(big.crop(((big.width - w) // 2, (big.height - h) // 2,
                                      (big.width - w) // 2 + w, (big.height - h) // 2 + h)))
    elif anim == "rise" and p < 1:
        out = Image.new("RGBA", line.size, (0, 0, 0, 0))
        out.alpha_composite(line, (0, int(30 * (1 - ease))))
    alpha = 1.0 if anim == "none" else (0.35 + 0.65 * ease if anim == "pop" else ease)
    if alpha < 1:
        a = out.getchannel("A").point(lambda v: int(v * alpha))
        out = out.copy()
        out.putalpha(a)
    return out


def render_layer(cues, style: dict, total_s: float, fps: int, out_dir: Path):
    """PNG frames + ffconcat list for the caption overlay. Returns (ffconcat_path, band_y)."""
    from PIL import Image
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("*.png"):
        old.unlink()
    lines = [draw_line(c["text"], c["emph"], style) for c in cues]
    band_h = max([img.height for img, _ in lines] + [2])
    pads = [p for _, p in lines]
    top = int(style["y"] * H) - max(pads, default=0)
    blank = out_dir / "blank.png"
    Image.new("RGBA", (W, band_h), (0, 0, 0, 0)).save(blank)
    n_anim = max(1, round(style.get("anim_s", 0.14) * fps)) if style.get("anim", "none") != "none" else 0
    seq, cursor = [], 0  # (path, frames)
    total_f = round(total_s * fps)
    for k, (c, (line, pad)) in enumerate(zip(cues, lines)):
        f0, f1 = round(c["start"] * fps), min(total_f, round(c["end"] * fps))
        if f0 > cursor:
            seq.append((blank, f0 - cursor))
        canvas = Image.new("RGBA", (W, band_h), (0, 0, 0, 0))
        y_off = max(pads) - pad
        frames = []
        for j in range(min(n_anim, max(0, f1 - f0 - 1))):
            fr = canvas.copy()
            fr.alpha_composite(_frame(line, style, j + 1, n_anim + 1), (0, y_off))
            p = out_dir / f"c{k:03d}_{j}.png"
            fr.save(p)
            frames.append((p, 1))
        hold = canvas.copy()
        hold.alpha_composite(line, (0, y_off))
        p = out_dir / f"c{k:03d}_h.png"
        hold.save(p)
        frames.append((p, max(1, f1 - f0 - len(frames))))
        seq += frames
        cursor = f0 + sum(n for _, n in frames)
    if cursor < total_f:
        seq.append((blank, total_f - cursor))
    lst = out_dir / "captions.ffconcat"
    body = ["ffconcat version 1.0"]
    for p, n in seq:
        body += [f"file '{p.as_posix()}'", f"duration {n / fps:.6f}"]
    body.append(f"file '{seq[-1][0].as_posix()}'")  # concat demuxer needs the last file repeated
    lst.write_text("\n".join(body) + "\n", encoding="utf-8")
    return lst, max(0, top)


def preview(names, text: str, out: Path):
    """Contact sheet of styles over a mid-grey/colour background."""
    from PIL import Image, ImageDraw
    rows = []
    for n in names:
        st = STYLES[n]
        terms = emphasis_terms(text, [])
        line, pad = draw_line(text, spans_of(text, terms), st)
        bg = Image.new("RGBA", (W, line.height + 60), (70, 110, 90, 255))
        ImageDraw.Draw(bg).rectangle([0, 0, W // 2, bg.height], fill=(200, 190, 170, 255))
        bg.alpha_composite(line, (0, 40))
        ImageDraw.Draw(bg).text((12, 6), n, fill=(255, 255, 255, 255), font=pil_font(26))
        rows.append(bg)
    sheet = Image.new("RGBA", (W, sum(r.height for r in rows)))
    y = 0
    for r in rows:
        sheet.alpha_composite(r, (0, y))
        y += r.height
    sheet.convert("RGB").save(out)
    print(out)


if __name__ == "__main__":
    if len(sys.argv) >= 4 and sys.argv[1] == "preview":
        names = list(STYLES) if sys.argv[2] == "all" else [sys.argv[2]]
        preview(names, sys.argv[3], Path(sys.argv[4] if len(sys.argv) > 4 else "caption-styles.png"))
    else:
        print(__doc__)
