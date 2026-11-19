from clipbot.captions import TimedText, ass_color, ass_time, build_ass, group_words
from clipbot.render import _lerp_expr
from clipbot.tts import Word, estimate_words


def test_ass_color_and_time():
    assert ass_color("#FFE100") == "&H0000E1FF"
    assert ass_time(3723.456) == "1:02:03.46"


def test_group_words_breaks_on_punctuation_and_count():
    words = [Word(w, i * 0.3, i * 0.3 + 0.25) for i, w in enumerate("one two, three four five six".split())]
    groups = [[w.text for w in g] for g in group_words(words, max_words=3, max_chars=40)]
    assert groups == [["one", "two,"], ["three", "four", "five"], ["six"]]


def test_estimate_words_cover_duration():
    ws = estimate_words("Hello there. General Kenobi!", 3.0)
    assert len(ws) == 4
    assert ws[0].start >= 0 and ws[-1].end <= 3.0
    assert all(a.end <= b.start + 1e-9 for a, b in zip(ws, ws[1:]))


def test_build_ass_has_hook_overlay_and_highlight():
    words = estimate_words("this is a test", 2.0)
    ass = build_ass(words, TimedText("Big hook", 0, 2), [TimedText("label {x}", 1, 2)],
                    {"highlight": "#FFE100"}, total=2.5)
    assert "BIG HOOK" in ass
    assert "LABEL (X)" in ass  # braces escaped
    assert ass.count("Style: Caption") == 1
    assert "\\c&H0000E1FF" in ass


def _eval_ff(expr: str, t: float) -> float:
    """Evaluate the small subset of ffmpeg expressions _lerp_expr produces."""
    import re

    py = re.sub(r"\bif\(lt\(t,", "_if((t<", expr)
    py = py.replace("_if((t<", "_if(_lt(t,")
    return eval(py, {"_if": lambda c, a, b: a if c else b, "_lt": lambda x, y: x < y, "t": t})


def test_lerp_expr_values():
    expr = _lerp_expr([(1.0, 0.2), (3.0, 0.6), (5.0, 0.4)])
    for t, want in [(0, 0.2), (1, 0.2), (2, 0.4), (3, 0.6), (4, 0.5), (9, 0.4)]:
        assert abs(_eval_ff(expr, t) - want) < 1e-6, (t, expr)


def test_realign_handles_mismatched_tokens():
    from clipbot.tts import _realign

    timed = [Word("In", 0, .2), Word("GTA", .2, .5), Word("6", .5, .7), Word("ten", .8, 1.0), Word("seconds", 1.0, 1.4)]
    out = _realign("In GTA 6, 10 seconds".split(), timed)
    assert [w.text for w in out] == ["In", "GTA", "6,", "10", "seconds"]
    assert out[2].start == .5 and out[4].start == 1.0
    assert 0.7 <= out[3].start < out[3].end <= 1.0
