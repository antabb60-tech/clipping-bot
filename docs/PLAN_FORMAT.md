# Edit plan format

One YAML file = one video idea. It lists the footage segments, the voiceover
line for each one, any on-screen text, and which segments go into each
platform's cut. Claude writes these; you fill in or fix the file names and
timestamps after recording.

Start a new one with `clipbot new plans/my-idea` or copy
[`examples/witness-memory.yaml`](../examples/witness-memory.yaml).

## Top level

| Key | Default | What it does |
| --- | --- | --- |
| `title` | file name | Name of the idea. Also used for output file names. |
| `slug` | from title | Override the output file name. |
| `footage_dir` | `.` | Folder with the recordings, relative to the plan file. Use `../footage` for plans in `plans/`. |
| `voice` | `en-US-AndrewNeural` | Voice name. `clipbot voices` lists the free Edge voices. For `piper` this is the path to a `.onnx` model. |
| `rate` | `+8%` | Speaking speed. `+10%` is a little faster, `-5%` slower. |
| `pitch` | `+0Hz` | Voice pitch. |
| `tts` | `edge` | Voice engine: `edge` (free, online, best), `sapi` (Windows built-in, offline), `piper` (offline neural), `silent` (no voice, for timing previews). |
| `hook` | none | Big text at the top of the screen from the very first frame. Keep it under ~45 characters. |
| `hook_duration` | `2.0` | Seconds the hook stays up. |
| `defaults` | none | Any segment key here applies to every segment unless the segment sets it. |
| `captions` | see below | Caption style, or `false` to turn captions off. |
| `music` | none | Optional background music file (loops). Only use music you have the rights to. |
| `music_volume` | `0.12` | Music level before loudness normalisation. |
| `loudness` | `-14` | Final loudness in LUFS. -14 is what TikTok, YouTube and X normalise to. |

## Segments

```yaml
segments:
  - id: report                 # short name used in the platform lists
    file: witness_run1.mp4     # inside footage_dir
    start: "0:45"              # SS, MM:SS or HH:MM:SS, decimals ok ("1:02.5")
    end: "0:53"
    vo: "Ten seconds later, the police description said red jacket."
    text: "THEY DESCRIBED THE JACKET"     # optional label under the hook area
    crop: crop                 # blur (default) or crop
    focus: 0.5                 # crop/zoom position: 0 = left edge, 1 = right edge
    zoom: 1.0                  # 1.0-3.0; makes the picture bigger
```

All segment keys:

| Key | Default | What it does |
| --- | --- | --- |
| `id` | `s1`, `s2`... | Name used by the `platforms` lists. |
| `file`, `start`, `end` | required | Which part of which recording to use. |
| `vo` | none | Voiceover line for this segment. Leave it out for a beat with only game audio. |
| `vo_delay` | `0.15` | Seconds into the segment before the line starts. |
| `text` | none | On-screen label. A string shows for the whole segment, or use `{say: "TEXT", start: 1.5, end: 4}` (seconds from the segment start). Can be a list. |
| `crop` | `blur` | `blur`: the full 16:9 picture in the middle over a blurred, zoomed copy (safe, shows everything). `crop`: fill the whole vertical screen by cutting the sides (more immersive, use `focus` to aim). |
| `focus` | `0.5` | Horizontal aim, 0 to 1. Or keyframes for a slow pan: `[[0, 0.3], [4, 0.7]]` means "at 0s aim at 0.3, at 4s aim at 0.7". |
| `zoom` | `1.0` | In `blur` mode makes the middle picture bigger (sides are cut); in `crop` mode zooms in further. |
| `speed` | `1.0` | 0.5 to 2.0. Speeds up or slows down footage and game audio. |
| `game_audio` | `0.30` | Game volume while the voice is talking. |
| `game_audio_gap` | `0.85` | Game volume when the voice isn't talking. Fades smoothly between the two. |
| `extend` | `true` | If the voiceover is longer than the clip, keep using footage past `end`. With `false` (or at the end of a recording) the last frame is held instead. |
| `violent` | `false` | Mark gunfights or explosions. `check` warns if one lands in the first 7 seconds of a Short, because YouTube limits ads on those. |

**Segment length** is the longer of the clip (`end - start`, adjusted for
`speed`) and the voiceover plus a short pause. So you can be loose with
`end`; the tool extends a clip that is too short for its line and tells you.

## Platforms

Each platform gets its own cut, built from a list of segment ids, in order.
Segments can be reused across platforms; shared segments are only rendered once.

```yaml
platforms:
  tiktok:                      # target: over 61s (TikTok Creator Rewards needs > 1 minute)
    segments: [open, crime, report, test, result, catch, outro]
    caption: "Post text"       # written to the .txt next to the video
    hashtags: [gta6, gaming]
  shorts:                      # target: 20-40s
    segments: [open, report, result]
    hook: "Different hook for YouTube"   # optional per-platform hook
    title: "YouTube title"
  x:                           # target: 20-40s
    segments: [open, report, result]
```

A bare list works too: `shorts: [open, report, result]`. If `platforms` is
missing, every platform uses every segment.

`clipbot check plan.yaml` prints each cut's length and warns when a cut is
outside its target. Lengths are estimates until you add `--real`.

## Captions

```yaml
captions:
  font: Arial Black     # any font installed on Windows, or drop a .ttf in fonts/
  size: 84
  color: "#FFFFFF"
  highlight: "#FFE100"  # colour of the word being spoken
  outline: 7
  max_words: 3          # words per caption chunk
  max_chars: 14
  y: 1180               # vertical position (0 = top, 1920 = bottom)
  uppercase: true
```

Captions follow the voiceover word by word. With the `edge` voice the timing
is exact. Other voices are timed with faster-whisper if installed
(`pip install faster-whisper`) and estimated otherwise.

## Layout on screen

The video is 1080x1920. The hook sits near the top (y about 300), labels
below it (y 520), captions at y 1180. All three stay clear of the TikTok and
Shorts buttons on the right and the caption area at the bottom.
