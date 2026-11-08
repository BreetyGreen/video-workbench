"""Write spec.json for an autopilot project from the sample standard + taxonomy.json.

usage (inside the project work dir): python make_spec.py "<cover title>" [caption style|auto]
Uses the shot types present in takes/selected-takes.json; keeps every measured target of examples/spec.json.
"""
import json
import sys
from pathlib import Path

from vw_common import work_dir

HERE = Path(__file__).resolve().parent
WORK = work_dir()
title = sys.argv[1] if len(sys.argv) > 1 else ""
style = sys.argv[2] if len(sys.argv) > 2 else "auto"
spec = json.loads((HERE / "examples" / "spec.json").read_text(encoding="utf-8"))
tax = json.loads((HERE / "taxonomy.json").read_text(encoding="utf-8"))["types"]
takes = json.loads((WORK / "takes" / "selected-takes.json").read_text(encoding="utf-8"))
unknown = [k for k in takes if k not in tax]
if unknown:
    raise SystemExit(f"selected-takes.json uses unknown shot types {unknown}; use only: {', '.join(tax)}")
present = [k for k in tax if k in takes]
flag = lambda f: [k for k in present if tax[k].get(f)]
e = spec["edit"]
e.update(push_strong_folders=flag("push_strong"), no_push_folders=flag("no_push"), single_shot_folders=flag("single"),
         long_ok_folders=flag("long_ok"),
         min_zoom_by_folder={k: tax[k]["min_zoom"] for k in present if tax[k].get("min_zoom")})
spec["audio"]["sfx_folders"] = flag("sfx")
spec["subtitle"]["style"] = style
spec["cover"]["title"] = title
spec["cover"]["font"] = "Noto Sans SC Black (fonts_download.py)"
spec["source"] = "样片标准（examples/spec.json）+ taxonomy.json 自动映射"
(WORK / "spec.json").write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps({"shot_types": present, "push_strong": e["push_strong_folders"], "sfx": spec["audio"]["sfx_folders"],
                  "caption_style": style}, ensure_ascii=False))
