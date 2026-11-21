# SmartCut

**English** | [Português (BR)](README.pt-BR.md)

An automated video and audio editing tool for **Linux** powered by **FFmpeg** (`silencedetect`). It automatically detects and removes pauses and silences, imports and exports standardized **FCPXML** and **EDL** timelines, and renders quick previews or full cuts directly to **MP4**. Includes a real-time bilingual GUI (**English US** / **Português BR**), **Dark** and **Light** themes, and a full Command-Line Interface (CLI).

---

## Features

- **Real-Time Bilingual Interface:** Switch instantly between **English (US)** and **Português (BR)** from the top bar, translating menus, parameters, dialogs, and execution logs without restarting the app.
- **Dark & Light Themes:** Toggle between **Dark** and **Light** modes with one click. Language and theme preferences are automatically saved to `~/.config/smartcut/settings.json`.
- **Original Input & Customizable Output:** Load any input video or audio file (with automatic detection of resolution, FPS, and duration) and freely choose the destination folder and base filename for exported files.
- **Fine-Tuned Silence Detection:** Adjust decibel threshold (`dB`), minimum silence duration, speech padding, and merge gap, or apply built-in presets (**Dynamic** and **Narration**).
- **Quick Preview (30s) or Full Video:** Test your cut pacing on the first 30 seconds before processing the entire file.
- **FCPXML 1.9, EDL CMX 3600 & JSONL Interchange:**
  - **Export:** Generates `.fcpxml` (frame-aligned rational timestamps), `.edl` (SMPTE `HH:MM:SS:FF` timecodes based on actual video FPS), and `.jsonl`.
  - **Import:** Loads existing `.fcpxml` or `.edl` timelines to convert between formats or render the cut media directly.
- **Direct FFmpeg Rendering:** Exports cut video in `H.264 / AAC` (`libx264`, `-crf 20`) or audio-only in `.m4a`.
- **Command-Line Interface (CLI):** Full terminal automation with selectable log language (`--lang en` or `--lang pt`).

---

## Prerequisites

SmartCut uses only the **Python 3.9+ standard library** (zero external `pip` packages required) and relies on standard system utilities:

- **Python 3.9 or higher**
- **FFmpeg and FFprobe** available in your `PATH`
- **Tkinter** (required only for the graphical interface)

### Installing System Dependencies on Linux

- **Ubuntu / Debian / Linux Mint:**
  ```bash
  sudo apt update && sudo apt install -y python3 python3-tk ffmpeg
  ```
- **Arch Linux / Manjaro / BigLinux:**
  ```bash
  sudo pacman -S --needed python tk ffmpeg
  ```

---

## Installation

1. **Clone the repository and make the script executable:**
   ```bash
   git clone [https://github.com/SilverKms21/SmartCut-Open.git](https://github.com/SilverKms21/SmartCut-Open.git)
   cd SmartCut-Open
   chmod +x smartcut.py
   ```

2. **(Optional) Build a standalone Linux executable locally with PyInstaller:**

   Building locally ensures full instruction-set compatibility with your CPU:
   ```bash
   python3 -m venv .venv-build
   .venv-build/bin/pip install --upgrade pip pyinstaller
   .venv-build/bin/pyinstaller --onefile --windowed --name smartcut --hidden-import tkinter smartcut.py
   ```

   Then choose where to place the compiled binary:

   - **Option A — Keep the executable in the same folder as `smartcut.py` (portable):**
     ```bash
     cp dist/smartcut ./smartcut
     rm -rf build dist smartcut.spec .venv-build
     ```
     *(Run later with: `./smartcut`)*

   - **Option B — Install for your user (`~/.local/bin`):**
     ```bash
     mkdir -p ~/.local/bin && cp dist/smartcut ~/.local/bin/smartcut
     rm -rf build dist smartcut.spec .venv-build
     ```
     *(Run from anywhere with: `smartcut`)*

---

## Usage

### 1. Graphical User Interface (GUI)

Run without arguments to launch the main window:

```bash
./smartcut.py
```

1. **Language & Theme (Top Bar):** Choose **English (US)** or **Português (BR)** from the dropdown menu and switch between **Dark** and **Light** themes.
2. **Original Input & Output File:** Click **Browse Input...** to load your raw video/audio and set the destination using **Save As...** or **Folder...** (or load an existing timeline via **Import FCPXML / EDL...**).
3. **Auto-Cut Parameters:** Fine-tune the sliders or click **Preset: Dynamic** / **Preset: Narration**.
4. **Scope & Export Formats:** Choose **First 30s (Quick preview)** or **Full video**, check your desired output formats (`.mp4`, `.fcpxml`, `.edl`, `.jsonl`), and click **Run**.

---

### 2. Command-Line Interface (CLI)

Passing an input media or timeline path runs SmartCut directly in the terminal without opening a GUI window:

- **Generate a 30-second preview with MP4, FCPXML, and EDL:**
  ```bash
  ./smartcut.py input.mp4 --preview-30s --render-mp4 --lang en
  ```

- **Process the full video with custom parameters and output path:**
  ```bash
  ./smartcut.py input.mp4 \
    -o ~/Videos/edited/final_video.mp4 \
    --lang en \
    --threshold -34 \
    --min-silence 0.40 \
    --padding 0.12 \
    --merge-gap 0.15 \
    --render-mp4
  ```

- **Import an `.edl` timeline and export `.fcpxml` + rendered MP4:**
  ```bash
  ./smartcut.py --import-timeline cut.edl -o ~/Videos/edited/ --render-mp4 --lang en
  ```

### CLI Options

| Flag | Default | Description |
| :--- | :--- | :--- |
| `-o`, `--output PATH` | Input folder | Set output folder or base filename |
| `--gui` | — | Force launch the graphical interface |
| `--lang {pt,en}` | `pt` | Set terminal log language (`pt` or `en`) |
| `--preview-30s` | `False` | Limit analysis and rendering to the first 30 seconds |
| `--max-duration N` | `None` | Limit processing to the first `N` seconds |
| `--import-timeline FILE` | `None` | Import cuts from an `.fcpxml` or `.edl` file |
| `--threshold DB` | `-32.0` | Volume threshold below which audio is treated as silence |
| `--min-silence SEC` | `0.45` | Minimum silence duration required to trigger a cut |
| `--padding SEC` | `0.12` | Safety margin kept before and after speech |
| `--min-clip SEC` | `0.25` | Minimum duration of a kept speech segment |
| `--merge-gap SEC` | `0.15` | Merge speech segments separated by gaps shorter than `SEC` |
| `--render-mp4` | `False` | Render cut `.mp4` (or `.m4a`) via FFmpeg |
| `--no-fcpxml` / `--no-edl` | `False` | Disable exporting the respective timeline format |
| `--jsonl FILE` | `None` | Export cut list to a `.jsonl` file |

---

## Generated Files & Configuration

- **UI Preferences:** Automatically saved to `~/.config/smartcut/settings.json`.
- **Default Outputs** (when `-o` / `--output` is omitted):
  - **Preview (30s):** `<name>_preview30s.mp4`, `<name>_preview30s.fcpxml`, `<name>_preview30s.edl`
  - **Full Video:** `<name>_smartcut.mp4`, `<name>_smartcut.fcpxml`, `<name>_smartcut.edl`
  - **Imported Timeline:** `<name>_imported.mp4`, `<name>_imported.fcpxml`, `<name>_imported.edl`

---

## License

Distributed under the **MIT** License.
