"""Transcribe voice files with DashScope paraformer-realtime-v2 to check they read the script correctly.

usage: python asr_check.py <audio> [<audio> ...]   (needs a DashScope key)
"""
import subprocess
import sys
import tempfile
from pathlib import Path

from vw_common import init_dashscope

init_dashscope()
from dashscope.audio.asr import Recognition  # noqa: E402

for p in sys.argv[1:]:
    tmp = Path(tempfile.gettempdir()) / (Path(p).stem + "_16k.wav")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", p, "-ac", "1", "-ar", "16000", str(tmp)], check=True)
    r = Recognition(model="paraformer-realtime-v2", format="wav", sample_rate=16000, callback=None).call(str(tmp))
    sents = r.get_sentence() or []
    print(Path(p).name, "->", "".join(s.get("text", "") for s in sents))
