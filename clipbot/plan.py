"""Edit-plan loading and validation.

An edit plan is a YAML file describing one video idea: which footage
segments to use, the voiceover line for each, on-screen text, and which
segments go into each platform's cut. See docs/PLAN_FORMAT.md.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


class PlanError(ValueError):
    """Raised when a plan file is invalid. The message is meant for humans."""


# Platform duration targets in seconds: (min, max, hard_max).
# min/max are what we aim for; hard_max is what the platform allows.
PLATFORM_RULES: dict[str, dict[str, Any]] = {
    # TikTok Creator Rewards only pays on videos longer than 1 minute.
    "tiktok": {"min": 61.0, "max": 180.0, "label": "TikTok (over 1 minute for Creator Rewards)"},
    "shorts": {"min": 20.0, "max": 40.0, "hard_max": 180.0, "label": "YouTube Shorts (20-40s)"},
    "x": {"min": 20.0, "max": 40.0, "hard_max": 140.0, "label": "X (20-40s)"},
}

CROP_MODES = ("blur", "crop")

_TC_RE = re.compile(r"^(?:(\d+):)?(?:(\d+):)?(\d+(?:\.\d+)?)$")


def parse_timecode(value: Any) -> float:
    """Parse '1:23.5', '01:02:03', '83.5' or a number into seconds."""
    if isinstance(value, bool):
        raise PlanError(f"bad timecode: {value!r}")
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str):
        raise PlanError(f"bad timecode: {value!r}")
    s = value.strip()
    m = _TC_RE.match(s)
    if not m:
        raise PlanError(f"bad timecode {value!r}; use SS, MM:SS or HH:MM:SS (decimals ok)")
    a, b, c = m.groups()
    parts = [p for p in (a, b) if p is not None]
    secs = float(c)
    if len(parts) == 2:
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + secs
    if len(parts) == 1:
        return int(parts[0]) * 60 + secs
    return secs


def fmt_time(seconds: float) -> str:
    m, s = divmod(max(0.0, seconds), 60)
    return f"{int(m)}:{s:05.2f}"


@dataclass
class Overlay:
    text: str
    start: float = 0.0  # relative to segment start
    end: float | None = None  # relative to segment start; None = segment end


@dataclass
class Segment:
    id: str
    file: Path
    start: float
    end: float
    vo: str = ""
    text: list[Overlay] = field(default_factory=list)
    crop: str = "blur"
    focus: float | list[tuple[float, float]] = 0.5
    zoom: float = 1.0
    game_audio: float = 0.30  # game volume while the voiceover is talking
    game_audio_gap: float = 0.85  # game volume when nobody is talking
    vo_delay: float = 0.15
    extend: bool = True  # allow extending the clip if the VO runs long
    violent: bool = False
    speed: float = 1.0

    @property
    def clip_len(self) -> float:
        return (self.end - self.start) / self.speed


@dataclass
class PlatformCut:
    name: str
    segments: list[str]
    hook: str | None = None
    hook_duration: float = 2.0
    caption: str = ""
    hashtags: list[str] = field(default_factory=list)
    title: str = ""


@dataclass
class Plan:
    path: Path
    title: str
    slug: str
    footage_dir: Path
    voice: str
    rate: str
    pitch: str
    tts: str
    hook: str
    hook_duration: float
    captions: dict[str, Any]
    segments: dict[str, Segment]
    platforms: dict[str, PlatformCut]
    loudness: float = -14.0
    music: Path | None = None
    music_volume: float = 0.12

    def cut_segments(self, platform: str) -> list[Segment]:
        return [self.segments[s] for s in self.platforms[platform].segments]


def _slugify(text: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return s[:60] or "video"


def _signed(v: Any, unit: str, name: str) -> str:
    """Normalise '8%' / 8 / '+8%' to the '+8%' form edge-tts requires."""
    s = str(v).strip().replace(" ", "")
    if s.endswith(unit):
        s = s[: -len(unit)]
    try:
        n = float(s)
    except ValueError:
        raise PlanError(f"{name} must look like +10{unit} or -5{unit}, got {v!r}") from None
    return f"{'+' if n >= 0 else '-'}{abs(int(round(n)))}{unit}"


def _volume(v: Any, name: str) -> float:
    try:
        f = float(v)
    except (TypeError, ValueError):
        raise PlanError(f"{name} must be a number like 0.3") from None
    if not 0.0 <= f <= 2.0:
        raise PlanError(f"{name} must be between 0 (silent) and 2 (double)")
    return f


def _as_list(v: Any) -> list:
    if v is None:
        return []
    return v if isinstance(v, list) else [v]


def _parse_focus(v: Any, where: str) -> float | list[tuple[float, float]]:
    if v is None:
        return 0.5
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        f = float(v)
        if not 0.0 <= f <= 1.0:
            raise PlanError(f"{where}: focus must be between 0 (left) and 1 (right)")
        return f
    if isinstance(v, list):
        keys: list[tuple[float, float]] = []
        for item in v:
            if not (isinstance(item, (list, tuple)) and len(item) == 2):
                raise PlanError(f"{where}: focus keyframes look like [[0, 0.5], [3, 0.7]]")
            t, x = parse_timecode(item[0]), float(item[1])
            if not 0.0 <= x <= 1.0:
                raise PlanError(f"{where}: focus values must be between 0 and 1")
            keys.append((t, x))
        if not keys:
            return 0.5
        keys.sort()
        return keys
    raise PlanError(f"{where}: focus must be a number or a list of [time, x] pairs")


def _parse_overlays(v: Any, where: str) -> list[Overlay]:
    out: list[Overlay] = []
    for item in _as_list(v):
        if isinstance(item, str):
            out.append(Overlay(text=item))
        elif isinstance(item, dict) and "say" in item:
            end = item.get("end")
            out.append(
                Overlay(
                    text=str(item["say"]),
                    start=parse_timecode(item.get("start", 0)),
                    end=None if end is None else parse_timecode(end),
                )
            )
        else:
            raise PlanError(f"{where}: text must be a string or {{say: ..., start: ..., end: ...}}")
    return out


def load_plan(path: str | Path) -> Plan:
    path = Path(path).resolve()
    if not path.exists():
        raise PlanError(f"plan not found: {path}")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise PlanError(f"{path.name} is not valid YAML: {e}") from e
    if not isinstance(data, dict):
        raise PlanError(f"{path.name}: top level must be a mapping")

    base = path.parent
    title = str(data.get("title") or path.stem)
    footage_dir = (base / str(data.get("footage_dir", "."))).resolve()
    defaults = data.get("defaults") or {}
    if not isinstance(defaults, dict):
        raise PlanError("defaults must be a mapping")

    raw_segments = data.get("segments")
    if not isinstance(raw_segments, list) or not raw_segments:
        raise PlanError("plan needs a non-empty 'segments' list")

    segments: dict[str, Segment] = {}
    for i, raw in enumerate(raw_segments):
        where = f"segment #{i + 1}"
        if not isinstance(raw, dict):
            raise PlanError(f"{where} must be a mapping")
        merged = {**defaults, **raw}
        sid = str(merged.get("id") or f"s{i + 1}")
        where = f"segment '{sid}'"
        if sid in segments:
            raise PlanError(f"duplicate segment id '{sid}'")
        if "file" not in merged:
            raise PlanError(f"{where}: missing 'file'")
        file = Path(str(merged["file"]))
        if not file.is_absolute():
            file = footage_dir / file
        if "start" not in merged or "end" not in merged:
            raise PlanError(f"{where}: needs 'start' and 'end'")
        start, end = parse_timecode(merged["start"]), parse_timecode(merged["end"])
        if end <= start:
            raise PlanError(f"{where}: end ({fmt_time(end)}) must be after start ({fmt_time(start)})")
        crop = str(merged.get("crop", "blur"))
        if crop not in CROP_MODES:
            raise PlanError(f"{where}: crop must be one of {', '.join(CROP_MODES)}")
        zoom = float(merged.get("zoom", 1.0))
        if not 1.0 <= zoom <= 3.0:
            raise PlanError(f"{where}: zoom must be between 1.0 and 3.0")
        speed = float(merged.get("speed", 1.0))
        if not 0.5 <= speed <= 2.0:
            raise PlanError(f"{where}: speed must be between 0.5 and 2.0")
        ga = merged.get("game_audio")
        segments[sid] = Segment(
            id=sid,
            file=file,
            start=start,
            end=end,
            vo=str(merged.get("vo") or "").strip(),
            text=_parse_overlays(merged.get("text"), where),
            crop=crop,
            focus=_parse_focus(merged.get("focus"), where),
            zoom=zoom,
            game_audio=0.30 if ga is None else _volume(ga, f"{where}: game_audio"),
            game_audio_gap=_volume(merged.get("game_audio_gap", 0.85), f"{where}: game_audio_gap"),
            vo_delay=float(merged.get("vo_delay", 0.15)),
            extend=bool(merged.get("extend", True)),
            violent=bool(merged.get("violent", False)),
            speed=speed,
        )

    hook = str(data.get("hook") or "").strip()
    hook_duration = float(data.get("hook_duration", 2.0))

    raw_platforms = data.get("platforms")
    if raw_platforms is None:
        raw_platforms = {name: {} for name in PLATFORM_RULES}
    if not isinstance(raw_platforms, dict) or not raw_platforms:
        raise PlanError("'platforms' must map platform names (tiktok, shorts, x) to cuts")

    platforms: dict[str, PlatformCut] = {}
    for name, raw in raw_platforms.items():
        name = str(name).lower()
        if name not in PLATFORM_RULES:
            raise PlanError(f"unknown platform '{name}'; use {', '.join(PLATFORM_RULES)}")
        raw = raw or {}
        if isinstance(raw, list):
            raw = {"segments": raw}
        if not isinstance(raw, dict):
            raise PlanError(f"platform '{name}' must be a list of segment ids or a mapping")
        seg_ids = [str(s) for s in _as_list(raw.get("segments"))] or list(segments)
        for s in seg_ids:
            if s not in segments:
                raise PlanError(f"platform '{name}' uses unknown segment '{s}'")
        platforms[name] = PlatformCut(
            name=name,
            segments=seg_ids,
            hook=(str(raw["hook"]).strip() if raw.get("hook") else None),
            hook_duration=float(raw.get("hook_duration", hook_duration)),
            caption=str(raw.get("caption") or "").strip(),
            hashtags=[str(h).lstrip("#") for h in _as_list(raw.get("hashtags"))],
            title=str(raw.get("title") or "").strip(),
        )

    captions = {
        "font": "Arial Black",
        "size": 84,
        "color": "#FFFFFF",
        "highlight": "#FFE100",
        "outline": 7,
        "max_words": 3,
        "max_chars": 14,
        "y": 1180,
        "uppercase": True,
        "enabled": True,
    }
    user_caps = data.get("captions", {})
    if user_caps is None:
        user_caps = {}
    if user_caps is False:
        captions["enabled"] = False
    elif isinstance(user_caps, dict):
        captions.update(user_caps)
    else:
        raise PlanError("captions must be a mapping or false")

    music = data.get("music")
    music_path = None
    if music:
        music_path = Path(str(music))
        if not music_path.is_absolute():
            music_path = (base / music_path).resolve()

    return Plan(
        path=path,
        title=title,
        slug=_slugify(str(data.get("slug") or title)),
        footage_dir=footage_dir,
        voice=str(data.get("voice", "en-US-AndrewNeural")),
        rate=_signed(data.get("rate", "+8%"), "%", "rate"),
        pitch=_signed(data.get("pitch", "+0Hz"), "Hz", "pitch"),
        tts=str(data.get("tts", "edge")),
        hook=hook,
        hook_duration=hook_duration,
        captions=captions,
        segments=segments,
        platforms=platforms,
        loudness=float(data.get("loudness", -14.0)),
        music=music_path,
        music_volume=float(data.get("music_volume", 0.12)),
    )


def check_files(plan: Plan) -> list[str]:
    """Return a list of problems with footage files referenced by the plan."""
    problems = []
    seen = set()
    for seg in plan.segments.values():
        if seg.file in seen:
            continue
        seen.add(seg.file)
        if not seg.file.exists():
            problems.append(f"missing footage: {seg.file}")
    if plan.music and not plan.music.exists():
        problems.append(f"missing music: {plan.music}")
    return problems
