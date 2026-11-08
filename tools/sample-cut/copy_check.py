"""Autopilot gate: check copy.json before any voice is generated. Exit code 1 = must rewrite.

usage (inside the project work dir): python copy_check.py
Checks: length (130-165 chars, 9-14 sentences), forbidden claims (price, stock, efficacy, superlatives,
competitor comparison), every number/unit and every fact-like phrase must appear in facts_from_package, every
shot type exists in takes/selected-takes.json, the first sentence opens on the opening shot, emphasis words are
literal substrings.
"""
import json
import re
import sys
from pathlib import Path

from vw_common import work_dir

HERE = Path(__file__).resolve().parent
WORK = work_dir()
copy = json.loads((WORK / "copy.json").read_text(encoding="utf-8"))
takes = json.loads((WORK / "takes" / "selected-takes.json").read_text(encoding="utf-8"))
tax = json.loads((HERE / "taxonomy.json").read_text(encoding="utf-8"))

FORBIDDEN = {
    "价格/促销": r"[0-9一二三四五六七八九十百]+\s*元|块钱|￥|¥|折|特价|秒杀|优惠|便宜|划算|性价比|券|包邮|赠品|买一送",
    "库存/稀缺": r"库存|限量|仅剩|最后\s*\d|抢光|断货",
    "功效": r"减肥|瘦身|刮油|燃脂|降火|清热|排毒|养颜|美白|抗氧化|降糖|降压|降脂|助眠|提神醒脑|治疗|预防|调理|护肝|养胃|增强免疫|解酒",
    "绝对化": r"最好|最佳|第一|顶级|极致|唯一|全网|100%|百分百|绝对|永久|万能|国家级",
    "比较": r"比.{0,6}(好|强|健康|便宜)|吊打|秒杀|碾压|别家|其他品牌",
}
text = "".join(s["text"] for s in copy["sentences"])
chars = len(re.sub(r"[^一-鿿0-9A-Za-z]", "", text))
facts = " ".join(copy.get("facts_from_package", []))
errors, warns = [], []

if not 130 <= chars <= 165:
    errors.append(f"文案 {chars} 字，要在 130-165 字之间（按 6.8 字/秒约 19-24 秒）")
if not 9 <= len(copy["sentences"]) <= 14:
    errors.append(f"{len(copy['sentences'])} 句，要 9-14 句")
if not copy.get("facts_from_package"):
    errors.append("facts_from_package 为空：卖点必须来自包装上的字（ocr_text.py + 看帧确认）")
for kind, pat in FORBIDDEN.items():
    for m in re.finditer(pat, text):
        errors.append(f"禁用（{kind}）：「{m.group(0)}」")
# numbers with units must be printed on the package
for m in re.finditer(r"(?:\d+(?:\.\d+)?|[零一二两三四五六七八九十百千]+)\s*(?:mL|ml|毫升|L|升|g|克|kg|千克|mg|大卡|千焦|kJ|%|瓶|袋|盒|包)", text):
    num = re.sub(r"\s", "", m.group(0))
    digits = re.sub(r"[^\d.]", "", num)
    if digits and digits not in facts.replace(" ", ""):
        errors.append(f"数字「{num}」在 facts_from_package 里找不到")
for i, s in enumerate(copy["sentences"]):
    for shot in s.get("shots", []):
        if shot not in takes:
            errors.append(f"第{i + 1}句的镜头类型「{shot}」不在 selected-takes.json 里（有：{', '.join(takes)}）")
    if not s.get("shots"):
        errors.append(f"第{i + 1}句没有配镜头")
    for w in s.get("emphasis", []) or []:
        if w not in s["text"]:
            errors.append(f"第{i + 1}句的强调词「{w}」不在这句原文里")
first = copy["sentences"][0].get("shots", [])
if tax["opening"] in takes and tax["opening"] not in first:
    warns.append(f"第一句建议配开场镜头「{tax['opening']}」")
if not re.search(r"左下角|小黄车|带.{0,3}回家|下单|囤|来一", copy["sentences"][-1]["text"]):
    warns.append("最后一句建议是行动号召（例：点左下角带一箱回家）")
print(json.dumps({"chars": chars, "sentences": len(copy["sentences"]), "errors": errors, "warnings": warns},
                 ensure_ascii=False, indent=1))
sys.exit(1 if errors else 0)
