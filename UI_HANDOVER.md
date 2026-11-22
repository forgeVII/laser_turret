# UI Handover — Antigravity → OpenCode

> Purpose: one final **visual-only** polish pass on the simulator HUD.
> Return the edited file(s) to the OpenCode turret chat for final verification.
> **No commit, no push.**

## Copy/paste brief for Antigravity

You may own the **look and layout** of the simulator. You may **not** change
behaviour, math, aiming, calibration, transport, hardware safety, or key meanings.
Make the existing tactical green HUD feel finished and professional at the user's
native **2880×1800** desktop, while keeping the logical 1300×750 layout intact.
One pass only, then hand it back for the user to test.

---

## 1. Real project

- Project root: `C:\learning\projects\embedded\laser_turret`
- Main file to edit: `C:\learning\projects\embedded\laser_turret\simulation\main.py`
- Do **not** edit backups (`main_pre_*.py`) or archived firmware sketches.
- Do **not** edit `common/kinematics.py`, `common/turret_link.py`, or any firmware.
- Create a backup first: `simulation\main_pre_antigravity_ui_backup.py`.

Respond in English. Keep project docs neutral — no affiliation names in any file,
comment, doc, or commit message.

---

## 2. Current stable state — protect this

The project is functionally complete. The UI pass must not undo any of this.

### Geometry / aiming / calibration — locked

```python
WIDTH, HEIGHT = 1300, 750
PAN_CENTRE, PAN_MIN, PAN_MAX = 100.0, 50.0, 150.0
TILT_CENTRE, TILT_MIN, TILT_MAX = 80.0, 40.0, 140.0
DISTANCE_CM = 90.0
CAM_HFOV_DEG = 34.0
CAM_VFOV_DEG = 20.0
ENEMY_X_FLIP = -1.0
ENEMY_Y_FLIP = -1.0
FACE_NOSE_TIP = 1
TRACK_TICK_EVERY = 1
LINK_MODE = "wifi"
```

- `N` types exact **centre-to-centre** distance in cm; `[` / `]` fine-tune by 10 cm.
  There is no `D` slot cycling any more.
- FOV live keys remain `,` / `.` for HFOV and `;` / `'` for VFOV.
- `R` works in all modes as frame-centre hold with laser ON; bias belongs to the
  active wall camera via `active_centre_bias()`. Bias is temporary because the whole
  setup moves between locations.
- HUD dot mirroring is display-only. Hardware aiming and numeric X/Y stay true.
- Do not add rate-control/second-stick control. Do not increase tracking gain or
  tracking speed. Do not add `K` eco-tracking unless explicitly asked later.

### Laser / hardware behaviour — locked

- `S<pan>,<tilt>` = move + laser ON + hold.
- `F` = laser OFF + hold position.
- 2 s no-link watchdog = laser OFF + hold. **No auto-park, no rest, no fold.**
- Envelope stays `X50..150`, `Y40..140`. `Y40` is the lower limit because the laser
  hides below it.
- Never power the whole turret from STM32 USB. No servo current through Blue Pill 5 V.
  Never double-feed Blue Pill from PSU 5 V + USB/ST-Link.
- Laser wiring: PA2 → `1 kΩ` → BC547 base; laser + to PSU pin 2; laser − to collector;
  emitter to GND.

### Link — locked

- ESP32 is **AP-only**: `TURRET_LINK`, `192.168.4.1`, TCP `8888`, greeting
  `TURRET_LINK_READY`.
- No mobile hotspot, no STA mode, no ARP discovery, no host cache.
- PC Wi-Fi joins `TURRET_LINK`; internet is via Bluetooth tethering.
- `L` reconnects to the fixed bridge.
- ESP32 serves one TCP client at a time; do not run `test_bridge.py` while `main.py`
  is open.
- OTA: hostname `turret-bridge`, port `3232`, password `turret`,
  `espota.py -i 192.168.4.1 -p 3232 -a turret -f <firmware.bin>`.

### Camera — locked

- DroidCam/local webcam indices remain.
- Direct IP Webcam MJPEG URL is entered in-sim with `V`; Enter connects, Esc cancels.
- Custom CamBridge/Wi-Fi camera was fully removed — do not reintroduce it.
- HC-SR04 is unused — do not reintroduce it.

---

## 3. Display architecture — do not replace with plain scaling

The previous blurry look came from Windows DPI upscaling. Current code is DPI-aware
and renders the fixed layout at native desktop resolution. Preserve this.

```python
# main.py top
if os.name == "nt":
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
    ...
WIDTH, HEIGHT = 1300, 750
_DISPLAY_SIZES = pygame.display.get_desktop_sizes()
DISPLAY_W, DISPLAY_H = _DISPLAY_SIZES[0] if _DISPLAY_SIZES else (WIDTH, HEIGHT)
UI_SCALE = min(DISPLAY_W / WIDTH, DISPLAY_H / HEIGHT)
def sc(v): return int(round(v * UI_SCALE))
```

- `display` is the real window; `screen` is a `SceneSurface` at `sc(WIDTH)×sc(HEIGHT)`.
- `present()` scales the native scene into the current window and stores `_view`.
- Mouse positions must keep using `scene_pos(event.pos)` for tabs and PIP dragging.
- Fonts are `ScaledFont` wrappers. Keep using `FONT_XS`, `FONT_S`, `FONT`, `FONT_B`,
  `FONT_BB`, `FONT_XB`.
- Draw with `drect()`, `dline()`, `dcircle()` (not raw `pygame.draw.*`) on `screen`.
- `UISurface` reports logical `get_width()`/`get_height()` while holding a native-
  resolution pixel buffer. Do not change that behaviour.
- Images already at native scale must be wrapped with `as_ui()` before blitting.

### Display modes — keep working

- **F9** = windowed at native desktop size.
- **F10** = fullscreen.
- **F11** = toggle.
- Keep `set_display_mode()` / `toggle_display_mode()` and the key-map hint row.

---

## 4. UI regions and current features

Logical layout:

```python
WALL_X, WALL_Y = 330, 60
WALL_W, WALL_H = 940, 529
SIDE_X, SIDE_Y = 10, 10
SIDE_W, SIDE_H = 140, 135
TOP_CX, TOP_CY = 80, 225
TOP_R = 55
HUD_X, HUD_Y = 10, 300
HUD_W = 290
```

Already implemented — polish, do not remove:

- Tactical green-on-black palette, scanlines, corner brackets.
- Clickable mode tabs: `1 MANUAL`, `2 HAND/FACE`, `3 ENEMY`.
- Header with accent bar, active-tab underline, pulsing link lamp.
- Wall feed with camera image, center reticle for `R`, magenta lock bracket in mode 3.
- Wall telemetry strip and segmented system status strip.
- Big X/Y readout card in the HUD.
- Bearing/elevation dials with ticks/labels.
- HUD sections: `POSITION / BEAM`, `MODE / OPTICS`, `TRACK / LOCK`, `CONTROLS`.
- Draggable/hideable tracker PIP: `P` hides only PIP; drag its title bar.
- `H` hides only the on-screen wall dot; hardware laser unchanged.
- Setup screen with camera assignment, `V` hint, `TAB`/`ENTER`/`ESC`.
- Distance entry UI for `N`, URL entry UI for `V`.

---

## 5. What Antigravity may change

Allowed:

- Spacing, alignment, padding, panel heights, font-size balance.
- Contrast, colour hierarchy, line weights, bracket sizes.
- Clearer status chips and mode indicators.
- Better empty/error states: `NO LINK`, `NO CAMERA`, `TARGET NOT FOUND`, `URL ENTRY`.
- Minor decorative detail that does not obscure telemetry.
- Refactoring **drawing functions only** if behaviour stays identical.

Not allowed:

- Changing any constants listed in section 2.
- Changing event-key meanings or adding new keys.
- Changing link/camera/vision/mode logic.
- Changing `present()`, `scene_pos()`, `sc()`, `SceneSurface`, `UISurface`,
  `ScaledFont`, `as_ui()`, `drect()`, `dline()`, `dcircle()`.
- Adding dependencies or downloading files.
- Editing firmware, docs other than a short UI note if needed, or backups.

---

## 6. Must-check states

Check these do not clip or overlap in the fixed 1300×750 logical scene:

1. Setup screen with no cameras.
2. Main HUD with `NO LINK`.
3. Main HUD with live link and mode 1 disarmed (`PRESS SPACE TO ARM`).
4. `R` centre-hold state (cyan reticle + bias text).
5. Mode 3 with target detected (lock bracket).
6. Mode 3 with `TARGET: NOT FOUND` / `holding last aim`.
7. `V` URL-entry state.
8. `N` distance-entry state.
9. PIP visible and hidden.
10. Fullscreen and windowed at 2880×1800.

---

## 7. Verification required before handing back

Run:

```powershell
python -m py_compile "C:\learning\projects\embedded\laser_turret\simulation\main.py" "C:\learning\projects\embedded\laser_turret\simulation\common\kinematics.py" "C:\learning\projects\embedded\laser_turret\simulation\common\turret_link.py"
```

Then do a 180-frame headless render check by injecting `ENTER` once on the setup
screen and `QUIT` at frame 180. Report:

- `py_compile` result.
- 180-frame render result with no traceback.
- Window size reported by `pygame.display.get_surface().get_size()`.
- Screenshot if available.

Do not run `test_bridge.py` while the simulator is open.

---

## 8. Hand back to OpenCode with

- List of files changed.
- Short bullet list of visual changes only.
- Verification output pasted above.
- Any layout state you could not verify.
- Explicit line: **“No logic, math, link, firmware, commit, or push changes.”**

Then the user returns here for the final review and completion.
