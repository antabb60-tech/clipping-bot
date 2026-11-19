"""clipbot command-line interface.

  clipbot check  PLAN.yaml            validate a plan and show each cut's length
  clipbot render PLAN.yaml [-p tiktok,shorts,x] [--preview]
  clipbot new    NAME                 start a new plan from the template
  clipbot probe  VIDEO                show a recording's size, fps, length, HDR
  clipbot voices [en-US]              list free Edge voices
  clipbot doctor                      check the install
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from clipbot import __version__, ffmpeg
from clipbot.plan import PLATFORM_RULES, PlanError, check_files, fmt_time, load_plan
from clipbot.render import Options, build_timeline, render_platform
from clipbot.tts import ENGINES, TTSError

TEMPLATE = Path(__file__).resolve().parent / "template.yaml"


def _platforms(arg: str | None, plan) -> list[str]:
    if not arg or arg == "all":
        return list(plan.platforms)
    names = [p.strip().lower() for p in arg.split(",") if p.strip()]
    for n in names:
        if n not in plan.platforms:
            raise PlanError(f"plan has no '{n}' cut; it has: {', '.join(plan.platforms)}")
    return names


def cmd_check(a) -> int:
    plan = load_plan(a.plan)
    problems = check_files(plan)
    print(f"Plan: {plan.title}  ({len(plan.segments)} segments, voice {plan.voice} via {a.tts or plan.tts})")
    opts = Options(out_dir=Path(a.out), tts=a.tts)
    cache = Path(a.out).resolve() / ".cache" / "tts"
    for name in _platforms(a.platform, plan):
        tl = build_timeline(plan, name, opts, cache, dry=not a.real)
        rules = PLATFORM_RULES[name]
        ok = rules["min"] <= tl.total <= rules["max"]
        print(f"\n  {name:7s} ~{tl.total:5.1f}s  {'OK' if ok else 'OUT OF RANGE'}  target {rules['label']}")
        for it in tl.items:
            vo = (it.seg.vo[:52] + "...") if len(it.seg.vo) > 55 else it.seg.vo
            print(f"    {fmt_time(it.offset)}  {it.seg.id:12s} {it.duration:4.1f}s  {vo}")
        for w in tl.warnings:
            print(f"    ! {w}")
    if problems:
        print()
        for p in problems:
            print(f"  ✗ {p}")
        return 1
    if not a.real:
        print("\nLengths are estimates. Run with --real to generate the voiceover and get exact lengths.")
    return 0


def cmd_doctor(a) -> int:
    """Check that everything clipbot needs is installed and working."""
    import platform
    import shutil

    ok = True

    def line(good: bool, label: str, fix: str = "") -> None:
        nonlocal ok
        ok &= good
        print(f"  {'OK ' if good else 'BAD'}  {label}" + ("" if good or not fix else f"\n         fix: {fix}"))

    print(f"clipbot {__version__} on Python {platform.python_version()} ({platform.system()})")
    line(sys.version_info >= (3, 10), "Python 3.10 or newer", "install Python 3.12 (winget install Python.Python.3.12)")
    have = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None
    line(have, "ffmpeg and ffprobe on PATH", "winget install Gyan.FFmpeg, then open a new terminal")
    if have:
        line(ffmpeg.has_filter("ass"), "ffmpeg can draw captions (libass)", "install the full build: winget install Gyan.FFmpeg")
        line(ffmpeg.has_filter("loudnorm"), "ffmpeg loudness filter")
        hdr = ffmpeg.has_filter("zscale")
        print(f"  {'OK ' if hdr else 'warn'}  HDR tone-mapping (zscale)" + ("" if hdr else ": HDR clips may look washed out"))
    try:
        import yaml  # noqa: F401
        line(True, "PyYAML installed")
    except ImportError:
        line(False, "PyYAML installed", "pip install pyyaml")
    if a.offline:
        print("  skip edge-tts voice test (--offline)")
    else:
        try:
            import tempfile

            from clipbot.tts import synthesize

            with tempfile.TemporaryDirectory() as td:
                sp = synthesize("Testing one two three.", Path(td), "edge", "en-US-AndrewNeural", "+0%", align="estimate")
            line(sp.duration > 0.5, f"free Edge voice works ({sp.duration:.1f}s test clip)")
        except Exception as e:  # noqa: BLE001
            line(False, f"free Edge voice works ({e})", "check your internet connection, or use --tts sapi")
    print("\nAll good." if ok else "\nFix the BAD lines above, then run clipbot doctor again.")
    return 0 if ok else 1


def cmd_render(a) -> int:
    plan = load_plan(a.plan)
    problems = check_files(plan)
    if problems:
        for p in problems:
            print(f"✗ {p}")
        return 1
    opts = Options(out_dir=Path(a.out), tts=a.tts, preview=a.preview, verbose=a.verbose,
                   align=a.align, keep_work=a.keep_work)
    results = []
    for name in _platforms(a.platform, plan):
        t0 = time.time()
        print(f"Rendering {name} ...")
        out, tl = render_platform(plan, name, opts)
        results.append((name, out, tl))
        print(f"  done in {time.time() - t0:.0f}s -> {out}")
    print("\nFinished:")
    for name, out, tl in results:
        print(f"  {name:7s} {tl.total:5.1f}s  {out}")
    print("Post notes (caption, hashtags, warnings) are the .txt files next to each video.")
    return 0


def cmd_new(a) -> int:
    dest = Path(a.name if a.name.endswith((".yaml", ".yml")) else a.name + ".yaml")
    if dest.exists() and not a.force:
        print(f"{dest} already exists (use --force to overwrite)")
        return 1
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(TEMPLATE.read_text(encoding="utf-8"), encoding="utf-8")
    print(f"Created {dest}. Edit it, then run: clipbot check {dest}")
    return 0


def cmd_probe(a) -> int:
    ffmpeg.require_tools()
    for f in a.files:
        info = ffmpeg.MediaInfo(Path(f))
        hdr = "HDR (will be tone-mapped)" if info.is_hdr else "SDR"
        audio = "audio" if info.audio else "NO AUDIO"
        print(f"{f}: {info.width}x{info.height} {info.fps:.2f}fps {fmt_time(info.duration)} {hdr}, {audio}")
    return 0


def cmd_voices(a) -> int:
    from clipbot.tts import list_edge_voices

    for v in list_edge_voices(a.prefix):
        print(f"{v['ShortName']:32s} {v['Gender']:7s} {', '.join(v.get('VoiceTag', {}).get('VoicePersonalities', []))}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="clipbot", description="Gameplay + YAML plan -> vertical videos.")
    p.add_argument("--version", action="version", version=f"clipbot {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    def common(sp):
        sp.add_argument("plan", help="path to the plan .yaml")
        sp.add_argument("-p", "--platform", help="tiktok, shorts, x, a comma list, or all (default)")
        sp.add_argument("--tts", choices=ENGINES, help="override the plan's voice engine")
        sp.add_argument("-o", "--out", default="out", help="output folder (default: out)")

    c = sub.add_parser("check", help="validate a plan and show lengths per platform")
    common(c)
    c.add_argument("--real", action="store_true", help="generate the voiceover for exact lengths (cached for render)")
    c.set_defaults(fn=cmd_check)

    r = sub.add_parser("render", help="render finished videos")
    common(r)
    r.add_argument("--preview", action="store_true", help="fast low-quality render to check timing")
    r.add_argument("--align", choices=("auto", "whisper", "estimate"), default="auto",
                   help="caption timing for voices without word timings")
    r.add_argument("--keep-work", action="store_true", help="keep intermediate files")
    r.add_argument("-v", "--verbose", action="store_true", help="print ffmpeg commands")
    r.set_defaults(fn=cmd_render)

    n = sub.add_parser("new", help="create a new plan from the template")
    n.add_argument("name")
    n.add_argument("--force", action="store_true")
    n.set_defaults(fn=cmd_new)

    pr = sub.add_parser("probe", help="describe recordings")
    pr.add_argument("files", nargs="+")
    pr.set_defaults(fn=cmd_probe)

    d = sub.add_parser("doctor", help="check that ffmpeg, captions and the free voice work")
    d.add_argument("--offline", action="store_true", help="skip the online voice test")
    d.set_defaults(fn=cmd_doctor)

    v = sub.add_parser("voices", help="list free Edge voices")
    v.add_argument("prefix", nargs="?", default="en-")
    v.set_defaults(fn=cmd_voices)
    return p


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    a = build_parser().parse_args(argv)
    try:
        return a.fn(a)
    except (PlanError, TTSError, ffmpeg.FFmpegError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130
