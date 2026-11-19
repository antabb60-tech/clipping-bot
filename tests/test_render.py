"""End-to-end render on tiny generated footage. Needs ffmpeg on PATH."""

import json
import shutil
import subprocess
import textwrap

import pytest

from clipbot.cli import main
from clipbot.ffmpeg import MediaInfo
from clipbot.plan import load_plan
from clipbot.render import Options, build_timeline

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")


def make_clip(path, seconds, audio=True, hdr=False):
    args = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", f"testsrc2=s=640x360:r=30:d={seconds}"]
    if audio:
        args += ["-f", "lavfi", "-i", f"sine=f=440:d={seconds}"]
    args += ["-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p"]
    if hdr:
        # Write the HDR10 colour tags into the H.264 stream itself; the -color_* options
        # alone are not written by every ffmpeg/x264 version.
        args += ["-color_trc", "smpte2084", "-color_primaries", "bt2020", "-colorspace", "bt2020nc",
                 "-bsf:v", "h264_metadata=transfer_characteristics=16:colour_primaries=9:matrix_coefficients=9"]
    if audio:
        args += ["-c:a", "aac"]
    subprocess.run(args + [str(path)], check=True)


@pytest.fixture()
def project(tmp_path):
    foot = tmp_path / "footage"
    foot.mkdir()
    make_clip(foot / "a.mp4", 6)
    make_clip(foot / "mute.mp4", 3, audio=False)
    plan = tmp_path / "plan.yaml"
    plan.write_text(textwrap.dedent("""
        title: Tiny test
        footage_dir: footage
        tts: silent
        hook: "Hook text"
        segments:
          - {id: one, file: a.mp4, start: 0.5, end: 2, vo: "One two three four five six seven eight nine ten.", text: LABEL}
          - {id: two, file: mute.mp4, start: 1, end: 2.5, crop: crop, focus: [[0, 0], [1, 1]], extend: false,
             vo: "This line is long enough that the clip has to hold its last frame for a while."}
          - {id: three, file: a.mp4, start: 4, end: 5.5, speed: 1.5, zoom: 1.4}
        platforms:
          shorts: [one, two, three]
          x: [one, three]
    """), encoding="utf-8")
    return tmp_path, plan


def test_timeline_frame_aligned_and_freezes(project):
    root, plan_path = project
    plan = load_plan(plan_path)
    tl = build_timeline(plan, "shorts", Options(out_dir=root / "out"), root / "out" / ".cache", dry=False)
    for it in tl.items:
        assert abs(it.duration * 30 - round(it.duration * 30)) < 1e-6
    one, two, three = tl.items
    assert one.src_len > 1.5  # extended into later footage for the VO
    assert two.freeze > 0  # extend: false -> holds the last frame
    assert three.duration == pytest.approx(1.0, abs=1 / 30)  # 1.5s at 1.5x speed
    assert any("hold" in w for w in tl.warnings)


def test_render_outputs(project):
    root, plan_path = project
    out = root / "out"
    assert main(["render", str(plan_path), "-o", str(out), "--preview"]) == 0
    files = sorted(p.name for p in (out / "tiny-test").iterdir() if p.is_file())
    assert files == ["tiny-test_shorts.txt", "tiny-test_shorts_preview.mp4",
                     "tiny-test_x.txt", "tiny-test_x_preview.mp4"]
    plan = load_plan(plan_path)
    for name in ("shorts", "x"):
        tl = build_timeline(plan, name, Options(out_dir=out), out / ".cache" / "tts")
        info = MediaInfo(out / "tiny-test" / f"tiny-test_{name}_preview.mp4")
        assert (info.width, info.height) == (1080, 1920)
        assert info.audio is not None
        assert abs(info.duration - tl.total) < 0.1
    # Shared segments are rendered once and reused.
    assert len(list((out / ".cache" / "parts").glob("*.mkv"))) == 3
    # Work folder is cleaned up.
    assert not (out / "tiny-test" / ".work" / "shorts").exists()


def test_hdr_source_renders(tmp_path):
    from clipbot import ffmpeg
    if not ffmpeg.has_filter("zscale"):
        pytest.skip("ffmpeg built without zscale")
    (tmp_path / "f").mkdir()
    make_clip(tmp_path / "f" / "hdr.mp4", 2, hdr=True)
    assert MediaInfo(tmp_path / "f" / "hdr.mp4").is_hdr
    plan = tmp_path / "p.yaml"
    plan.write_text("footage_dir: f\ntts: silent\nsegments:\n  - {file: hdr.mp4, start: 0, end: 1.5}\n"
                    "platforms: {x: []}\n", encoding="utf-8")
    assert main(["render", str(plan), "-o", str(tmp_path / "out"), "--preview"]) == 0


def test_check_command(project, capsys):
    root, plan_path = project
    assert main(["check", str(plan_path), "-o", str(root / "out")]) == 0
    out = capsys.readouterr().out
    assert "shorts" in out and "SHORT" in out  # tiny test plan is under 20s


def test_check_reports_missing_footage(tmp_path, capsys):
    plan = tmp_path / "p.yaml"
    plan.write_text("segments:\n  - {file: nope.mp4, start: 0, end: 3, vo: hi}\n", encoding="utf-8")
    assert main(["check", str(plan), "-o", str(tmp_path / "out")]) == 1
    assert "missing footage" in capsys.readouterr().out
