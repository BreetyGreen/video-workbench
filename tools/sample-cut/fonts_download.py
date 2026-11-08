"""Download the caption fonts (all SIL OFL 1.1: free for commercial use and for embedding in videos).

usage: python fonts_download.py        (idempotent; existing files are kept)
target: VIDEO_WORKBENCH_FONT_DIR, default <data_home>/fonts, with manifest.json (source, license, sha256)
Every font ships next to its own license text. Jianying (剪映) bundles the same open fonts under the names in
`jianying` so drafts and the rendered mp4 use the same typeface.
"""
import hashlib
import io
import json
import os
import time
import urllib.request
import zipfile
from pathlib import Path

from vw_common import data_home

DIR = Path(os.environ.get("VIDEO_WORKBENCH_FONT_DIR") or data_home() / "fonts")
GF = "https://raw.githubusercontent.com/google/fonts/main/ofl/"
FONTS = {
    "noto-sans-sc": {"name": "Noto Sans SC / 思源黑体 (variable 100-900)", "jianying": "SourceHanSansCN_Bold",
                     "file": "NotoSansSC-VF.ttf", "url": GF + "notosanssc/NotoSansSC%5Bwght%5D.ttf",
                     "license_url": GF + "notosanssc/OFL.txt"},
    "smiley-sans": {"name": "Smiley Sans / 得意黑", "jianying": "得意黑", "file": "SmileySans-Oblique.ttf",
                    "zip": "https://github.com/atelier-anchor/smiley-sans/releases/download/v2.0.1/smiley-sans-v2.0.1.zip",
                    "zip_member": "SmileySans-Oblique.ttf",
                    "license_url": "https://raw.githubusercontent.com/atelier-anchor/smiley-sans/main/LICENSE"},
    "zcool-kuaile": {"name": "ZCOOL KuaiLe / 站酷快乐体", "jianying": "快乐体", "file": "ZCOOLKuaiLe-Regular.ttf",
                     "url": GF + "zcoolkuaile/ZCOOLKuaiLe-Regular.ttf", "license_url": GF + "zcoolkuaile/OFL.txt"},
    "zcool-huangyou": {"name": "ZCOOL QingKe HuangYou / 站酷庆科黄油体", "jianying": "黄油体",
                       "file": "ZCOOLQingKeHuangYou-Regular.ttf",
                       "url": GF + "zcoolqingkehuangyou/ZCOOLQingKeHuangYou-Regular.ttf",
                       "license_url": GF + "zcoolqingkehuangyou/OFL.txt"},
    "zcool-xiaowei": {"name": "ZCOOL XiaoWei / 站酷小薇体", "jianying": "小薇体", "file": "ZCOOLXiaoWei-Regular.ttf",
                      "url": GF + "zcoolxiaowei/ZCOOLXiaoWei-Regular.ttf", "license_url": GF + "zcoolxiaowei/OFL.txt"},
    "lxgw-wenkai": {"name": "LXGW WenKai / 霞鹜文楷 Medium", "jianying": "小薇体", "file": "LXGWWenKai-Medium.ttf",
                    "url": "https://github.com/lxgw/LxgwWenKai/releases/download/v1.530/LXGWWenKai-Medium.ttf",
                    "license_url": "https://raw.githubusercontent.com/lxgw/LxgwWenKai/main/OFL.txt"},
}


def fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "video-workbench-fonts/1.0"})
    for attempt in range(3):
        try:
            return urllib.request.urlopen(req, timeout=300).read()
        except Exception:
            if attempt == 2:
                raise
            time.sleep(3)


def main():
    DIR.mkdir(parents=True, exist_ok=True)
    manifest = {}
    for key, f in FONTS.items():
        d = DIR / key
        d.mkdir(exist_ok=True)
        dst = d / f["file"]
        status = "exists"
        try:
            if not dst.exists() or dst.stat().st_size < 100_000:
                if "zip" in f:
                    z = zipfile.ZipFile(io.BytesIO(fetch(f["zip"])))
                    member = next(n for n in z.namelist() if n.endswith(f["zip_member"]))
                    data = z.read(member)
                else:
                    data = fetch(f["url"])
                assert data[:4] in (b"\x00\x01\x00\x00", b"OTTO", b"true"), "not a font file"
                dst.write_bytes(data)
                status = "downloaded"
            lic = d / "LICENSE.txt"
            if not lic.exists():
                lic.write_bytes(fetch(f["license_url"]))
            assert b"Open Font License" in lic.read_bytes() or b"OFL" in lic.read_bytes(), "unexpected license"
        except Exception as e:  # keep going; the renderer falls back to system fonts for a missing face
            status = f"failed: {e}"
        manifest[key] = {**{k: v for k, v in f.items() if k != "zip_member"}, "path": str(dst), "status": status,
                         "license": "SIL Open Font License 1.1",
                         "sha256": hashlib.sha256(dst.read_bytes()).hexdigest() if dst.exists() else None}
        print(f"{status:12s} {key}")
    (DIR / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    ok = sum(1 for m in manifest.values() if m["sha256"])
    print(f"{ok}/{len(manifest)} fonts ready in {DIR}")


if __name__ == "__main__":
    main()
