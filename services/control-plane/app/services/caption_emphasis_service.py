"""Pick the words a caption should shout.

Commercial short-video captions ("花字") colour one or two punch words per line: a
number with its unit (十瓶, 两百四十五克, 零脂肪), the product name, or a sensory /
benefit word (冰爽, 清润, 无负担). This service derives those terms deterministically
from the narration text, so the renderer and the Jianying draft highlight the same
words without another model call. Product facts still come only from the narration;
this never adds words, it only chooses which existing ones to emphasise.
"""
from __future__ import annotations

import re

_NUMERAL = r"(?:[零〇一二两三四五六七八九十百千万]{1,8}|\d+(?:\.\d+)?)"
_UNIT = (r"(?:个月|小时|分钟|毫升|大卡|ml|g|kg|瓶|克|升|斤|月|天|年|倍|种|颗|粒|盒|袋|包|次|折|元|卡|"
         r"脂肪|糖|添加|负担|香精|色素|防腐剂)")
_NUMBER_TERM = re.compile(rf"{_NUMERAL}{_UNIT}")

# Generic sales punch words (sensory, benefit, urgency). Two characters or more so a
# single common character never lights up on its own.
PUNCH_WORDS: tuple[str, ...] = (
    "透心凉", "冰爽", "清爽", "清润", "清甜", "清香", "原香", "香浓", "醇厚", "顺滑", "丝滑", "绵密", "绵细", "密腻",
    "细腻", "沙沙", "饱满", "满满", "真材实料", "现熬", "熬制", "新鲜", "解腻", "不腻", "轻松", "无负担", "零负担",
    "更畅快", "畅快", "好喝", "回购", "必入", "上头", "绝了", "犯困", "口干", "甜腻", "长胖", "今天就试试", "试试",
    "来一杯", "冲一杯", "随手一瓶", "一口", "冷藏", "常温", "摇匀", "沉淀",
)


def product_terms_from_title(title: str) -> list[str]:
    """Split a task title into product-name candidates (whole title first, then parts)."""
    compact = "".join(title.split())
    if not compact:
        return []
    parts = [part for part in re.split(r"[｜|/\-—–·,，。:：()（）\[\]【】]+", compact) if len(part) >= 2]
    terms = [compact] if len(compact) >= 2 else []
    terms.extend(part for part in parts if part != compact)
    return list(dict.fromkeys(terms))


def emphasis_terms(text: str, *, product_terms: list[str] | tuple[str, ...] = (), max_terms: int = 2) -> list[str]:
    """Return up to ``max_terms`` substrings of ``text`` worth highlighting.

    Priority: number+unit facts, then the product name, then punch words. Terms never
    overlap each other and every term is a literal substring of ``text``.
    """
    compact = "".join(text.split())
    if not compact:
        return []
    candidates: list[tuple[int, int, str, bool]] = []
    for match in _NUMBER_TERM.finditer(compact):
        candidates.append((match.start(), match.end(), match.group(0), False))
    for term in sorted({item for item in product_terms if item}, key=len, reverse=True):
        start = compact.find(term)
        if start >= 0:
            candidates.append((start, start + len(term), term, False))
    for word in sorted(PUNCH_WORDS, key=len, reverse=True):
        start = compact.find(word)
        if start >= 0:
            candidates.append((start, start + len(word), word, True))

    chosen: list[tuple[int, int, str]] = []
    punch_used = False
    for start, end, term, is_punch in candidates:
        if is_punch and punch_used:
            continue  # one sensory word per line keeps the accent readable
        if any(not (end <= s or start >= e) for s, e, _ in chosen):
            continue
        if any(term in kept or kept in term for _, _, kept in chosen):
            continue
        chosen.append((start, end, term))
        punch_used = punch_used or is_punch
        if len(chosen) >= max_terms:
            break
    chosen.sort()
    return [term for _, _, term in chosen]
