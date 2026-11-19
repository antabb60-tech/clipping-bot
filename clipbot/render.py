"""Render one platform cut of a plan into a finished vertical video."""

from __future__ import annotations

import hashlib
import json
import math
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from clipbot import ffmpeg
from clipbot.captions import TimedText, build_ass
from clipbot.plan import PLATFORM_RULES, Plan, Segment, fmt_time
from clipbot.tts import Speech, Word, estimate_seconds, synthesize

W, H, FPS = 1080, 1920, 30
TAIL_PAD = 0.3  # seconds of footage kept after a VO line ends
PART_VERSION = 2  # bump when segment rendering changes, to invalidate cached parts
REPO_FONTS = Path(__file__).resolve().parent.parent / "fonts"


@dataclass
class Options:
    out_dir: Path
    tts: str | None = None  # override the plan's engine
    preview: bool = False
    verbose: bool = False
    align: str = "auto"
    keep_work: bool = False


@dataclass
class TimelineItem:
    seg: Segment
    offset: float  # where this segment starts in the final video
    duration: float  # final duration of this segment
    src_len: float  # seconds of source footage used
    freeze: float  # seconds of frozen last frame added (VO ran past the footage)
    speech: Speech | None


@dataclass
class Timeline:
    platform: str
    items: list[TimelineItem]
    warnings: list[str] = field(default_factory=list)

    @property
    def total(self) -> float:
        return sum(i.duration for i in self.items)


# ------------------------------------------------------------------ planning


def build_timeline(plan: Plan, platform: str, opts: Options, cache: Path, dry: bool = False) -> Timeline:
    """Work out every segment's real length once the voiceover is known.

    With dry=True no audio is generated; VO lengths are estimated. Used by
    'clipbot check' so it runs instantly and offline.
    """
    engine = opts.tts or plan.tts
    items: list[TimelineItem] = []
    warnings: list[str] = []
    offset = 0.0
    src_durations: dict[Path, float] = {}

    def file_len(f: Path) -> float | None:
        if not f.exists():
            return None  # dry run with missing footage: assume there is enough
        if f not in src_durations:
            src_durations[f] = ffmpeg.media_duration(f)
        return src_durations[f]

    for seg in plan.cut_segments(platform):
        speech = None
        vo_len = 0.0
        if seg.vo:
            if dry:
                vo_len = estimate_seconds(seg.vo, plan.rate)
            else:
                speech = synthesize(seg.vo, cache, engine, plan.voice, plan.rate, plan.pitch, opts.align)
                vo_len = speech.duration
        need = seg.vo_delay + vo_len + TAIL_PAD if seg.vo else 0.0
        # Whole frames only, so audio and video stay in sync across many segments.
        duration = math.ceil(max(seg.clip_len, need) * FPS - 1e-6) / FPS

        flen = file_len(seg.file)
        if flen is not None and seg.start >= flen:
            raise ValueError(f"[{seg.id}] starts at {fmt_time(seg.start)} but {seg.file.name} is only "
                             f"{fmt_time(flen)} long")
        planned_src = seg.end - seg.start
        if seg.extend:
            want_src = duration * seg.speed
        else:
            want_src = planned_src
        avail = (flen - seg.start) if flen is not None else want_src
        if flen is not None and seg.end > flen + 0.05:
            warnings.append(f"[{seg.id}] end {fmt_time(seg.end)} is past the end of {seg.file.name} "
                            f"({fmt_time(flen)})")
        src_len = max(1.0 / FPS, min(want_src, avail))
        freeze = max(0.0, duration - src_len / seg.speed)
        if freeze < 0.5 / FPS:
            freeze = 0.0
        if need > seg.clip_len + 0.05:
            msg = f"[{seg.id}] voiceover needs {need:.1f}s but the clip is {seg.clip_len:.1f}s; "
            if src_len > planned_src + 0.05:
                msg += f"using footage up to {fmt_time(seg.start + src_len)}"
                if freeze:
                    msg += f" and holding the last frame {freeze:.1f}s"
            else:
                msg += f"holding the last frame {freeze:.1f}s"
            warnings.append(msg)
        items.append(TimelineItem(seg, offset, duration, src_len, freeze, speech))
        offset += duration

    cut = plan.platforms[platform]
    hook_text = cut.hook if cut.hook is not None else plan.hook
    if len(hook_text) > 45:
        warnings.append(f"{platform}: hook is {len(hook_text)} characters; over ~45 it wraps to 3+ lines "
                        "and is hard to read in one second")
    tl = Timeline(platform, items, warnings)
    rules = PLATFORM_RULES[platform]
    if tl.total < rules["min"]:
        warnings.append(f"{platform}: {tl.total:.1f}s is SHORT of the {rules['min']:.0f}s target ({rules['label']})")
    elif tl.total > rules["max"]:
        warnings.append(f"{platform}: {tl.total:.1f}s is LONGER than the {rules['max']:.0f}s target ({rules['label']})")
    if platform == "shorts":
        for it in items:
            if it.seg.violent and it.offset < 7.0:
                warnings.append(
                    f"shorts: segment '{it.seg.id}' is marked violent and starts at {it.offset:.1f}s. "
                    "YouTube limits ads on Shorts with graphic violence in the first 7 seconds; move it later."
                )
    return tl


# ------------------------------------------------------------------ filters


def _lerp_expr(keys: list[tuple[float, float]]) -> str:
    """Piecewise-linear expression of t over (time, value) keyframes."""
    if len(keys) == 1:
        return f"{keys[0][1]:.4f}"
    expr = f"{keys[-1][1]:.4f}"
    for (t0, v0), (t1, v1) in reversed(list(zip(keys, keys[1:]))):
        seg = f"({v0:.4f}+({v1 - v0:.4f})*(t-{t0:.3f})/{max(1e-3, t1 - t0):.3f})"
        expr = f"if(lt(t,{t1:.3f}),{seg},{expr})"
    return f"if(lt(t,{keys[0][0]:.3f}),{keys[0][1]:.4f},{expr})"


def _focus_expr(focus) -> str:
    return _lerp_expr(focus) if isinstance(focus, list) else f"{float(focus):.4f}"


def video_filter(seg: Segment, freeze: float, hdr: bool, preview: bool) -> str:
    chain: list[str] = []
    if hdr:
        chain.append(
            "zscale=tin=smpte2084:min=bt2020nc:pin=bt2020:rin=tv:t=linear:npl=100,format=gbrpf32le,"
            "zscale=p=bt709,tonemap=hable:desat=0,zscale=t=bt709:m=bt709:r=tv,format=yuv420p"
        )
    if seg.speed != 1.0:
        chain.append(f"setpts=PTS/{seg.speed}")
    chain.append(f"fps={FPS}")
    fx = _focus_expr(seg.focus)
    pre = ",".join(chain)

    if seg.crop == "crop":
        h = int(round(H * seg.zoom / 2)) * 2
        g = (
            f"[0:v]{pre},scale=-2:{h}:flags=lanczos,"
            f"crop=w={W}:h={H}:x='(iw-ow)*clip({fx},0,1)':y='(ih-oh)/2'[v0]"
        )
    else:  # blur fill: sharp 16:9 picture in the middle, blurred copy behind it
        fw = int(round(W * seg.zoom / 2)) * 2
        blur = "6:1" if preview else "10:2"
        g = (
            f"[0:v]{pre},split=2[bgsrc][fgsrc];"
            f"[bgsrc]scale=270:480:force_original_aspect_ratio=increase,crop=270:480,"
            f"boxblur={blur},eq=brightness=-0.10:saturation=1.15,scale={W}:{H}[bg];"
            f"[fgsrc]scale={fw}:-2:flags=lanczos,crop=w={W}:h=ih:x='(iw-ow)*clip({fx},0,1)'[fg];"
            f"[bg][fg]overlay=x=0:y=(H-h)/2[v0]"
        )
    tail = "[v0]"
    if freeze > 0.01:
        g += f";[v0]tpad=stop_mode=clone:stop_duration={freeze:.3f}[v1]"
        tail = "[v1]"
    g += f";{tail}format=yuv420p,setsar=1[vout]"
    return g


def _atempo(speed: float) -> str:
    # atempo accepts 0.5..2.0 in one step, which matches the plan's allowed range.
    return f"atempo={speed}," if speed != 1.0 else ""


# ------------------------------------------------------------------ rendering


DUCK_RAMP = 0.25  # seconds to fade game audio down/up around a voiceover line


def _duck_expr(item: TimelineItem) -> str:
    """Volume expression: game audio dips while the voiceover talks, then comes back."""
    seg = item.seg
    gap, under = seg.game_audio_gap, seg.game_audio
    if not item.speech:
        return f"{gap:.3f}"
    a = seg.vo_delay
    b = seg.vo_delay + item.speech.duration
    r = DUCK_RAMP
    # 1 inside [a, b], ramping to 0 over r seconds outside it.
    inside = f"clip(min((t-{a - r:.3f})/{r},({b + r:.3f}-t)/{r}),0,1)"
    return f"{gap:.3f}+({under - gap:.3f})*{inside}"


def _part_key(item: TimelineItem, preview: bool) -> str:
    seg = item.seg
    st = seg.file.stat()
    raw = json.dumps(
        [
            PART_VERSION, str(seg.file.resolve()), st.st_size, int(st.st_mtime), seg.start, seg.speed,
            seg.crop, seg.focus, seg.zoom, _duck_expr(item),
            round(item.duration, 4), round(item.src_len, 4), round(item.freeze, 4), preview,
        ],
        default=str,
    )
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:20]


def render_segment(item: TimelineItem, out: Path, preview: bool, verbose: bool) -> None:
    seg = item.seg
    info = ffmpeg.MediaInfo(seg.file)
    hdr = info.is_hdr and ffmpeg.has_filter("zscale")
    if info.is_hdr and not hdr and verbose:
        print(f"  ! {seg.file.name} is HDR but this ffmpeg has no zscale; colours may look washed out")
    vf = video_filter(seg, item.freeze, hdr, preview)

    vol = _duck_expr(item)

    args = ["-ss", f"{seg.start:.3f}", "-t", f"{item.src_len:.3f}", "-i", str(seg.file)]
    if info.audio:
        af = f"[0:a]{_atempo(seg.speed)}volume='{vol}':eval=frame,aresample=48000,aformat=channel_layouts=stereo,apad[aout]"
    else:
        args += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]
        af = "[1:a]anull[aout]"
    args += [
        "-filter_complex", vf + ";" + af,
        "-map", "[vout]", "-map", "[aout]",
        "-t", f"{item.duration:.3f}",
        "-r", str(FPS),
        "-c:v", "libx264", "-preset", "ultrafast" if preview else "veryfast",
        "-crf", "26" if preview else "16",
        "-c:a", "pcm_s16le",
        str(out),
    ]
    ffmpeg.run(args, verbose=verbose)


def _measure_loudness(wav: Path, target: float) -> dict | None:
    err = ffmpeg.run(
        ["-i", str(wav), "-af", f"loudnorm=I={target}:TP=-1.5:LRA=11:print_format=json", "-f", "null", "-"],
        loglevel="info",  # loudnorm prints its JSON at info level
    )
    m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", err, re.S)
    return json.loads(m.group(0)) if m else None


def render_platform(plan: Plan, platform: str, opts: Options) -> tuple[Path, Timeline]:
    ffmpeg.require_tools()
    out_root = opts.out_dir.resolve() / plan.slug
    work = out_root / ".work" / platform
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    cache = opts.out_dir.resolve() / ".cache" / "tts"

    tl = build_timeline(plan, platform, opts, cache)
    for w in tl.warnings:
        print(f"  ! {w}")

    # 1) each segment -> vertical clip with game audio
    # Parts are cached, so a segment shared by several cuts is only encoded once.
    part_cache = opts.out_dir.resolve() / ".cache" / "parts"
    part_cache.mkdir(parents=True, exist_ok=True)
    parts = []
    for i, item in enumerate(tl.items):
        cached = part_cache / f"{_part_key(item, opts.preview)}.mkv"
        label = f"  [{platform}] segment {i + 1}/{len(tl.items)} '{item.seg.id}' ({item.duration:.1f}s)"
        if cached.exists():
            print(label + " (cached)")
        else:
            print(label)
            tmp = cached.with_name(cached.stem + ".tmp.mkv")
            render_segment(item, tmp, opts.preview, opts.verbose)
            tmp.replace(cached)
        parts.append(cached)
    (work / "parts.txt").write_text(
        "".join("file '" + p.as_posix().replace("'", "'\\''") + "'\n" for p in parts), encoding="utf-8"
    )
    body = work / "body.mkv"
    ffmpeg.run(["-f", "concat", "-safe", "0", "-i", "parts.txt", "-c", "copy", body.name], cwd=work, verbose=opts.verbose)

    # 2) captions / hook / overlays
    words: list[Word] = []
    overlays: list[TimedText] = []
    for item in tl.items:
        base = item.offset + item.seg.vo_delay
        if item.speech:
            words += [Word(w.text, base + w.start, base + w.end) for w in item.speech.words]
        for ov in item.seg.text:
            end = item.duration if ov.end is None else min(ov.end, item.duration)
            overlays.append(TimedText(ov.text, item.offset + ov.start, item.offset + end))
    cut = plan.platforms[platform]
    hook_text = cut.hook if cut.hook is not None else plan.hook
    hook = TimedText(hook_text, 0.0, cut.hook_duration) if hook_text else None
    (work / "subs.ass").write_text(build_ass(words, hook, overlays, plan.captions, tl.total), encoding="utf-8")
    fonts = work / "fonts"
    fonts.mkdir()
    for d in (REPO_FONTS, plan.path.parent / "fonts"):
        if d.is_dir():
            for f in d.iterdir():
                if f.suffix.lower() in (".ttf", ".otf"):
                    shutil.copy2(f, fonts / f.name)

    # 3) audio mix: game audio + VO lines at their offsets (+ optional music)
    inputs = ["-i", body.name]
    graph = ["[0:a]anull[game]"]
    mix = ["[game]"]
    n = 1
    for item in tl.items:
        if item.speech:
            ms = int(round((item.offset + item.seg.vo_delay) * 1000))
            inputs += ["-i", str(item.speech.wav)]
            graph.append(f"[{n}:a]adelay={ms}|{ms},aformat=channel_layouts=stereo[vo{n}]")
            mix.append(f"[vo{n}]")
            n += 1
    if plan.music and plan.music.exists():
        inputs += ["-stream_loop", "-1", "-i", str(plan.music)]
        graph.append(f"[{n}:a]volume={plan.music_volume:.3f},aresample=48000,aformat=channel_layouts=stereo[mus]")
        mix.append("[mus]")
        n += 1
    graph.append(f"{''.join(mix)}amix=inputs={len(mix)}:duration=first:normalize=0:dropout_transition=0[mixed]")
    mixed = work / "mixed.wav"
    ffmpeg.run(
        [*inputs, "-filter_complex", ";".join(graph), "-map", "[mixed]", "-t", f"{tl.total:.3f}",
         "-c:a", "pcm_s16le", "-ar", "48000", mixed.name],
        cwd=work, verbose=opts.verbose,
    )

    # 4) two-pass loudness normalisation (platforms target about -14 LUFS)
    target = plan.loudness
    m = _measure_loudness(mixed, target)
    if m and m.get("input_i") not in (None, "-inf"):
        ln = (
            f"loudnorm=I={target}:TP=-1.5:LRA=11:measured_I={m['input_i']}:measured_TP={m['input_tp']}:"
            f"measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}:offset={m['target_offset']}:linear=true"
        )
    else:
        ln = f"loudnorm=I={target}:TP=-1.5:LRA=11"

    # 5) final encode: burn captions, normalised audio, platform-friendly mp4
    final = out_root / f"{plan.slug}_{platform}{'_preview' if opts.preview else ''}.mp4"
    ffmpeg.run(
        [
            "-i", body.name, "-i", mixed.name,
            "-filter_complex", f"[0:v]ass=subs.ass:fontsdir=fonts[v];[1:a]{ln},aresample=48000[a]",
            "-map", "[v]", "-map", "[a]",
            "-t", f"{tl.total:.3f}",
            "-c:v", "libx264", "-preset", "ultrafast" if opts.preview else "medium",
            "-crf", "28" if opts.preview else "19",
            "-maxrate", "16M", "-bufsize", "32M",
            "-profile:v", "high", "-pix_fmt", "yuv420p", "-r", str(FPS),
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
            "-movflags", "+faststart",
            str(final.resolve()),
        ],
        cwd=work, verbose=opts.verbose,
    )
    write_post_notes(plan, platform, tl, out_root)
    if not opts.keep_work:
        shutil.rmtree(work, ignore_errors=True)
    return final, tl


def write_post_notes(plan: Plan, platform: str, tl: Timeline, out_root: Path) -> Path:
    cut = plan.platforms[platform]
    tags = " ".join(f"#{h}" for h in cut.hashtags)
    lines = [
        f"{plan.title} - {platform}",
        f"Length: {tl.total:.1f}s",
        "",
    ]
    if cut.title:
        lines += ["TITLE:", cut.title, ""]
    lines += ["CAPTION:", (cut.caption + ("\n\n" + tags if tags else "")).strip() or "(none in plan)", ""]
    if tl.warnings:
        lines += ["CHECK BEFORE POSTING:", *[f"- {w}" for w in tl.warnings], ""]
    p = out_root / f"{plan.slug}_{platform}.txt"
    p.write_text("\n".join(lines), encoding="utf-8")
    return p
