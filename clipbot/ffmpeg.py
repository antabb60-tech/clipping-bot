"""Thin helpers around the ffmpeg / ffprobe command-line tools."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path


class FFmpegError(RuntimeError):
    pass


def require_tools() -> None:
    missing = [t for t in ("ffmpeg", "ffprobe") if shutil.which(t) is None]
    if missing:
        raise FFmpegError(
            f"{' and '.join(missing)} not found on PATH. On Windows run: winget install Gyan.FFmpeg "
            "and then open a NEW terminal window. See docs/WINDOWS_SETUP.md."
        )


def run(args: list[str], cwd: Path | None = None, verbose: bool = False, loglevel: str | None = None) -> str:
    level = loglevel or ("info" if verbose else "error")
    cmd = ["ffmpeg", "-hide_banner", "-y", "-nostdin", "-loglevel", level, *args]
    if verbose:
        print("  $ " + " ".join(_q(a) for a in cmd))
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        tail = "\n".join(proc.stderr.strip().splitlines()[-25:])
        raise FFmpegError(f"ffmpeg failed (exit {proc.returncode}):\n{tail}")
    return proc.stderr


def probe(path: Path) -> dict:
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if proc.returncode != 0:
        raise FFmpegError(f"ffprobe could not read {path}: {proc.stderr.strip()}")
    return json.loads(proc.stdout)


class MediaInfo:
    def __init__(self, path: Path):
        self.path = path
        data = probe(path)
        self.duration = float(data.get("format", {}).get("duration") or 0.0)
        self.video = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), None)
        self.audio = next((s for s in data.get("streams", []) if s.get("codec_type") == "audio"), None)

    @property
    def width(self) -> int:
        return int(self.video["width"]) if self.video else 0

    @property
    def height(self) -> int:
        return int(self.video["height"]) if self.video else 0

    @property
    def fps(self) -> float:
        if not self.video:
            return 0.0
        num, _, den = str(self.video.get("avg_frame_rate", "0/1")).partition("/")
        try:
            return float(num) / float(den or 1)
        except (ValueError, ZeroDivisionError):
            return 0.0

    @property
    def is_hdr(self) -> bool:
        if not self.video:
            return False
        return self.video.get("color_transfer") in ("smpte2084", "arib-std-b67")


def media_duration(path: Path) -> float:
    return MediaInfo(path).duration


_filters_cache: set[str] | None = None


def has_filter(name: str) -> bool:
    global _filters_cache
    if _filters_cache is None:
        proc = subprocess.run(["ffmpeg", "-hide_banner", "-filters"], capture_output=True, text=True)
        names = set()
        for line in proc.stdout.splitlines():
            parts = line.split()
            if len(parts) >= 2 and len(parts[0]) == 3:
                names.add(parts[1])
        _filters_cache = names
    return name in _filters_cache


def _q(a: str) -> str:
    return f'"{a}"' if (" " in a or ";" in a) else a
