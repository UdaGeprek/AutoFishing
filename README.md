# Albion Fishing Bot

External fishing assistant for **Albion Online**: reads the screen with computer vision and sends mouse/keyboard input via WinAPI. Does not inject into the game process.

> **Disclaimer:** Automation may violate Albion Online’s terms of service. This project is for learning (computer vision, input automation). Use on live servers at your own risk.

---

## Features

| Feature | Description |
|--------|-------------|
| Full auto | Cast to water-zone center, watch bobber, hook on bite, play mini-game |
| Assist mode | You cast and hook manually; bot controls the green bar only |
| HSV calibration | Eyedropper from live previews + tolerance sliders |
| Settings profiles | Save / load / delete profiles; factory default if nothing saved |
| Auto bait | Press an action-bar key every N catches |
| Auto food | Press a food key on a timer (minutes) |
| Humanize & watchdog | Random recast delays; force recast when stuck |

**Removed:** audio mode, packet sniff, hybrid, multi-spot, manual cast-point picker (cast always uses **water zone center**).

---

## Requirements

- Windows 10/11  
- Python 3.10+ (3.11 recommended)  
- Albion in windowed or borderless mode (same resolution as calibration)  

---

## Installation

```bash
git clone https://github.com/UdaGeprek/AutoFishing.git
cd AutoFishing2
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

---

## Run

```bash
python app.py
```

| Shortcut | Action |
|----------|--------|
| **F1** | Start / pause bot |
| **Shift+Tab** | Transparent overlay mode |

---

## First-time setup

### 1. Screen regions (tab **Regions**)

1. **Set water zone** — draw a box where the bobber appears.  
2. **Set mini-game bar** — draw a box around the green reel bar.  

Casts always go to the **center of the water zone**.

### 2. Color calibration (tab **Colors**)

1. Set hue / saturation / value tolerance.  
2. Click the bobber or bar in the left preview panes.  
3. Choose pipette target: **Bobber** or **Green bar**.  
4. Adjust HSV sliders if masks look wrong.

### 3. Bite sensitivity (tab **Fishing**)

Lower sensitivity = faster hook. Higher = waits longer (fewer false bites).

### 4. Profiles (tab **Profiles**)

- **Factory default** = built-in settings in `settings.py`.  
- Click **Save profile** or **New profile** to keep changes after restart.  
- Unsaved changes are lost on exit; startup uses the **last saved profile** or **factory default**.  
- Files: `profiles/<name>.json`, meta: `profiles/_meta.json`.

### 5. Automation (tab **Automation**)

- **Natural timing** — random delay between casts.  
- **Stuck guard** — recast after idle timeout.  
- **Auto bait / Auto food** — assign the correct action-bar keys in-game first.

### 6. Language

Use the **Language** dropdown (top bar): **English** (default), **Indonesia**, or **Filipino**. Choice is stored in `profiles/_meta.json`.

---

## UI layout

- **Left:** live water + bar previews (always visible).  
- **Right:** tabs by topic — Dashboard, Regions, Fishing, Colors, Automation, Profiles.  
- **Bottom:** session stats and activity log.  

Dark theme via **qdarktheme** with the original green/blue accent palette.

---

## Project structure

```text
AutoFishing/
├── app.py
├── fishing_worker.py
├── settings.py
├── translations.py
├── screen_vision.py
├── input_control.py
├── bait_automation.py
├── food_automation.py
├── region_picker.py
├── stats.py
├── theme.py
├── widgets.py
└── profiles/
```

---

## Tips

- Keep resolution and UI scale the same as when you calibrated.  
- Re-pipette colors if lighting changes (day/night, weather).  
- Start with medium bite sensitivity; increase if you get false hook sets.  
- **Assist mode** works well if you prefer manual bite detection.

---

## License & contributions

PolyForm Noncommercial License 1.0.0 — free for personal and noncommercial use only; **commercial use is not permitted**. See [LICENSE](LICENSE).

Bug fixes and documentation PRs welcome.

---

## Disclaimer

Not affiliated with Sandbox Interactive GmbH. *Albion Online* is a trademark of its respective owners.
