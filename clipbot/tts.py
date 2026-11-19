"""Free text-to-speech engines with word timings for captions.

Engines:
  edge   Microsoft Edge online voices via edge-tts. Free, no API key, needs
         internet. Gives exact word timings. Default.
  sapi   Windows built-in voices (offline). Robotic, but always available.
  piper  Piper neural TTS (offline). 'voice' is the path to a .onnx model.
  silent Silence of the estimated length. For fast previews and tests.

Engines without word timings get them from faster-whisper when it is
installed (pip install faster-whisper), otherwise they are estimated.
"""

from __future__ import annotations

import asyncio
import difflib
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from clipbot import ffmpeg

ENGINES = ("edge", "sapi", "piper", "silent")


class TTSError(RuntimeError):
    pass


@dataclass
class Word:
    text: str
    start: float
    end: float


@dataclass
class Speech:
    wav: Path
    duration: float
    words: list[Word]


def _rate_factor(rate: str) -> float:
    m = re.match(r"^\s*([+-]?\d+(?:\.\d+)?)\s*%\s*$", rate or "")
    return 1.0 + (float(m.group(1)) / 100.0 if m else 0.0)


def estimate_seconds(text: str, rate: str = "+0%") -> float:
    """Rough speaking time: ~2.7 words/sec at normal rate."""
    words = len(text.split())
    return max(0.4, words / 2.7 / max(0.3, _rate_factor(rate)))


def tokenize(text: str) -> list[str]:
    return [w for w in text.split() if w.strip()]


def estimate_words(text: str, duration: float, lead: float = 0.05, tail: float = 0.15) -> list[Word]:
    """Spread words over the audio, weighted by length (plus a pause after punctuation)."""
    tokens = tokenize(text)
    if not tokens:
        return []
    weights = []
    for t in tokens:
        w = len(re.sub(r"\W", "", t)) + 2
        if re.search(r"[.!?]$", t):
            w += 4
        elif re.search(r"[,;:]$", t):
            w += 2
        weights.append(w)
    span = max(0.1, duration - lead - tail)
    total = sum(weights)
    out, t0 = [], lead
    for tok, w in zip(tokens, weights):
        d = span * w / total
        out.append(Word(tok, t0, t0 + d))
        t0 += d
    return out


def _cache_key(*parts: str) -> str:
    return hashlib.sha1("\x1f".join(parts).encode("utf-8")).hexdigest()[:16]


def _to_wav(src: Path, dst: Path) -> None:
    ffmpeg.run(["-i", str(src), "-ar", "48000", "-ac", "2", "-c:a", "pcm_s16le", str(dst)])


# ---------------------------------------------------------------- engines


def _edge(text: str, voice: str, rate: str, pitch: str, out_wav: Path) -> list[Word]:
    try:
        import edge_tts
    except ImportError as e:  # pragma: no cover
        raise TTSError("edge-tts is not installed: pip install edge-tts") from e

    async def go() -> tuple[bytes, list[Word]]:
        try:
            comm = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch, boundary="WordBoundary")
        except TypeError:  # edge-tts < 7 emits word boundaries by default
            comm = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch)
        audio = bytearray()
        words: list[Word] = []
        async for chunk in comm.stream():
            if chunk["type"] == "audio":
                audio.extend(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                start = chunk["offset"] / 1e7
                words.append(Word(chunk["text"], start, start + chunk["duration"] / 1e7))
        return bytes(audio), words

    last: Exception | None = None
    for attempt in range(3):  # the free endpoint occasionally drops a connection
        try:
            audio, words = asyncio.run(go())
            break
        except Exception as e:  # noqa: BLE001 - surface any network/library error nicely
            last = e
            time.sleep(1.5 * (attempt + 1))
    else:
        raise TTSError(
            f"edge-tts failed ({type(last).__name__}: {last}). It needs internet. "
            "Check the voice name with 'clipbot voices', or use --tts sapi for an offline voice."
        ) from last
    if not audio:
        raise TTSError("edge-tts returned no audio (bad voice name?)")
    with tempfile.TemporaryDirectory() as td:
        mp3 = Path(td) / "vo.mp3"
        mp3.write_bytes(audio)
        _to_wav(mp3, out_wav)
    return words


_SAPI_PS = r"""
Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
if ($env:CLIPBOT_VOICE) { try { $s.SelectVoice($env:CLIPBOT_VOICE) } catch { } }
$s.Rate = [int]$env:CLIPBOT_RATE
$s.SetOutputToWaveFile($env:CLIPBOT_OUT)
$s.Speak([IO.File]::ReadAllText($env:CLIPBOT_TEXT, [Text.Encoding]::UTF8))
$s.Dispose()
"""


def _sapi(text: str, voice: str, rate: str, out_wav: Path) -> None:
    if sys.platform != "win32":
        raise TTSError("the sapi engine only works on Windows")
    with tempfile.TemporaryDirectory() as td:
        txt, raw = Path(td) / "t.txt", Path(td) / "raw.wav"
        txt.write_text(text, encoding="utf-8")
        sapi_rate = max(-10, min(10, round((_rate_factor(rate) - 1.0) * 10)))
        env = {
            **os.environ,
            "CLIPBOT_TEXT": str(txt),
            "CLIPBOT_OUT": str(raw),
            "CLIPBOT_RATE": str(sapi_rate),
            # Edge voice names (en-US-...) aren't SAPI voices; fall back to the default voice.
            "CLIPBOT_VOICE": "" if re.match(r"^[a-z]{2}-[A-Z]{2}-", voice) else voice,
        }
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", _SAPI_PS],
            env=env, capture_output=True, text=True,
        )
        if proc.returncode != 0 or not raw.exists():
            raise TTSError(f"Windows speech failed: {proc.stderr.strip()}")
        _to_wav(raw, out_wav)


def _piper(text: str, model: str, rate: str, out_wav: Path) -> None:
    exe = shutil.which("piper")
    if not exe:
        raise TTSError("piper not found on PATH; see docs/WINDOWS_SETUP.md (optional offline voice)")
    if not Path(model).exists():
        raise TTSError(f"piper needs 'voice' set to a .onnx model file; not found: {model}")
    with tempfile.TemporaryDirectory() as td:
        raw = Path(td) / "raw.wav"
        length_scale = 1.0 / max(0.3, _rate_factor(rate))
        proc = subprocess.run(
            [exe, "--model", model, "--output_file", str(raw), "--length_scale", f"{length_scale:.3f}"],
            input=text, capture_output=True, text=True, encoding="utf-8",
        )
        if proc.returncode != 0 or not raw.exists():
            raise TTSError(f"piper failed: {proc.stderr.strip()[-500:]}")
        _to_wav(raw, out_wav)


def _silent(text: str, rate: str, out_wav: Path) -> None:
    dur = estimate_seconds(text, rate)
    ffmpeg.run(["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-t", f"{dur:.3f}", "-c:a", "pcm_s16le", str(out_wav)])


def _whisper_words(wav: Path) -> list[Word] | None:
    try:
        from faster_whisper import WhisperModel  # type: ignore
    except ImportError:
        return None
    model = WhisperModel("base.en", device="cpu", compute_type="int8")
    segments, _ = model.transcribe(str(wav), word_timestamps=True, language="en")
    words = [Word(w.word.strip(), w.start, w.end) for s in segments for w in (s.words or [])]
    return words or None


def _norm(token: str) -> str:
    return re.sub(r"[^a-z0-9]", "", token.lower())


def _realign(script_tokens: list[str], timed: list[Word]) -> list[Word]:
    """Keep the script's spelling (for captions) but use the engine's timings.

    Engines and whisper can split, merge or drop words ("GTA 6" vs "GTA6",
    "10" vs "ten"), so match the two word lists and interpolate any script
    words that didn't match between their matched neighbours.
    """
    if not timed or not script_tokens:
        return []
    a = [_norm(t) for t in script_tokens]
    b = [_norm(w.text) for w in timed]
    times: list[tuple[float, float] | None] = [None] * len(a)
    for blk in difflib.SequenceMatcher(None, a, b, autojunk=False).get_matching_blocks():
        for k in range(blk.size):
            w = timed[blk.b + k]
            times[blk.a + k] = (w.start, w.end)

    # Fill gaps: spread unmatched words between the previous and next known times.
    out: list[Word] = []
    i = 0
    span_start, span_end = timed[0].start, timed[-1].end
    while i < len(a):
        if times[i] is not None:
            out.append(Word(script_tokens[i], *times[i]))
            i += 1
            continue
        j = i
        while j < len(a) and times[j] is None:
            j += 1
        lo = out[-1].end if out else span_start
        hi = times[j][0] if j < len(a) else span_end
        if hi <= lo:
            hi = lo + 0.08 * (j - i)
        est = estimate_words(" ".join(script_tokens[i:j]), hi - lo, lead=0.0, tail=0.0)
        out += [Word(w.text, lo + w.start, lo + w.end) for w in est]
        i = j
    return out


# ---------------------------------------------------------------- public


def synthesize(
    text: str,
    cache_dir: Path,
    engine: str = "edge",
    voice: str = "en-US-AndrewNeural",
    rate: str = "+0%",
    pitch: str = "+0Hz",
    align: str = "auto",
) -> Speech:
    """Speak `text` to a 48 kHz stereo WAV, with per-word timings. Cached."""
    if engine not in ENGINES:
        raise TTSError(f"unknown tts engine '{engine}'; use one of {', '.join(ENGINES)}")
    cache_dir.mkdir(parents=True, exist_ok=True)
    key = _cache_key(engine, voice, rate, pitch, align, text)
    wav = cache_dir / f"vo_{key}.wav"
    meta = cache_dir / f"vo_{key}.json"
    if wav.exists() and meta.exists():
        m = json.loads(meta.read_text(encoding="utf-8"))
        return Speech(wav, m["duration"], [Word(**w) for w in m["words"]])

    tmp = wav.with_suffix(".tmp.wav")
    timed: list[Word] = []
    if engine == "edge":
        timed = _edge(text, voice, rate, pitch, tmp)
    elif engine == "sapi":
        _sapi(text, voice, rate, tmp)
    elif engine == "piper":
        _piper(text, voice, rate, tmp)
    else:
        _silent(text, rate, tmp)
    tmp.replace(wav)
    duration = ffmpeg.media_duration(wav)

    if not timed and engine != "silent" and align in ("auto", "whisper"):
        timed = _whisper_words(wav) or []
        if not timed and align == "whisper":
            raise TTSError("align: whisper requested but faster-whisper is not installed")
    tokens = tokenize(text)
    words = _realign(tokens, timed) if timed else estimate_words(text, duration)

    meta.write_text(
        json.dumps({"duration": duration, "words": [asdict(w) for w in words]}, indent=1),
        encoding="utf-8",
    )
    return Speech(wav, duration, words)


def list_edge_voices(prefix: str = "en-") -> list[dict]:
    import edge_tts

    voices = asyncio.run(edge_tts.list_voices())
    return [v for v in voices if v["ShortName"].startswith(prefix)]
