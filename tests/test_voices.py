"""Real voice engines. The Edge test needs internet; it runs when CLIPBOT_NETWORK_TESTS=1 (CI)."""

import os
import shutil
import sys

import pytest

from clipbot.tts import synthesize

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")


@needs_ffmpeg
@pytest.mark.skipif(os.environ.get("CLIPBOT_NETWORK_TESTS") != "1", reason="set CLIPBOT_NETWORK_TESTS=1")
def test_edge_voice_with_word_timings(tmp_path):
    text = "In GTA 6, witnesses remember your outfit."
    sp = synthesize(text, tmp_path, "edge", "en-US-AndrewNeural", "+8%")
    assert 1.0 < sp.duration < 8.0
    assert [w.text for w in sp.words] == text.split()
    assert all(0 <= w.start < w.end <= sp.duration + 0.2 for w in sp.words)
    assert sp.words == sorted(sp.words, key=lambda w: w.start)
    # Cached second call returns the same thing without regenerating.
    again = synthesize(text, tmp_path, "edge", "en-US-AndrewNeural", "+8%")
    assert again.wav == sp.wav and again.words == sp.words


@needs_ffmpeg
@pytest.mark.skipif(sys.platform != "win32", reason="Windows only")
def test_windows_sapi_voice(tmp_path):
    sp = synthesize("Testing the built in Windows voice.", tmp_path, "sapi", "", "+0%", align="estimate")
    assert sp.duration > 1.0
    assert len(sp.words) == 6
