import textwrap

import pytest

from clipbot.plan import PlanError, load_plan, parse_timecode


def write(tmp_path, body):
    p = tmp_path / "plan.yaml"
    p.write_text(textwrap.dedent(body), encoding="utf-8")
    return p


@pytest.mark.parametrize("value,expected", [
    ("12", 12.0), ("1:05", 65.0), ("1:02:03.5", 3723.5), (7, 7.0), ("0:04.25", 4.25),
])
def test_timecodes(value, expected):
    assert parse_timecode(value) == pytest.approx(expected)


@pytest.mark.parametrize("bad", ["1:2:3:4", "abc", "", None, True])
def test_bad_timecodes(bad):
    with pytest.raises(PlanError):
        parse_timecode(bad)


def test_minimal_plan_defaults(tmp_path):
    plan = load_plan(write(tmp_path, """
        title: Test Idea!
        segments:
          - {file: a.mp4, start: 0, end: 5, vo: hello there}
    """))
    assert plan.slug == "test-idea"
    assert set(plan.platforms) == {"tiktok", "shorts", "x"}
    seg = plan.segments["s1"]
    assert seg.file == tmp_path / "a.mp4"
    assert seg.crop == "blur" and seg.clip_len == 5


def test_defaults_merge_and_overrides(tmp_path):
    plan = load_plan(write(tmp_path, """
        defaults: {crop: crop, zoom: 1.2}
        segments:
          - {id: a, file: a.mp4, start: 0, end: 5}
          - {id: b, file: a.mp4, start: 5, end: 9, crop: blur, focus: [[0, 0.2], [3, 0.8]]}
        platforms:
          shorts: [b]
          tiktok: {segments: [a, b], hook: Long hook, hashtags: ["#gta6", fyp]}
    """))
    assert plan.segments["a"].crop == "crop" and plan.segments["a"].zoom == 1.2
    assert plan.segments["b"].crop == "blur"
    assert plan.segments["b"].focus == [(0.0, 0.2), (3.0, 0.8)]
    assert plan.platforms["shorts"].segments == ["b"]
    assert plan.platforms["tiktok"].hashtags == ["gta6", "fyp"]


@pytest.mark.parametrize("body,msg", [
    ("segments: []", "non-empty"),
    ("segments:\n  - {file: a.mp4, start: 5, end: 2}", "must be after"),
    ("segments:\n  - {file: a.mp4, start: 0, end: 2, crop: zoom}", "crop must be"),
    ("segments:\n  - {file: a.mp4, start: 0, end: 2}\nplatforms: {tiktok: [nope]}", "unknown segment"),
    ("segments:\n  - {file: a.mp4, start: 0, end: 2}\nplatforms: {insta: {}}", "unknown platform"),
    ("segments:\n  - {file: a.mp4, start: 0, end: 2, focus: 3}", "focus"),
])
def test_validation_errors(tmp_path, body, msg):
    with pytest.raises(PlanError, match=msg):
        load_plan(write(tmp_path, body))


def test_example_and_template_load():
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    load_plan(root / "examples" / "witness-memory.yaml")
    load_plan(root / "clipbot" / "template.yaml")
