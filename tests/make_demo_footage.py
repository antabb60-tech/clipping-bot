"""Generate stand-in footage so the example plan can render without real recordings.

Usage: python tests/make_demo_footage.py footage
"""

import subprocess
import sys
from pathlib import Path

out = Path(sys.argv[1] if len(sys.argv) > 1 else "footage")
out.mkdir(parents=True, exist_ok=True)
for i in (1, 2, 3):
    dest = out / f"witness_run{i}.mp4"
    if dest.exists():
        continue
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
         "-f", "lavfi", "-i", "testsrc2=s=1280x720:r=30:d=140",
         "-f", "lavfi", "-i", f"sine=f={220 * i}:d=140",
         "-c:v", "libx264", "-preset", "ultrafast", "-crf", "30", "-c:a", "aac", str(dest)],
        check=True,
    )
    print(f"made {dest}")
