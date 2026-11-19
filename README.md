# clipbot

Turns GTA 6 gameplay recordings plus a short YAML edit plan into finished,
faceless vertical videos for TikTok, YouTube Shorts and X. Runs locally on
Windows and uses only free tools: FFmpeg, Python and the free Microsoft
Edge voices. No paid APIs, no watermark, no uploads. You post by hand.

Each video gets:

* an AI voiceover (free Edge neural voices; offline Windows or Piper voices as a fallback)
* word-by-word animated captions burned in, with the spoken word highlighted
* a hook text overlay from the first frame
* vertical 1080x1920 framing: blur-fill (full picture over a blurred copy) or crop with an aim point and optional slow pans
* game audio that dips under the voice and comes back between lines
* loudness normalised to -14 LUFS (what all three platforms target)
* a separate cut per platform: TikTok over 1 minute, Shorts and X at 20-40 seconds
* a `.txt` next to each video with the caption, hashtags and anything to check before posting

## Quick start (Windows)

1. Download this repo (Code > Download ZIP) and extract it, e.g. to `C:\clipbot`.
2. Double-click `setup.bat`. It installs Python and FFmpeg if needed and checks everything.
3. Put recordings in `footage\` and a plan in `plans\`, then in a terminal in that folder:

```
clipbot check plans\my-idea.yaml
clipbot render plans\my-idea.yaml --preview
clipbot render plans\my-idea.yaml
```

Full guide: [docs/WINDOWS_SETUP.md](docs/WINDOWS_SETUP.md).
Plan reference: [docs/PLAN_FORMAT.md](docs/PLAN_FORMAT.md).

## The workflow

1. Claude researches trends and writes an idea as a plan: hook, voiceover
   lines, which shots to record, and how each platform's cut is put together.
2. You record the shots on Xbox and download them from Google Drive into `footage\`.
3. Fix the `file:`, `start:` and `end:` values in the plan to match what you recorded.
   `clipbot check` tells you each cut's length and anything out of range.
4. `clipbot render --preview` to check timing, then `clipbot render` for the finals.
5. Post from `out\<idea>\`, using the caption in the matching `.txt`.

## A plan in brief

```yaml
title: "GTA 6 witnesses remember your outfit"
footage_dir: ../footage
voice: en-US-AndrewNeural
hook: "GTA 6 cops remember what you WEAR"

segments:
  - id: open
    file: witness_run1.mp4
    start: "0:04"
    end: "0:09"
    vo: "In GTA 6, witnesses actually remember what you were wearing."
    text: "WITNESS SYSTEM"
  - id: report
    file: witness_run1.mp4
    start: "0:45"
    end: "0:53"
    vo: "Ten seconds later, the police description said red jacket."
    crop: crop
    focus: [[0, 0.35], [6, 0.6]]

platforms:
  tiktok: {segments: [open, report, ...], hashtags: [gta6, gaming]}
  shorts: [open, report]
  x: [open, report]
```

See [examples/witness-memory.yaml](examples/witness-memory.yaml) for a full one.

## Commands

| Command | What it does |
| --- | --- |
| `clipbot doctor` | Checks Python, FFmpeg, caption support and the free voice. |
| `clipbot new plans\idea` | Creates a plan from the template. |
| `clipbot probe footage\*.mp4` | Size, fps, length, HDR and audio for recordings. |
| `clipbot check PLAN [--real]` | Validates a plan and shows each cut's timeline and length. |
| `clipbot render PLAN [-p tiktok,shorts,x] [--preview]` | Renders the videos into `out\`. |
| `clipbot voices [en-GB]` | Lists free Edge voices. |

Voiceovers and rendered segments are cached in `out\.cache`, so re-rendering
after a small plan change is quick. Delete that folder to free space.

## Development

```
pip install -e ".[dev]"
pytest
```

Tests render tiny generated clips end to end, so they need FFmpeg on PATH.
GitHub Actions runs them on Windows (including the real Edge and Windows
voices and the setup script) and Linux.
