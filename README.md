<div align="center">

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="src/vertex/assets/logo/light/vertex-stacked-light.png">
  <img src="src/vertex/assets/logo/dark/vertex-stacked-dark.png" alt="Vertex" width="200">
</picture>

# **BIG DISCLAIMER AND SOME PERSONAL WORDS**
This entire project is vibe coded. I used Claude Pro to make this entire thing.

I know AI is arse.

I fully acknowledge the ethical, ecological and moral implications that using LLMs bring along with them. Let alone the copyright side of things. 

I know I was using the hard work and the combined 10s of thousands of hours of learning of every **real** and **skilled** developer that is out there. But I was in need of a solution to the only "gripe" I have using Linux. 

I did my switch from Windows to Linux. Getting everything working was pretty easy. Even multi-audio track clip recording was super easy due to GPU Screenrecorder's existence. 

On Windows, I used SteelSeries Moments to capture my gaming clips. Showing them to my friends is super easy. You can adjust the volume or mute audio tracks entirely. I really loved that. You can trim them, and easily export them to discord. Convenient.

But for some reason, no video player supports multi-audio-track playback out of the box. I did some "hacky" things to force my video player to play all audiotracks at once. It worked well.... But I couldnt easily turn down my microphone volume on one audio track, while leaving chat and game sounds at the same volume. So I tried using open source video editors, but I just couldnt get a solid workflow going. It all felt like so much effort to *quickly* edit (trim and adjust volumes per audio track) and share clips to my friends. 

With ongoing microphone issues, I have many clips where my microphone is way too loud. I did eventually fix it, but my historical clips are barely usable due to that fact. 

I use this project for myself. I have about 600 clips that I successfully imported into it. The performance is good. Editing, trimming and sharing works just like it does on the Windows counterpart. 



Talking to one of my friends who is a software developer. He told me the codebase is complete trash. But I should still put it on a Github repo under the MIT license. 

This will most likely be the only code, I will ever publicly share. 

If people are seeing the niche that it tries to cover, take this "project", re-write it, improve it. 

This intro section is written by me, the human behind it. The following showcase of this "project" was also written by AI. I did edit some parts to be more readable. 

**One final note:**

 If you have a gripe with people like me, who vibe code such a thing, thats completely okay. Just dont seek me out and harrass me.

---

**Game clips for Linux and Windows, plus Sonar-style audio on Linux.**
A re-implementation of SteelSeries Moments and Sonar.

Save the last minute of a game with one key, trim it, turn your mic down and
send it to your friends.

</div>

<p align="center">
  <img src="docs/screenshots/home.png" alt="Vertex's Home page" width="900">
</p>

> The screenshots show a made-up demo library.

Vertex never changes your recordings. No network access, no telemetry, no
account.

---

## Contents

- [Library](#library)
- [Editor and export](#editor-and-export)
- [Recording](#recording)
- [Sonar (Linux)](#sonar-linux)
- [Settings](#settings)
- [Linux and Windows](#linux-and-windows)
- [Install](#install)
- [Uninstall](#uninstall)
- [Commands](#commands)
- [Your data](#your-data)
- [Thanks](#thanks)

---

## Library

<p align="center">
  <img src="docs/screenshots/library.png" alt="The library" width="900">
</p>

- All your clips, with previews.
- Filter by game, person or favorites. Search, tag and rename.
- Select several clips to tag, favorite, export or delete them at once.
- Right-click a game to rename it. Its clips and new clips get the new name.

## Editor and export

<table>
<tr>
<td width="60%"><img src="docs/screenshots/editor.png" alt="The clip editor"></td>
<td width="40%"><img src="docs/screenshots/export.png" alt="The export dialog"></td>
</tr>
</table>

- A volume slider per audio track.
- Trim without losing quality.
- **Share** sizes the clip for Discord and copies it. Paste or drag it into a chat.
- **Export** saves it to your Exports folder.
- Playback volume up to 300%, only for watching.

## Recording

<table>
<tr>
<td width="50%"><img src="docs/screenshots/settings-recording.png" alt="Recording settings"></td>
<td width="50%"><img src="docs/screenshots/settings-notifications.png" alt="Notification settings"></td>
</tr>
</table>

- The replay buffer keeps the last minute or two.
- Game, chat, media and mic are separate tracks, each with its own device
  and volume.
- New clips are tagged with the game you're playing.
- Recording is optional. Switch it off to only manage the clips you have.
- A sound and a notification over your game when a clip is saved or isn't.
  Each sound can be switched off or swapped for a file of your own.

## Sonar (Linux)

<p align="center">
  <img src="docs/screenshots/sonar.png" alt="The Sonar page" width="900">
</p>

- Separate Game, Chat and Media volumes, and a shared Vertex Mic.
- Apps stay on their channel.
- A priority list picks your headset and mic.
- Recording uses Sonar's channels as its tracks.

## Settings

<p align="center">
  <img src="docs/screenshots/settings-general.png" alt="General settings" width="900">
</p>

- Nine color schemes.
- Import from Moments or Medal, with a folder per game. Untick folders to
  leave them out.
- Game and date from clip names: pick the app that made them (Medal,
  ShadowPlay, Xbox Game Bar, OBS and more), or teach Vertex your own names.
  Vertex shows what re-reading the names would change before applying it.
- Backups: one file with your settings and library (not the clips). One a
  day, the last five kept. Restore everything or pick single settings.

---

## Linux and Windows

Everything above works on both, except:

| | Linux | Windows 10 and 11 |
|---|---|---|
| Recorder | [GPU Screen Recorder](https://git.dec05eba.com/gpu-screen-recorder/about/) | [OBS Studio](https://obsproject.com/) 30+, run by Vertex in the tray |
| Sonar | Yes (PipeWire or PulseAudio) | No. Use your own virtual devices to split game and chat |
| Game tag for new clips | The app on Sonar's Game channel, or Desktop | The full-screen game, or Desktop |
| Hotkeys | Bind `vertex save-clip` in your desktop's shortcuts | Settings › Shortcuts |
| Notifications over games | With `gpu-screen-recorder-notification` | Yes, except over old exclusive full screen |
| Stream Deck | [StreamController plugin](https://github.com/StellarGalaxyAtlas/vertex-unified-plugin) | No |

---

## Install

> [!CAUTION]
> **These install steps were written by AI and have not been verified.**
> Package names and commands may be wrong for your system. Vertex is mostly
> tested on KDE Plasma (Wayland) with PipeWire; Windows is newer. Read each
> command before you run it, and open an issue if something is wrong.

### Linux

**1. System packages:** Python 3.10+, `pipx`, `ffmpeg`, `libmpv` and
`pactl` (for Sonar). Optional: GPU Screen Recorder (recording) and
`gpu-screen-recorder-notification` (notifications over games).

```bash
# Arch
sudo pacman -S python-pipx ffmpeg mpv libpulse
yay -S gpu-screen-recorder gpu-screen-recorder-notification   # AUR

# Debian / Ubuntu
sudo apt install pipx ffmpeg libmpv2 pulseaudio-utils libxcb-cursor0

# Fedora (ffmpeg from RPM Fusion)
sudo dnf install pipx ffmpeg mpv-libs pulseaudio-utils
```

**2. Vertex:**

```bash
pipx install git+https://github.com/StellarGalaxyAtlas/vertex.git
vertex            # adds itself to your start menu and runs setup
vertex doctor     # checks that everything is in place
```

Flatpak GPU Screen Recorder: set *Settings › Recording › Advanced › Command*
to `flatpak run --command=gpu-screen-recorder com.dec05eba.gpu_screen_recorder`.

### Windows

**1. Programs**, in PowerShell (OBS only for recording):

```powershell
winget install Python.Python.3.13 Git.Git Gyan.FFmpeg OBSProject.OBSStudio
```

- Open OBS once, finish its setup wizard and close it. Vertex starts it from
  then on.
- libmpv: download an `mpv-dev-x86_64` archive (not `-v3`) from
  [mpv's Windows builds](https://sourceforge.net/projects/mpv-player-windows/files/libmpv/),
  put `libmpv-2.dll` in a folder such as `C:\Users\<you>\mpv`, and add that
  folder to your `PATH`.

**2. Vertex**, in a new PowerShell window:

```powershell
py -m pip install --user pipx
py -m pipx ensurepath   # then open a new PowerShell window
pipx install git+https://github.com/StellarGalaxyAtlas/vertex.git
vertex            # adds itself to the Start menu and runs setup
vertex doctor     # checks that everything is in place
```

### Update

Run the same `pipx install` line with `--force`, then quit Vertex from the
tray and open it again.

---

## Uninstall

1. Linux only: run `vertex sonar down` while Vertex is open, to remove
   Sonar's virtual devices.
2. Quit Vertex from the tray.
3. Run:

   ```bash
   vertex uninstall-desktop     # removes the menu entry and autostart
   pipx uninstall vertex-clips
   ```

Your clips stay. To remove your settings, library and logs too, delete the
folders under [Your data](#your-data). On Windows, Vertex's profile and scene
collection stay in OBS; delete them there if you like.

---

## Commands

Use these in mouse or keyboard software, a Stream Deck or a script.
*Settings › Shortcuts* lists them ready to copy. On KDE: System Settings ›
Keyboard › Shortcuts › Add New › Command or Script.

```
vertex save-clip [--last N]       save the replay buffer (or its last N seconds)
vertex replay start|stop|toggle
vertex show | state | watch | doctor
vertex backup export [FILE] | import FILE [--only settings|library]

# Linux, with Sonar
vertex volume game|chat|media|mic up|down|0-100
vertex mute game|chat|media|mic
vertex device next|previous [mic]
vertex sonar up|down
```

The tray menu shows Vertex, saves clips and starts the replay buffer. On
Linux it also switches Sonar's output and mic.

---

## Your data

| What | Linux | Windows |
|---|---|---|
| Settings | `~/.config/vertex/config.json` | `%APPDATA%\Vertex\config.json` |
| Library and backups | `~/.local/share/vertex/` | `%LOCALAPPDATA%\Vertex\Library\` |
| Logs | `~/.local/state/vertex/logs/` | `%LOCALAPPDATA%\Vertex\State\logs\` |
| Thumbnails (safe to delete) | `~/.cache/vertex/` | `%LOCALAPPDATA%\Vertex\Cache\` |

Logs are small text files for troubleshooting. Turn them off with *Keep logs*
in Settings.

Developers: [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md).

---

## Thanks

Some more personal words from the human behind the scene. This "project" would have never come alive without projects like the following. I am grateful that there are passionate people out there that create and maintain libraries like this. I am so unbelievably thankful for the open source community. 

- **[GPU Screen Recorder](https://git.dec05eba.com/gpu-screen-recorder/about/)** by dec05eba (GPL-3.0-only): recording on Linux.
- **[OBS Studio](https://obsproject.com/)** (GPL-2.0-or-later): recording on Windows.
- **[mpv](https://mpv.io/)** (GPLv2+ / LGPLv2.1+): playback, and live mixing of several audio tracks.
- **[FFmpeg](https://ffmpeg.org/)** (LGPLv2.1+ / GPLv2+): thumbnails, previews, waveforms, trims and exports.
- **[x264](https://www.videolan.org/developers/x264.html)** (GPLv2+): size-capped exports.
- **[PipeWire](https://pipewire.org/)** and **[PulseAudio](https://www.freedesktop.org/wiki/Software/PulseAudio/)**: the building blocks of Sonar.
- **[Qt](https://www.qt.io/)** (LGPLv3) and **[PySide6](https://doc.qt.io/qtforpython-6/)** (LGPLv3): the interface.
- **[SQLite](https://sqlite.org/)** (public domain): the library.
- **[Python](https://www.python.org/)** (PSF License).
- **[python-mpv](https://github.com/jaseg/python-mpv)** by jaseg (GPLv2+ / LGPLv2.1+): mpv inside the Qt window.
- **[Send2Trash](https://github.com/arsenetar/send2trash)** by Virgil Dupras and Andrew Senetar (BSD-3-Clause): deleting to the Trash.
- **SteelSeries Moments** and **SteelSeries Sonar**: the apps Vertex re-implements.
- **[freedesktop.org](https://www.freedesktop.org/)**: the standards for folders, menu entries and the Trash.

---

## License

[MIT](LICENSE).
