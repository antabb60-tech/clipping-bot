"""Build an .ass subtitle file: animated word captions, hook, and text overlays.

Everything is drawn by ffmpeg's libass at 1080x1920, so it is burned into the
video and looks the same on every platform.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

from clipbot.tts import Word

W, H = 1080, 1920


@dataclass
class TimedText:
    text: str
    start: float
    end: float


def ass_color(hex_color: str, alpha: int = 0) -> str:
    """'#RRGGBB' -> '&HAABBGGRR' (ASS colour order)."""
    h = hex_color.lstrip("#")
    if not re.fullmatch(r"[0-9a-fA-F]{6}", h):
        raise ValueError(f"colour must look like #FFE100, got {hex_color!r}")
    r, g, b = h[0:2], h[2:4], h[4:6]
    return f"&H{alpha:02X}{b}{g}{r}".upper()


def ass_time(t: float) -> str:
    t = max(0.0, t)
    cs = int(round(t * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def escape(text: str) -> str:
    return text.replace("\\", "/").replace("{", "(").replace("}", ")").replace("\n", "\\N")


def group_words(words: list[Word], max_words: int = 3, max_chars: int = 14, gap: float = 0.35) -> list[list[Word]]:
    """Split words into short caption chunks: by count, length, punctuation and pauses."""
    groups: list[list[Word]] = []
    cur: list[Word] = []
    for w in words:
        if cur:
            chars = sum(len(x.text) + 1 for x in cur) + len(w.text)
            if len(cur) >= max_words or chars > max_chars or w.start - cur[-1].end > gap:
                groups.append(cur)
                cur = []
        cur.append(w)
        if re.search(r"[.!?,;:]$", w.text):
            groups.append(cur)
            cur = []
    if cur:
        groups.append(cur)
    return groups


def _clean(word: str, upper: bool) -> str:
    # Drop trailing commas/periods on captions (looks cleaner); keep ! and ?.
    w = re.sub(r"[,.;:]+$", "", word)
    return w.upper() if upper else w


def build_ass(
    words: list[Word],
    hook: TimedText | None,
    overlays: Iterable[TimedText],
    style: dict,
    total: float,
) -> str:
    font = style.get("font", "Arial Black")
    size = int(style.get("size", 84))
    outline = float(style.get("outline", 7))
    color = ass_color(style.get("color", "#FFFFFF"))
    hi = ass_color(style.get("highlight", "#FFE100"))
    y = int(style.get("y", 1180))
    upper = bool(style.get("uppercase", True))

    lines = [
        "[Script Info]",
        "ScriptType: v4.00+",
        f"PlayResX: {W}",
        f"PlayResY: {H}",
        "WrapStyle: 0",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, "
        "Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Caption,{font},{size},{color},{hi},&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,{outline},3,5,60,60,0,1",
        f"Style: Hook,{font},78,&H00000000,&H00000000,&H00FFFFFF,&H00000000,-1,0,0,0,100,100,0,0,3,18,0,8,80,80,0,1",
        f"Style: Label,{font},64,&H00000000,&H00000000,{ass_color('#FFE100')},&H00000000,-1,0,0,0,100,100,0,0,3,14,0,8,90,90,0,1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]

    def ev(layer: int, start: float, end: float, st: str, text: str) -> None:
        end = min(end, total)
        if end - start < 0.02:
            return
        lines.append(f"Dialogue: {layer},{ass_time(start)},{ass_time(end)},{st},,0,0,0,,{text}")

    if hook and hook.text:
        anim = r"\fscx70\fscy70\t(0,110,\fscx106\fscy106)\t(110,200,\fscx100\fscy100)\fad(0,180)"
        ev(3, hook.start, hook.end, "Hook", "{\\an8\\pos(540,300)" + anim + "}" + escape(hook.text.upper()))

    for ov in overlays:
        if ov.text:
            ev(2, ov.start, ov.end, "Label", "{\\an8\\pos(540,520)\\fad(120,120)}" + escape(ov.text.upper()))

    if style.get("enabled", True):
        groups = group_words(words, int(style.get("max_words", 3)), int(style.get("max_chars", 14)))
        for gi, g in enumerate(groups):
            next_start = groups[gi + 1][0].start if gi + 1 < len(groups) else total
            g_end = min(g[-1].end + 0.25, next_start)
            texts = [escape(_clean(w.text, upper)) for w in g]
            for wi, w in enumerate(g):
                start = w.start if wi else g[0].start
                end = g[wi + 1].start if wi + 1 < len(g) else g_end
                parts = [
                    ("{\\c" + hi + "}" + t + "{\\c" + color + "}") if i == wi else t
                    for i, t in enumerate(texts)
                ]
                pop = r"\fscx80\fscy80\t(0,90,\fscx100\fscy100)" if wi == 0 else ""
                ev(1, start, end, "Caption", "{\\an5\\pos(540," + str(y) + ")" + pop + "}" + " ".join(parts))

    return "\n".join(lines) + "\n"
