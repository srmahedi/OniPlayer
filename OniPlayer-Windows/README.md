# OniPlayer Windows

<p align="center">
  <strong>A minimal, keyboard-and-mouse-centric desktop media player built using PyQt6 and libvlc.</strong>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Platform-Windows-blue?style=for-the-badge&logo=data:image/svg%2bxml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCA4OCA4OCI+PHBhdGggZmlsbD0iI2ZmZiIgZD0iTTAgMTIuNDAybDM1LjY4Ny00Ljg2LjAxNiAzNC44ODEtMzUuNjcwLjE5M3ptMzUuNjcgMzMuMzI3bC4wMjggMzQuOTUzLTM1LjY5OC00LjkwNC0uMDAzLTMwLjIyMnptNC43NzMtMzguOTIybDQ3LjU1Ny02LjgwN3Y0MS4xM2wtNDcuNTU3LjI3MnptNDcuNTU3IDM4LjM1OXY0MS4yMjlsLTQ3LjU1Ny02LjY4NS4wMTYtMzQuNzIxeiIvPjwvc3ZnPg==" alt="Platform Badge" />
  <img src="https://img.shields.io/badge/Python-3.10%2B-blue?style=for-the-badge&logo=python&logoColor=white" alt="Python Badge" />
  <img src="https://img.shields.io/badge/Core%20Engine-LibVLC%203.0.21-orange?style=for-the-badge&logo=vlc&logoColor=white" alt="VLC Badge" />
  <img src="https://img.shields.io/badge/GUI-PyQt6-darkgreen?style=for-the-badge" alt="GUI Badge" />
</p>


OniPlayer is a minimal, keyboard-and-mouse-centric desktop media player built using **PyQt6** and **libvlc** (`python-vlc`). Engineered for high-performance and a distraction-free viewing experience, it boots directly into a immersive fullscreen, auto-hides the mouse cursor over video playback, and packs incredibly powerful mouse gestures and keyboard shortcuts.

---

## Features

### Media Playback
* **Universal Format Support:** Decodes all major formats (MP4, MKV, AVI, MOV, WMV) natively using high-performance hardware acceleration via VLC.
* **Smart Playlists:** Drop a file or directory into the player to automatically queue up all video files in that directory.
* **Auto-Advance:** Seamlessly moves to the next video when the current one finishes.

### Advanced Audio Control
* **Track Switching:** Supports switching between multiple audio streams (multi-language tracks) inside the container.
* **Smart Volume:** Smooth scaling with an elegant translucent on-screen display (OSD). Default volume is set to a comfortable `60`.
* **Quick Mute:** Instantly toggle sound with a simple keyboard shortcut or clicking the volume icon.

### Complete Subtitle System
* **Auto-Discovery:** Automatically detects and loads external subtitle files (SRT, ASS) with matching filenames.
* **Track Selection:** Easily switch between multiple subtitle tracks or disable subtitles entirely.
* **Subtitle Sync:** Dynamically delay or advance subtitle rendering to match the audio.

### Immersive User Interface
* **Distraction-Free Design:** Modern dark theme with minimalist styling. Fullscreen by default.
* **Ultra-Hidden Cursor:** The mouse cursor vanishes automatically over the video area. It instantly reappears when hovering over the timeline, title bar, or when opening the context menu.
* **Stuck-Cursor Prevention:** Leverages an automatic background OS cursor-refresh handler to prevent standard Windows loading spinners from getting stuck on screen.

---

## Controls & Gestures Guide

OniPlayer is designed to be fully controlled via keyboard shortcuts and advanced mouse gestures.

### Keyboard Controls
| Key | Action |
|:---|:---|
| `Space` | Play / Pause |
| `Enter` / `F` | Toggle Fullscreen |
| `Esc` | Exit Fullscreen |
| `Left Arrow` | Seek Backward |
| `Right Arrow` | Seek Forward |
| `Up Arrow` | Volume Up |
| `Down Arrow` | Volume Down |
| `M` | Toggle Mute |
|| `Page Up` | Previous Video in Playlist |
|| `Page Down` | Next Video in Playlist |
| `A` | Cycle to Next Audio Track |
| `S` | Toggle Subtitles On / Off |

### Mouse Gestures & Shortcuts
| Action | Gesture / Input |
|:---|:---|
| **Toggle Play/Pause** | Left Double-Click over Video |
| **Toggle Fullscreen** | Middle-Click |
| **Toggle Subtitles** | Hold Middle-Click (1 second) |
| **Context Menu** | Right-Click |
| **Volume Control** | Scroll Mouse Wheel |
| **Fast Forward / Rewind** | Hold Left-Click + Scroll Mouse Wheel |
| **Switch Audio Track** | Hold Right-Click + Scroll Mouse Wheel |
| **Next Video** | Hold Left-Click + Single-Click Right-Click |
| **Previous Video** | Hold Right-Click + Single-Click Left-Click |
| **Seek Playback** | Click / Drag Timeline |

---

## Getting Started

### Prerequisites
* Windows OS (64-bit)
* Python 3.10+
* Boundled local `libvlc.dll`, `libvlccore.dll`, and the `plugins` directory (bundled for direct executable compile).

### Setting Up Development Environment


1. **Install Dependencies:**
   ```powershell
   pip install -r requirements.txt
   ```

2. **Run OniPlayer:**
   ```powershell
   python main.py
   ```

---

## Packaging and Distribution

### 1. Compile to Executable (`PyInstaller`)
To bundle the application into exe::
```powershell
pyinstaller --noconfirm --onedir --windowed --icon "icon.ico" --name "OniPlayer" --version-file "file_version_info.txt" main.py
```

### 2. Create Installer (`Inno Setup`)
Compile the `setup.iss` script in Inno Setup to package your PyInstaller distribution into a single installer executable (`OniPlayer_x64.exe`).

---
