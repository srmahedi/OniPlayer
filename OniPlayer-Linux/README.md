# OniPlayer Linux

<p align="center">
  <strong>A minimal, keyboard-and-mouse-centric desktop media player built using PyQt6 and libvlc for Linux.</strong>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Platform-Arch%20Linux-blue?style=for-the-badge&logo=archlinux&logoColor=white" alt="Platform Badge" />
  <img src="https://img.shields.io/badge/Python-3.10%2B-blue?style=for-the-badge&logo=python&logoColor=white" alt="Python Badge" />
  <img src="https://img.shields.io/badge/GUI-PyQt6-darkgreen?style=for-the-badge" alt="GUI Badge" />
  <img src="https://img.shields.io/badge/Core%20Engine-LibVLC%203.0.23-orange?style=for-the-badge&logo=vlc&logoColor=white" alt="VLC Badge" />
  <img src="https://img.shields.io/badge/Graphics-X11%20%2F%20Wayland-orange?style=for-the-badge" alt="Graphics Badge" />
</p>


OniPlayer is a minimal, keyboard-and-mouse-centric desktop media player built using **PyQt6** and **libvlc** (`python-vlc`). Engineered for high-performance and a distraction-free viewing experience, it boots directly into a immersive fullscreen, auto-hides the mouse cursor over video playback, and packs incredibly powerful mouse gestures and keyboard shortcuts.

**Designed specifically for Arch Linux and its derivatives**, OniPlayer Linux includes a custom build process that compiles VLC from source and bundles the necessary libraries for optimal performance and compatibility.

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

---

## Architecture & VLC Engine

OniPlayer Linux uses a custom-built VLC engine for optimal performance and compatibility:

### Custom VLC Build Process
The `libvlc.sh` script builds VLC 3.0.23 from source with these specific configurations:
- **Shared libraries only** (`--enable-shared --disable-static`) for efficient bundling
- **VLC UI disabled** (`--disable-vlc --disable-qt --disable-skins2`) since OniPlayer provides its own UI
- **GStreamer decoder disabled** (`--disable-gst-decode`) to rely on VLC's native decoders
- **Prefix set to `/usr/local`** for standard system integration

### Engine Extraction
The `get_engine.py` script automatically extracts the built VLC components:
- **Core libraries:** `libvlc.so.5` and `libvlccore.so.9`
- **Plugin modules:** All compiled `.so` plugin files from the modules directory
- **Output:** Organized into `vlc_engine/lib/` and `vlc_engine/plugins/`

### Runtime Configuration
The application sets up the VLC environment at runtime:
- `VLC_PLUGIN_PATH`: Points to the bundled plugins directory
- `LD_LIBRARY_PATH`: Includes the bundled lib directory for library resolution
- `QT_QPA_PLATFORM=xcb`: Forces X11 backend for VLC embedding compatibility on Wayland

This approach ensures consistent behavior across different Linux distributions while maintaining the performance benefits of a native VLC build.

---

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
| `Page Up` | Previous Video in Playlist |
| `Page Down` | Next Video in Playlist |
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
* **Arch Linux** or derivative (Manjaro, EndeavourOS, etc.)
* **Desktop Environment:** Any major DE (GNOME, KDE Plasma, XFCE, i3, etc.)
* **Graphics Stack:** X11 or Wayland (automatically uses XWayland for VLC embedding on Wayland)
* **Build Tools:** GCC, make, automake, autoconf, libtool, pkg-config
* **Python 3.10+**

### Setting Up Development Environment

1. **Install build dependencies:**
   ```bash
   sudo pacman -S --needed base-devel git libtool automake autoconf pkgconf gettext flex bison lua ffmpeg
   ```

2. **Build VLC engine from source:**
   The included `libvlc.sh` script will automatically compile VLC 3.0.23 and extract the necessary libraries:
   ```bash
   chmod +x libvlc.sh
   ./libvlc.sh
   ```
   This process:
   - Clones VLC 3.0.23 from the official VideoLAN repository
   - Configures and builds it with optimal settings for OniPlayer
   - Extracts libvlc, libvlccore, and all plugin modules
   - Places them in the `vlc_engine/` directory for bundling

3. **Install Python dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Run OniPlayer:**
   ```bash
   python main.py
   ```

### System-Wide Installation

For a complete system-wide installation available to all users, use the provided installation script:

```bash
chmod +x install.sh
./install.sh
```

**Important:** The installation script must be run **after** completing the VLC engine build with `libvlc.sh`.

The `install.sh` script performs the following:
- Creates a Python virtual environment and installs dependencies
- Builds the application using PyInstaller as a single executable
- Installs the VLC engine to `/usr/local/lib/vlc_engine/` (system-wide access)
- Installs the compiled binary to `/usr/local/bin/oniplayer`
- Sets up proper permissions for system-wide access
- Creates a desktop entry for application menu integration
- Installs the application icon

After installation, OniPlayer can be launched from anywhere by running `oniplayer` or through the desktop application menu.

### Graphics Stack Compatibility

OniPlayer Linux is designed to work with both X11 and Wayland:

* **X11:** Native support with direct VLC embedding
* **Wayland:** Automatically uses XWayland backend for VLC embedding (`QT_QPA_PLATFORM=xcb`) to ensure compatibility while maintaining the Wayland desktop experience

The application detects your environment and configures itself accordingly.

---

## Packaging and Distribution

### Build VLC Engine
First, ensure the VLC engine is built and available:
```bash
./libvlc.sh
```

### Compile to Executable (`PyInstaller`)
To bundle the application into a standalone binary:
```bash
pyinstaller --noconfirm --onefile --windowed --name "oniplayer" main.py
```

The compiled application will be in the `dist/oniplayer` directory. The bundled VLC engine (`vlc_engine/`) will be included automatically.

### System Integration
For system-wide installation, you can create a desktop entry:
```bash
sudo cp dist/OniPlayer/OniPlayer /usr/local/bin/
sudo cp icon.ico /usr/share/icons/
```

Create `/usr/share/applications/oniplayer.desktop`:
```ini
[Desktop Entry]
Name=OniPlayer
Comment=Minimal keyboard-and-mouse-centric media player
Exec=/usr/local/bin/OniPlayer
Icon=/usr/share/icons/icon.ico
Terminal=false
Type=Application
Categories=AudioVideo;Player;
```

---
