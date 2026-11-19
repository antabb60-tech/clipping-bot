# Windows setup

Everything here is free. It takes about 10 minutes, mostly downloads.

## 1. Get the code

Easiest: on the GitHub page for this repo click **Code > Download ZIP**,
then extract it somewhere simple like `C:\clipbot`. Avoid OneDrive-synced
folders (Desktop or Documents on many PCs), because syncing big video
files slows everything down.

If you have git: `git clone https://github.com/antabb60-tech/clipping-bot C:\clipbot`.
Then `git pull` gets updates.

## 2. Run the installer

Double-click **`setup.bat`** in that folder. It:

1. Installs Python 3.12 if you don't have it (via winget, built into Windows 10/11).
2. Installs FFmpeg (the free video engine) if you don't have it.
3. Creates a private Python environment in `.venv` and installs clipbot into it.
4. Runs `clipbot doctor` to check everything works, including the free voice.

If it says Python or FFmpeg was installed but "not found yet", close the
window and double-click `setup.bat` again. New programs only show up in
new windows.

You can run `setup.bat` again any time, for example after downloading an update.

## 3. Open a terminal in the folder

In File Explorer, open the clipbot folder, click the address bar, type
`cmd` and press Enter. All commands below are run from there.

```
clipbot doctor
```

Every line should say OK.

## 4. Folders

```
C:\clipbot\
  footage\     your Xbox recordings go here (downloaded from Google Drive)
  plans\       one .yaml plan per video idea (Claude writes these)
  out\         finished videos + post notes appear here
  examples\    a complete example plan
```

When you download several files at once from Google Drive it gives you a
ZIP. Extract it into `footage\`.

## 5. Make videos

```
clipbot probe footage\witness_run1.mp4
clipbot check plans\my-idea.yaml
clipbot render plans\my-idea.yaml --preview
clipbot render plans\my-idea.yaml
```

* `probe` shows a recording's size, length, frame rate and whether it is HDR.
* `check` validates the plan and shows how long each platform cut will be.
  Add `--real` to generate the voiceover first for exact lengths.
* `render --preview` makes a quick low-quality version to check timing.
* `render` makes the final videos: `out\<idea>\<idea>_tiktok.mp4`, `_shorts.mp4`, `_x.mp4`,
  plus a `.txt` per platform with the caption, hashtags and anything to check before posting.
* `-p tiktok` renders just one platform; `-p shorts,x` renders two.

## Xbox capture tips

* **Settings > Preferences > Capture & share**: 1080p SDR game clips are
  smaller and look right everywhere. 4K and HDR clips work too: clipbot
  detects HDR and converts the colours so they don't look washed out.
* `crop` mode fills the tall screen with the middle third of the picture, so
  a 1080p clip gets upscaled and looks softer. If an idea uses a lot of `crop`
  shots, record those in 4K. `blur` mode looks sharp from 1080p.
* Use **Start recording** for longer takes so one file holds a whole
  scenario. Timestamps in plans are from the start of each file.
* Name files to match the plan (for example `witness_run1.mp4`), or edit the
  `file:` lines in the plan to match your names.
* Turn off in-game HUD elements you don't want, and avoid recording
  story cutscenes (no main-story spoilers, and Rockstar disallows posting isolated cutscenes).

## Troubleshooting

| Problem | Fix |
| --- | --- |
| `'clipbot' is not recognized` | Run it from the clipbot folder (it uses `clipbot.cmd`). In PowerShell type `.\clipbot` instead of `clipbot`. If it still fails, run `setup.bat`. |
| `ffmpeg not found` | `winget install Gyan.FFmpeg`, then open a new terminal. |
| `edge-tts failed` | The free Edge voice needs internet. Try again, or add `--tts sapi` to use the offline Windows voice (more robotic). |
| Captions in the wrong font | The default is Arial Black. Put any `.ttf` in `fonts\` and set `captions: {font: "Font Name"}` in the plan. |
| A render fails with "Permission denied" | Close the video if it is open in a player, then run again. |
| Everything is slow | Use `--preview` while adjusting a plan; only do the full render once. Keep footage on an internal drive, not OneDrive. |

## Manual install (no winget)

1. Python 3.12 from https://www.python.org/downloads/ (tick **Add python.exe to PATH**).
2. FFmpeg: download the "full" build ZIP from https://www.gyan.dev/ffmpeg/builds/,
   extract it to `C:\ffmpeg`, and add `C:\ffmpeg\bin` to your PATH
   (Start > "Edit the system environment variables" > Environment Variables > Path > New).
3. Double-click `setup.bat`.

## Optional extras

* **Better caption timing for non-Edge voices**: `.venv\Scripts\pip install faster-whisper`.
* **Offline neural voice (Piper)**: download `piper` for Windows from
  https://github.com/rhasspy/piper/releases, put it on PATH, download a voice
  `.onnx` model, and set `tts: piper` and `voice: C:\path\to\voice.onnx` in the plan.
