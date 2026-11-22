# LASER TURRET — Full Project Context

> Single source of truth for this project. Read this first when resuming.
> Repo: `C:\learning\projects\embedded\laser_turret` · remote `https://github.com/forgeVII/laser_turret` (private)
> Last updated: 2026-11-23

---

## 1. What this is

A pan/tilt **laser turret** with a three-part split:

| Part | Job |
|---|---|
| **PC (Python)** | brain — webcam/vision, aiming math, modes, link heartbeat |
| **Blue Pill (STM32F103)** | muscle — moves two servos and switches the laser |
| **ESP32** | transparent WiFi→UART bridge (no aiming logic) |

Final status: **fully wireless, AP-only**. The ESP32 is always a **SoftAP**
`TURRET_LINK` at `192.168.4.1`; the PC joins that network for the turret link and
gets internet from Bluetooth tethering. There is **no mobile-hotspot/STA mode**,
no subnet discovery, and no Wi-Fi password in the firmware. The simulator connects
straight to `192.168.4.1:8888`, retrying quickly for the first 12 s so a late AP
association or ESP32 boot does not show a false OFFLINE. The ESP32 forwards bytes
between TCP and UART0 unchanged. STM32 firmware needed no changes for WiFi.

**Core safety rule:** working envelope is limited (X 50–150, Y 40–140); `F` and the
2 s link timeout force the laser OFF. **There is no rest/fold position any more** —
`S` means laser OFF + hold position. HC-SR04 was discarded and is not used. Only one
webcam is used, for face tracking; all other aiming is done mathematically. No depth
sensor is used — mode 3 uses the single `DISTANCE_CM` value (set exactly with `N`,
fine-tuned with `[` / `]`).

---

## 2. Architecture (locked)

```
   PC (pygame + MediaPipe)
   vision / mode router / smoothing / IK
            |
            | TCP 192.168.4.1:8888  (fixed AP; no discovery)
            v
   ESP32 SoftAP "TURRET_LINK" + transparent bridge
   UART0: GPIO1 TX / GPIO3 RX  @ 115200
            |
            | PSU header 3 (TX) / 4 (RX)
            v
   Blue Pill: PA10 RX / PA9 TX
   servo X = PA1, servo Y = PA0, laser = PA2
```

**Transport:** `simulation/common/turret_link.py` → `TurretLink`, mode `"wifi"` by
default, `"serial"` as CP2102 fallback. Same payload in both modes.

### Link protocol (115200 baud, 8N1, newline-terminated ASCII)

| Command | Meaning |
|---|---|
| `S<pan>,<tilt>\n` | engage — move both servos to final X/Y angles, laser ON |
| `F\n` | release — laser OFF, hold position (no motion) |

Examples: `S110,60\n`, `S80,75\n`, `F\n`.

**STM32 link watchdog:** 2 s with no valid command → laser OFF, position held.
No auto-rest (removed with the no-rest geometry). The PC sends a heartbeat
(`link.service()`, every 0.8 s) so tracking doesn't trigger it. USB debug commands do
**not** feed/reset the link watchdog.

---

## 3. Hardware (as built)

### 3.1 Bill of materials / status

| Item | Status / note |
|---|---|
| Blue Pill STM32F103C8T6 | flashed with `turret_main.ino`; SWD/ST-Link first, no USB bootloader assumed |
| ESP32 38-pin DevKit (CP2102 onboard) | flashed with `esp32_bridge.ino`; mounted on PSU box |
| 2× SG90 servo | X/pan and Y/tilt; both work |
| Laser 650 nm 5 V 2-wire | switched by BC547 low-side via 1 kΩ on PA2 |
| Custom PSU | XL4015 variable 5 V / CC 2.0 A + MP1584 fixed 5 V; battery + adapter mode, BMS + charger working |
| CP2102 dongle | debug fallback only, **data-only** (5 V not connected) |
| ST-Link V2 | flashing + bench 3.3 V only; not part of final setup |
| HC-SR04 | **discarded / not used** |

### 3.2 PSU header map (as built)

| Pin | Function |
|---|---|
| 1 | fixed 5 V — MP1584 (ESP32 + Blue Pill) |
| 2 | variable 5 V — XL4015, CC set 2.0 A (servos + laser) |
| 3 | ESP32 TX (GPIO1) |
| 4 | ESP32 RX (GPIO3) |
| 5 | GND |

### 3.3 Final wiring

| From | To |
|---|---|
| ESP32 VIN/5V | PSU header 1 |
| ESP32 GND | PSU header 5 |
| ESP32 TX (GPIO1) | header 3 → Blue Pill **PA10** |
| ESP32 RX (GPIO3) | header 4 ← Blue Pill **PA9** |
| Blue Pill 5V | PSU header 1 |
| Blue Pill GND | PSU header 5 |
| Servo + laser +5V | PSU header 2 |
| All grounds | PSU header 5 (common) |
| Laser red/+ | PSU pin 2 |
| Laser bare/− | BC547 collector |
| BC547 emitter | GND |
| PA2 → 1 kΩ | BC547 base |

BC547 orientation, flat face toward you, legs down: **C – B – E** (left / middle / right).

### 3.4 Power rules (never violate)

- Never power the whole turret from STM32 USB. USB measured **4.80 V, ~0.7 A**.
- Never feed Blue Pill 5 V from PSU and USB/ST-Link 3.3 V at the same time.
- No servo current through the Blue Pill 5 V pin.
- CP2102 data-only: TX/RX/GND connected, **CP2102 5 V not connected**.
- ESP32 and Blue Pill share the MP1584 rail; servos/laser share the XL4015 rail.
- Power math: servo+laser peak ~1.54 A; ESP32+Blue Pill peak ~0.6 A; total ~11 W.
- Jitter was diagnosed: **no voltage drop**; current limit stays 2.0 A.

### 3.5 Physical axes and safe envelope (re-aligned 2026-11-19)

| Axis | Pin | Centre | Working range | Notes |
|---|---|---|---|---|
| X / pan | PA1 | 100 | **50–150** (centre ±50) | reduced 10° each side after physical re-check |
| Y / tilt | PA0 | 80 | **40–140** | below 40 the laser hides in the mount |

- **No rest/fold position.** `S` = laser OFF + hold; nothing parks on its own.
- Y min 40 is a hard physical limit (laser occluded below it).
- New mounting: Y joint 2.5 cm above floor; X joint 2.5 cm west + 2.5 cm above Y;
  laser 2.5 cm east + 1.5 cm below X → laser tip 1 cm above Y joint. No component
  collisions inside the new envelope.
- `Servo.read()` is unreliable on this core — firmware tracks `posX`/`posY` itself.

### 3.6 Toolchain / flashing

- Arduino IDE + **Arduino_STM32** core (NOT `Arduino_STM32-master`, NOT STMicroelectronics core).
- Active core: `C:\Users\hc808\OneDrive\Apps\Documents\Arduino\hardware\Arduino_STM32\STM32F1`.
- Upload method `STLinkMethod`. FQBN:
  `Arduino_STM32:STM32F1:genericSTM32F103C:upload_method=STLinkMethod`.
- ST-Link SWDIO/SWCLK are internally PA13/PA14. Two ST-Link entries exist; use the
  healthy `Status: OK` instance, not the stale `Unknown` phantom.
- Arduino CLI: `C:\Program Files\Arduino IDE\resources\app\lib\backend\resources\arduino-cli.exe`.
- ESP32 FQBN: `esp32:esp32:esp32`.
- **Arduino CLI cache gotcha:** `upload` can reuse a stale binary after editing a
  sketch. Use `compile --clean` and verify the built `.bin` contains a new debug
  string before flashing.

---

## 4. Firmware

### 4.1 STM32 — `firmware/turret_main/turret_main.ino`

Final firmware. `Serial` = USB/COM debug; `Serial1` = PA9 TX / PA10 RX link @ 115200.

Debug commands: `C` centre · `X<n>` · `Y<n>` · `S` laser OFF + hold (no rest) ·
`O` laser ON · `F` laser OFF · `L` line loop · `I`/`8` infinity · `Q` status · `H` help ·
`J0` stop · `J1` X slow · `J2` Y slow · `J3` X fast · `J4` Y fast ·
`J5` both slow · `J6` both fast · `J7` infinity slow · `J8` infinity fast.

`J1`–`J4` = smooth single-axis sweep diagnostic (2026-11-19): moves only that axis,
laser forced OFF, watchdog suppressed, `writeMicroseconds()` via `degToUs()` at
0.1°/10 ms (slow) or 0.5°/10 ms (fast), one `report()` per end-of-sweep (no Serial
throttling). Same endpoint pulses as `write()` → safe envelope unchanged. Use it to
separate software stepping from mechanical binding, X vs Y. `J5`/`J6` drive both axes
in parallel (slow/fast) at the new envelope; `J7`/`J8` run the infinity figure-8 at
40 ms/step and 3 ms/step with the laser on for visual dot-dot checks. `J0` stops all
loops and diagnostics without snapping.

**Root cause of jerky "dot-dot" motion (confirmed in code, 2026-11-19):** normal moves
use `servo.write(int)` in exact 1° increments, one step per `STEP_MS=25` (measured
~37 ms because `report(Serial)` blocks ~20 ms per line at 115200). That is ~1° every
~37 ms on **both** axes — inherent stepping, not a power fault. Gemini's "integer
degrees" point was correct; its cap/ground-loop advice is secondary here (user
measured no voltage drop, common GND already at header 5). Mechanical backlash on
the cantilevered tilt (Y) is still possible — that is what `J1`/`J2` isolate.

**Diagnostic results (2026-11-19):** run `J1`–`J4` with fine `writeMicroseconds()` steps:
- X smooth at fast (250°/s); mild stepping only at slow (10°/s) = servo deadband
  (0.1° ≈ 1 µs commands fall inside the ~3–5 µs deadband → stick-slip). X is mechanically fine.
- Y stepped at BOTH speeds and vibrated at fast reversals → mechanical backlash / gear
  drift / gravity load on the cantilevered tilt. Needs physical inspection.
- Decisive next test: physically swap X and Y servos, rerun `J1`/`J2`. If the fault
  follows the servo → replace it; if it stays on the tilt axis → mount/bracket/load.

**Swap test (2026-11-19) — RESOLVED:** user swapped the X and Y servo bodies and reran
`J1`–`J4` twice. Both axes now smooth at fast; only minor deadband stepping remains at
slow. The fault did **not** follow either servo — removing and refitting the horns
reseeded whatever was loose (loose horn/spline or gear). **No replacement servo, no
bracket modification needed.** Keep an eye on the tilt horn; retighten if judder returns.

**Smooth-motion upgrade (2026-11-19) — flashed & verified on COM12:**
Normal motion no longer uses `servo.write(int)` 1° steps. A sub-degree output layer:
- `degToUs(float)` — interpolates the core's 544..2400 µs map, same endpoints as `write()`.
- `driveServos()` every `DRIVE_MS=5` ms via `writeMicroseconds()`; `approachDeg()` uses
  an 80%-of-error step with a 0.3° (~3 µs) floor so commands stay outside servo deadband
  and converge monotonically (no limit-cycle hunting).
- `STEP_MS` 25→10 ms for the integer target logic; `report(Serial)` removed from every
  step and throttled to `REPORT_MS=100` ms **only on state change** (was a ~20 ms/line
  blocking stall at 115200). Idle now emits zero lines.
- Diagnostic sweeps sync `smoothX`/`smoothY` as they run, so `J0` exits with no snap.
- Envelope / link watchdog / F-release safety logic preserved; rest later removed.
- Help marker: `motion: sub-degree 5ms, feedback 100ms`.

Verified behaviour (current build, 2026-11-19):
- Centre X100 Y80; `C` returns there directly; X clamps to 50/150, Y to 40/140.
- `S` / `F` → laser OFF, **hold position** (no fold).
- `O` arms laser; laser-on-while-idle stable once wiring is seated.
- Feedback throttled (0 idle lines / 3 s); `J0` continuity: no jump on stop.
- Final binary marker `X50..150 Y40..140`, size 27,244 B; flashed over ST-Link.
- Figure-8 `J7` (40 ms) and `J8` (3 ms) both ran with laser ON, watchdog suppressed
  during loops; user visual check: smooth, no dot-dot, all mechanical issues fixed.

Earlier test sketches kept in `firmware/`: `servo_center`, `servo_sweep`,
`laser_center`, `serial_test`.

### 4.2 ESP32 — `firmware/esp32_bridge/esp32_bridge.ino`

Transparent bridge, no protocol translation:
- **WIFI_AP only**: open `TURRET_LINK` at `192.168.4.1`. No `WIFI_SSID`, `WIFI_PASS`,
  STA timeout, or hotspot fallback exists in the sketch any more.
- PC joins `TURRET_LINK`; the simulator connects directly to `192.168.4.1:8888`.
  Internet stays on Bluetooth tethering, so the phone's Wi-Fi hotspot is unused.
- The bridge still sends `TURRET_LINK_READY` on connect as a sanity greeting.
- TCP port **8888**; uses UART0 (GPIO1 TX / GPIO3 RX) to match the fixed PSU header wiring.
- Single TCP client at a time; replies from STM32 mirrored back to the client.
- Optional debug on Serial1 TX = GPIO26 (not needed for operation).
- GPIO2 onboard LED: 200 ms blink = PC client connected, 1000 ms = AP idle.
- **ArduinoOTA enabled 2026-11-21** (hostname `turret-bridge`, password `turret`,
  port 3232). After the one final wired flash, all later updates go over WiFi —
  no BOOT/EN pressing, no opening the box. Select `turret-bridge at <ip>` in
  Arduino IDE → Tools → Port. OTA reboots straight into the new sketch.
- Flash via CP2102 on the header requires BOOT held; easier via ESP32 onboard USB
  (DTR/RTS auto-reset — no manual BOOT/EN tapping at all).
- Flashing with BOOT held during the final reset leaves the chip in download mode —
  press EN once with BOOT released.
- Old sketches are kept locally in `firmware/esp32_bridge_archive/` (outside the
  sketch folder so Arduino CLI ignores them), excluded from the published repo.
  Only the AP-only bridge is shipped.

**Critical physical faults found and fixed inside the PSU box:**
1. The GND near the ESP32 5 V pin was **not continuous** with the board's other
   grounds — use the working GND.
2. **SD1 and SD0 were shorted** on the ESP32 base, killing flash reads (`invalid
   header: 0x00000000`, RTCWDT reset loop). Fixed; boot is clean now.

Do not let the CP2102 dongle drive header 3/4 during normal operation — its TX would
contend with Blue Pill PA9 on ESP32 GPIO3. Dongle can stay on PC USB if its UART pins
are disconnected from the header.

---

## 5. Kinematics (direction-based aiming)

Single source of truth: `simulation/common/kinematics.py`. Gemini's wall-point formula
was checked as a reference only (matched exact IK within ~0–1.5°) and was **not** adopted.
No conflicting math in project files.

### 5.1 Geometry (re-aligned, measured 2026-11-19)

Kinematic chain is **tilt-first**: Y/tilt is bolted to the base, X/pan is mounted on
Y, laser is mounted on X.

- Tilt joint **A** = base, 2.5 cm above floor.
- Pan joint **B** = A + (−2.5 right [2.5 west], 0 forward, +2.5 up) cm.
- Laser = B + (+2.5 right [2.5 east], 0 forward, −1.5 up) cm.
- Laser relative to tilt base A = **(0, 0, 1.0)** cm — directly above the tilt axis.

Because the laser has no forward offset from the tilt axis, azimuth and elevation are
strongly coupled; extreme IK corners are physically unreachable and clamp.

### 5.2 Servo mapping and beam direction

```
pan  = X - 100    (+ = right)
tilt = 80 - Y     (+ = up)
```

Coordinate frame: x = right, y = forward, z = up. For tilt-first:

```
beam_dir = ( sin(pan),  cos(pan)*cos(tilt),  cos(pan)*sin(tilt) )
azimuth   = atan2(x, y)
elevation = atan2(z, sqrt(x² + y²))
```

Verified examples (`python common\kinematics.py`):
- X100 Y80 → az **0.00°**, el **0.00°** (new centre)
- X130 Y60 → az **+31.57°**, el **+17.23°**
- X150 Y40 → az **+57.27°**, el **+24.40°**
- X50 Y140 → az **−67.24°**, el **−33.83°**

Exact IK self-test:
- want +40.0/+25.0 → X135.63 Y48.67 → got +40.00/+25.00
- want −40.0/−35.0 → X68.23 Y122.43 → got −40.00/−35.00
- want +50.0/+40.0 → X135.93 Y40.00 → got +43.41/+31.36 (clamped at Y min —
  corner unreachable with the new geometry, not a bug)

The firmware receives only final X/Y angles; all coupling/geometry is done PC-side.

---

## 6. Simulator / PC side

### 6.1 Key files

```
simulation/
├── main.py                         # main program: pygame HUD + modes + link
├── common/
│   ├── kinematics.py               # tilt-first FK/IK + direction model
│   ├── turret_link.py              # TurretLink: wifi TCP / serial fallback
│   ├── face_ai.py                  # ArcFace embeddings (parked)
│   ├── coord_mapper.py
│   ├── gamepad_reader.py
│   ├── virtual_mcu.py
│   └── visualizer.py
├── modes/                          # earlier modular baseline
├── test_bridge.py                  # offline WiFi→UART E2E test
└── test_loopback.py                # ESP32 UART loopback diagnostic
```

`python -m py_compile main.py common\kinematics.py common\turret_link.py` passes.

### 6.2 Link usage in `main.py`

```python
LINK_MODE = "wifi"
# Fixed ESP32 SoftAP; no discovery/cache. Fast startup retries are built in.
link = TurretLink(mode=LINK_MODE, port="COM4", baud=115200,
                  host=TURRET_HOST, tcp_port=TURRET_PORT, heartbeat=0.8)
...
# one engage state drives BOTH the HUD laser display and the link
if current_mode == 1:            # MANUAL: Space arms laser + motion
    link_engage = laser_on
elif track_source == "HAND":
    link_engage = hand_detected and hand_gesture == "FIST"
else:                            # FACE
    link_engage = face_detected
...
cmd = f"S{int(round(servo_pan))},{int(round(servo_tilt))}" if link_engage else "F"
if cmd != arm_last_cmd:
    link.write(cmd + "\n"); arm_last_cmd = cmd
link.service()
...
link.close()   # on exit
```

Servos only step while `link_engage` is true — disarmed means the sim holds position,
matching the hardware `F` (hold, laser OFF). This is why screen and real turret now agree.

Set `LINK_MODE = "serial"` for the CP2102 fallback (port may be COM11 now; check with
`Get-PnpDevice -Class Ports`).

### 6.3 Modes and controls

| Key | Action |
|---|---|
| `1` | MANUAL — gamepad sticks (`G` toggles STICK↔KEY; arrow keys) |
| `2` | HAND / FACE tracking on the user camera — `T` toggles source |
| `3` | **ENEMY TRACK** on the front/target camera (DroidCam) — `T` toggles HEAD/HAND |
| `R` (all modes) | frame-centre hold + calibration — laser ON, cyan crosshair in wall view |
| hold arrows (any mode + `R`) | FINE trim at 8°/s, clamped to ±10°. Do **not** use mode-1 KEY's 55 units/s here — that slammed X into its end stop. `Z` zeroes the active bias for recovery; `R` again finishes and prints values |
| `Space` | MANUAL arm toggle — controls **real** laser + motion (and HUD) |
| `Enter` | fire flash / confirm setup |
| `C` | recentre head + aim |
| `E` | enroll face (PLAYER1..n) |
| `+` / `-` | face-match threshold |
| `M` toggle overlay · `H` toggle wall dot · `Z` zero R bias · `O` cycle joystick · `Y` cycle target camera · `U` cycle user camera |
| `N` / `[` `]` | type exact centre-to-centre distance in cm / fine-tune by 10 cm |
| `Tab` setup · `Esc` quit |

**Enemy mode (`3`)** runs detection on `target_raw` (front camera). Assign the phone's
DroidCam as the target camera in TAB setup or with `Y` until the wall view shows its
index (currently PC index **1**, 640×480 via MSMF; laptop webcam is 0 at 2560×1440).
Face → nose tip, hand → palm centre; **largest bounding box wins** (models
configured for up to 4 faces / 4 hands — verified to load). Normalized point uses
`nx = (u − 0.5)·2 · ENEMY_X_FLIP`, `ny = (0.5 − v)·2 · ENEMY_Y_FLIP`; the IK then
solves a wall point at the selected distance. **Live-tested 2026-11-20: both flips
are `-1.0`** — with `+1.0` the physical beam moved opposite to the target on both
axes in mode 3 only. The wall-view dot now uses the same display-only mirror as
the other modes; do not change the flips to fix the on-screen dot.
Laser engages while a target is visible, `F` when lost; losing a
target **holds the last aim** (no auto-park). No depth sensor: the operator selects
90 or 180 cm with `D`; keep the beam away from eyes and retain Space/Esc as the
kill switch.

**Frame-centre calibration (the phone is ~1 cm below and ~1 cm forward of the
laser):** the active wall camera draws a cyan crosshair at frame centre. Put a
physical mark at that spot in the scene, press `R` in **any** mode → beam goes to
frame centre at the selected distance with laser ON and holds; **hold arrow keys**
until the real laser dot covers the mark, then press `R` again. The console
prints `ENEMY_CENTER_AZ_BIAS` / `ENEMY_CENTER_EL_BIAS` and `USER_CENTER_*` values —
copy them to the top of `main.py` to persist. Stored biases are in beam degrees
(`+az` right, `+el` up) and apply to tracking as well as centre hold. Expect a small
**negative** EL bias for the 1 cm-low camera. The live arrow mapping is inverted
(`LEFT` raises az, `RIGHT` lowers it, `UP` lowers el, `DOWN` raises it) because
this mount/servo reverses raw az/el; that makes both the wall dot and the physical
laser follow the arrow exactly like mode-1 KEY. If target following is inverted
again, flip `ENEMY_X_FLIP` / `ENEMY_Y_FLIP`, not the bias signs.

Hand mode: **FIST engages** (laser ON, servos follow); open/partial = free.
Face mode: face detected engages. Head yaw/pitch gains currently `2.4` / `3.0`.

Direction signs calibrated on real hardware 2026-11-19 (after the servo re-alignment):
- Manual (keys + stick, both axes) were reversed: `+X = pan LEFT`, `+Y = tilt UP`.
  Keyboard and gamepad stick signs flipped accordingly.
- Hand vertical was reversed: `ny = (wy - 0.5) * 2` (was `0.5 - wy`). Horizontal unchanged
  (`wx = hand_x`, raw cam; display mirrored separately).
- Face: `HEAD_YAW_FLIP = +1.0` unchanged (horizontal correct), `HEAD_PITCH_FLIP = +1.0`
  (was −1.0) for vertical.
- Manual now engages the link; screen and hardware share `link_engage`.
- **Stick mode:** first stick only (axes 0/1), absolute mapping; releasing returns to
  centre. The second-stick / rate-control experiment was tried and **reverted** — it
  degraded aiming accuracy.
- **HUD dot/beams:** `show_beam` keeps the dot visible in all three views even while
  disarmed. The point is **mirrored on both axes for display only** via `hud_mirror()`
  (`X'=200−X`, `Y'=160−Y`); hardware/laser and the numeric az/el readout stay true.
  Hardware still follows `link_engage` only.
- **Hand/face speed:** original gains retained (`AIM_SMOOTH=0.35`,
  `SERVO_MAX_VEL=280`, `SERVO_GAIN=6.0`). The faster-gain experiment degraded
  accuracy and was **reverted**.
Simulator servo smoothing constants: `SERVO_MAX_VEL=280`, `SERVO_MAX_ACCEL=1400`,
`SERVO_GAIN=6.0`, `AIM_SMOOTH=0.35`.

Manual controls are clamped to the working envelope. The on-screen dot uses a virtual
wall at 200 cm only for projection; aiming itself is direction-based. Constant small
horizontal dot offset is expected 2.5 cm lateral parallax.

### 6.4 Face recognition — **parked, not working live**

`common/face_ai.py` loads ArcFace ONNX (`arc.onnx`, 130 MB, gitignored), 512-d
embeddings, cosine match threshold default 0.30, enrollment JSON persistence.
Most likely failure: `embed()` only resizes the bbox to 112×112 — **no 5-point
landmark alignment**. Fix when resumed: align with 5 landmarks (eyes/nose/mouth)
before embedding, then retune threshold. Pipeline itself loads and self-matches.

---

## 7. Verification performed

| Test | Result |
|---|---|
| PSU build, adapter + battery, both rails 5 V, charging | PASS (2026-11-17) |
| ST-Link flashing, USB serial sanity (`ALIVE`) | PASS |
| Physical pin/angle mapping X=PA1, Y=PA0, C→X100 Y80 | PASS |
| Envelope clamps X50/150, Y40/140 (new alignment) | PASS |
| No-rest behaviour: S/F = laser OFF + hold | PASS |
| CP2102 data-only on PA9/PA10 (`H`, `S`, `F`) | PASS |
| ESP32 compile + flash + SoftAP boot | PASS (old AP firmware) |
| WiFi TCP bridge `H`, `S110,60`, `S80,75`, `F` | **PASS — fully wireless** (old AP firmware) |
| ESP32 AP-only firmware compile + OTA flash | PASS 2026-11-23 — no credentials, no STA, no hotspot path |
| ESP32 live on `TURRET_LINK` | PASS — PC `192.168.4.2`, bridge `192.168.4.1`, signal ~96–99% |
| Full TCP→UART→STM32 round trip over AP | PASS — `H` → 494-byte help reply; `TURRET_LINK_READY` greeting confirmed |
| ArduinoOTA push (LED blink fix) | PASS 2026-11-21 — 100% upload, no wires/EN/box opening |
| Fixed bridge startup retry (no discovery) | PASS 2026-11-23 — 0.25 s retry for 12 s, then 2 s |
| `python -m py_compile` for main + kinematics + link + scripts | PASS |
| Final visual-only UI polish (2026-11-23) | REVERTED — Antigravity pass introduced elevation-gauge overflow, swapped gimbal direction, overlapping text, and clutter; user preferred the prior HUD. `main.py` restored byte-identical to `main_pre_antigravity_ui_backup.py`. The rejected pass is kept as `main_antigravity_ui_reverted_backup.py` for reference only. 180-frame headless render + py_compile PASS on restored file. |
| Gauge fix superseded (2026-11-23) | Both old left-top boxes (bearing dial + elevation needle) removed. Replaced by one `draw_gimbal_pose` scope (x10..300, y10..296) + travel sliders in the HUD `POSITION / BEAM` card. Scope is **not square**: it uses the wall-camera aspect `WALL_W/WALL_H` (266×150 ≈ 1.777). Scope and slider dots use the **same transform as the wall dot** — `display_aim()` mirror then `project_dot()` normalised on the wall rect — not raw servo values; this fixed the left/right reversal. Verified: X50→150 moves dot 1.002→0.002 (left, same as wall), Y40→140 moves 1.119→-0.798 (up). Layout probe: HUD text y=698/746, pose text y=237/296, both fit. 180-frame render PASS at 2880×1800. |
| Physical direction calibration (2026-11-19) | PASS — X100 = new centre, +X = pan right; Y80 = new centre, lower Y = tilt up; `pan = X−100`, `tilt = 80−Y` |
| New geometry kinematics self-test (2026-11-19) | PASS — centre + normal ranges round-trip exactly; extreme corners clamp (laser 1 cm above tilt axis → strong az/el coupling) |
| `J7`/`J8` figure-8 with laser ON (2026-11-19) | PASS — user visual check: no dot-dot, no judder |
| Mode direction/link fixes (2026-11-19) | fixed hand L/R (`wx = hand_x`), face L/R + U/D (flips `+1`/`-1`), manual engage (screen = hardware via `link_engage`); `py_compile` PASS — **needs live re-test** |

Test log: `simulation/bridge_test_result.txt`.

---

## 8. Git state

- `d8b2979` baseline simulator.
- `a8fd62e` face recognition — **local, not pushed**.
- Working tree (uncommitted): `simulation/main.py`, `common/kinematics.py`,
  `common/turret_link.py`, `test_bridge.py`, `test_loopback.py`, `CONTEXT.md`,
  `mini_test/`, `firmware/` sketches and `firmware/esp32_bridge_archive/`.
- **Commit/push only if explicitly asked.**

---

## 9. Next steps (in order)

1. ~~Visual confirmation of smooth normal motion~~ **DONE (2026-11-19):** slow/fast
   figure-8 with laser ON checked by user — everything fixed, no dot-dot or judder.
2. ~~Flash the AP-only firmware~~ **DONE 2026-11-23** (OTA). Join PC to
   `TURRET_LINK`, run `python main.py`, and confirm `[Link] WiFi AP 192.168.4.1:8888 OK`.
   Re-test manual `Space`, hand FIST L/R, face both axes, and mode-3 axis flips.
3. ~~Add ArduinoOTA~~ **DONE 2026-11-21** (one final wired flash installs it; later
   flashes are WiFi-only with no box opening).
4. Refresh stale `TRACKER.md` references (HC-SR04, single-servo plan) if desired.
5. Live-test the 2026-11-21 aiming changes below: R in modes 1/2/3, mode-3
   dot mirror, smooth recentre, and exact `N` distance entry.
6. Later: fix face recognition with 5-point landmark alignment.
7. ~~UI polish handover~~ **REVERTED 2026-11-23**: the Antigravity visual pass
   was rejected by user (gauge overflow, swapped gimbal, overlaps, clutter).
   Do not re-apply the rejected pass.
8. ~~Left-top gauges~~ **REPLACED 2026-11-23**: both X/Y dial boxes removed;
   single `GIMBAL POSE` scope + HUD travel sliders from the Antigravity pass
   reintroduced in the clean layout. `main.py` is now final.
9. Commit/push **DONE 2026-11-23**: `3b82494` pushed to `origin/main`
   (`forgeVII/laser_turret`). Local rollback copies, archived pre-AP sketches,
   build output and stale test logs stay unpublished.

---

## 10. Known issues / gotchas

| Issue | Cause | Fix / note |
|---|---|---|
| Turret auto-rest during tests | removed with no-rest geometry | no longer applicable |
| Laser unexpectedly OFF on post-move check | 2 s link watchdog / `F` | Expected — send `O` to re-arm, or keep heartbeat via `link.service()` |
| Hardware X/Y not moving in mode 1 | `laser_on` defaults to **False**; `S` is laser ON + hold, so hardware only moves while armed | Press `Space` once (HUD now shows `PRESS SPACE TO ARM`). STICK still shows the HUD dot while disarmed; KEY shows nothing until armed |
| Laser randomly dropped while sitting still (fixed) | loose PA2 → 1 kΩ → BC547 base / laser connector after rewiring | reseated wiring; laser then stayed ON through 18 s idle |
| Board boots in download mode after flashing | BOOT held during final reset | Press EN once with BOOT released; **or** use ESP32 onboard USB (auto-reset) / ArduinoOTA so it never happens again |
| Must open the box to press EN / see blue LED | EN+BOOT buttons and GPIO2 LED are inside the enclosure | One-time fix: bring EN, BOOT and GPIO2 (with 330 Ω LED) out to panel-mount controls; OTA then removes all later flashing resets |
| **EN must be pressed at EVERY PSU power-on** (confirmed 2026-11-21 — not just after flashing) | EN pin not asserted HIGH at power-up: missing/weak EN pull-up, or PSU 3.3 V rail ramps too slowly for the chip's internal POR. OTA reboots work fine without EN → chip itself is healthy | Hardware one-time fix: **10 kΩ EN → 3.3 V** plus **100 nF EN → GND** (Espressif POR RC) so EN rises after the rail settles; also verify **10 kΩ BOOT/GPIO0 → 3.3 V** and that the BOOT button isn't stuck. If a quick panel override is wanted instead, bring EN out to a panel button (still a press, but no box opening). Firmware cannot fix this — the chip isn't running yet |
| `invalid header: 0x00000000`, RTCWDT reset loop | SD1/SD0 shorted; wrong GND on ESP32 base | Fixed physically — use working GND, keep SD1/SD0 separated |
| XL4015 current LED full / main LED off on ESP32 load | ESP32 base short | Fixed with the wiring above |
| Arduino CLI uploads stale code | build cache | `compile --clean`; grep `.bin` for a new string |
| Arduino CLI upload dies at `Invalid head of packet (0x80)` during app write | 921600 baud over long/manual CP2102 header wiring (bootloader still wrote) | re-flash with bundled `esptool.exe --baud 115200 --before no-reset --after no-reset write_flash 0x1000 <bootloader> 0x8000 <partitions> 0xe000 boot_app0.bin 0x10000 <app>`; all hashes verified |
| Simulator lagging / frozen when bridge is down | `TurretLink._connect_tcp()` did a blocking 0.4 s connect on every 0.8 s heartbeat | fast 0.25 s startup retry for 12 s, then 2 s backoff + state-change-only logs (fixed 2026-11-23) |
| Bridge shows OFFLINE right after launch | PC had not finished joining `TURRET_LINK`, or ESP32 was still booting | fixed 2026-11-23: no discovery/cache, fixed AP IP, 0.25 s reconnect during startup; press `L` to force a fresh connect |
| Blue LED stuck ON after boot | `blink()` was only called when a PC client was connected | one `blink()` per loop in every state; OTA'd 2026-11-21 |
| TCP probe fails while simulator runs | ESP32 serves **one TCP client at a time**; `main.py` holds the slot | expected — stop `main.py` before running `test_bridge.py` / diagnostics; press `L` in-app to reconnect |
| COM ports shift / stale `Unknown` entries | USB renumbering | Check `Present` with `Get-PnpDevice`, use the live instance |
| `Servo.read()` wrong | core quirk | firmware tracks `posX`/`posY` |
| Servo stutter | USB rail brown-out (diagnosed: no drop here) | external 5 V supply, common GND; keep 2.0 A limit |
| `ESP32Servo` needed for mini-test | core 3.x dropped Servo | `#include <ESP32Servo.h>` |
| `LED_BUILTIN` missing | some ESP32 variants | use pin `2` directly |
| CP2102 contention on header 3/4 | dongle TX drives ESP32 RX | disconnect its UART pins during normal operation |
| `H` help reply truncated over WiFi (was ~363 B) | ESP32 bridge per-byte `Serial1.printf` debug on UART→TCP starved RX on long bursts | **FIXED 2026-11-19:** removed both per-byte debug prints, chunked UART→TCP into 128 B writes, reflashed via CP2102 header. Full 492 B help now arrives intact |
| No internet with old AP workflow | single Wi-Fi adapter | fixed 2026-11-23: PC Wi-Fi joins `TURRET_LINK` for the bridge; internet runs over Bluetooth tethering. No phone hotspot, no STA/fallback path |
| Face recognition never matches | no landmark alignment | parked; add 5-point alignment before embedding |
| X servo physically near 0 / no response (2026-11-21) | **Confirmed by user:** an internal solder joint inside the X servo broke off after the earlier end-stop event. Firmware query still showed a safe `X=89 Y=45 LASER=OFF`, so the command was fine — the servo internals had failed | User opened the servo and re-soldered/fixed it. Re-test with simulator closed first, then mode-1 KEY slowly, then `R` fine trim (8 deg/s, ±10° clamp). Do not send `S` (laser ON) until full X travel is confirmed |

---

## 11. Design decisions log

| Decision | Choice | Why |
|---|---|---|
| Brain/muscle split | PC does vision + math; STM32 is actuator | simple, robust firmware |
| Wireless transport | ESP32 SoftAP `TURRET_LINK` + fixed-IP TCP transparent bridge; Bluetooth tethering for internet | no hotspot credentials, no discovery delay, deterministic startup; no STM32 firmware change |
| Bridge UART | ESP32 UART0, matches fixed PSU header | no desoldering inside the box |
| Link protocol | `S<x>,<y>` / `F`, ASCII, newline | same over serial and WiFi; easy to debug |
| Aiming | direction-based exact tilt-first IK; mode 3 + R use selected-distance wall-point IK | keeps the beam on the camera point away from frame centre without a depth sensor |
| Safe envelope | X50–150, Y40–140, no rest; F + 2 s watchdog force laser OFF | new physical alignment; laser hides below Y40 |
| Laser switch | BC547 low-side via 1 kΩ on PA2 | 3.3 V logic safely controls 5 V laser |
| Servo power | external 5 V, common GND | no MCU brown-out |
| Face ID | MediaPipe + ArcFace 512-d | parked pending alignment fix |
| HC-SR04 | discarded | not needed for direction-based aiming |
| Camera (2026-11-21) | DroidCam / local webcam via `cv2.VideoCapture` indices | custom CamBridge app was tried and removed the same day; not used |

---

## 12. Camera note

Custom CamBridge/Wi-Fi camera work was trialled on 2026-11-21 and **fully removed**
same day at the user's request: `wifi_camera.py`, `PHONE_CAMERA.md`, the handoff doc,
the `TURRET_*_CAMERA_URL` env hooks, and the phone APK were all deleted/uninstalled.
DroidCam/webcam indices 0–8 remain the only camera path.

Kept from that trial: `laser_on` now defaults to **False** — leaving the setup
screen no longer arms the laser; press `Space` in mode 1 to arm. The bridge is now
fixed at `192.168.4.1` with fast startup retries; press `L` in-app to force a
fresh connect if the ESP32 was rebooted.

---

## 13. Aiming fixes implemented 2026-11-21 (first live feedback received)

Local backup before edits: `simulation/main_stable_backup.py`.

| Change | Detail |
|---|---|
| `R` in all modes | `centre_hold` now overrides manual / hand / enemy branches. It aims at the active wall camera frame centre, forces laser ON, and holds position. Press `R` again to finish. |
| Mode-3 dot mirror | `ENEMY_DOT_MIRROR = True`; the wall-view laser dot now uses the same display mirror as the other modes. Hardware az/el are unchanged. |
| R arrow feel (fixed after live test) | `HOLD` an arrow is a **fine trim at 8 deg/s**, clamped to **±10°**. The first attempt used mode-1 KEY's 55 deg/s and drove X to its end stop ("almost 0° and stuck") in about a second — corrected. `Z` zeroes the active bias immediately. Arrow signs remain inverted on both axes so the wall dot and physical laser follow the key on this reversed mount. |
| Distance-aware aiming | Mode-3 lock and all-mode `R` convert the camera-normalized point to a wall point at the selected distance and solve it with `kin.inverse()`. Mount offsets: camera 1 cm forward / 1 cm below laser, effective FOV reused from `AZ_MAX`/`EL_SCALE` (50°). |
| Distance slots | `D` cycles **90 cm** (1 arm) / **180 cm** (2 arm). `[` and `]` fine-tune the active slot by 10 cm (20–500 cm). |
| Hide wall dot | `H` toggles `show_dot`, like `M` toggles the mask. Hides only the on-screen wall-view red dot; hardware laser is unaffected. |

- `apply_bias()` adds the saved degree-style centre trim after the IK solve.
- `active_centre_bias()` selects enemy vs user bias from the camera shown in the
  wall view, not from the mode number.
- Cyan frame-centre crosshair now appears for `R` in every mode, not only mode 3.
- IK round-trip test at 90 cm (single `DISTANCE_CM`): corner error effectively zero
  for reachable points; extreme edges clamp to `X50..150 / Y40..140`.
- `python -m py_compile main.py common\kinematics.py common\turret_link.py` PASS.
- User confirmed: `R` works in modes 1/2/3. User reported R arrows moved both
  screen dot and physical laser opposite on both axes, then reported X servo
  went to almost 0° and stuck after the 55 deg/s change. Both are corrected:
  arrows follow the key, but now at a safe 8 deg/s with a ±10° clamp and `Z`
  recovery.
- **Still needs live re-test:** arrow directions after sign inversion, safe
  slow trim without hitting the end stop, `Z` recovery, `H` hide-dot toggle,
  and whether the exact `N` distance matches the real wall. No commit or push.

---

## 14. Motion tuning after servo repair (2026-11-21)

User confirmed everything works after re-soldering the broken X servo joint, then
asked for more accuracy / smoothness / speed before UI work. Conservative PC-side
uplift only — firmware target rate is still ~100 deg/s (`STEP_MS = 10`), so
raising PC limits beyond this adds lag, not real speed.

| Parameter | Old | New | Effect |
|---|---:|---:|---|
| `AIM_SMOOTH` | 0.35 | 0.45 | Faster hand/face/enemy tracking, still filtered |
| `STICK_SMOOTH` | 0.40 | 0.50 | Snappier mode-1 stick/manual feel |
| `KEY_RATE` | 55 | 65 units/s | Slightly faster mode-1 KEY |
| `TRACK_TICK_EVERY` | 2 | 1 | Inference every frame instead of every other frame |
| `SERVO_MAX_ACCEL` | 1400 | 1800 | Quicker ramp, same top speed |
| `SERVO_GAIN` | 6 | 8 | Tighter small-error tracking |
| `SERVO_MAX_VEL` | 280 | 280 | Unchanged; firmware is the real limit |

**Deliberately unchanged:** `R_BIAS_RATE = 8 deg/s`, `R_BIAS_LIMIT = ±10°`,
and the R target ease of 55 units/s. R is a calibration trim, not flying — the
old 55 deg/s setting caused the X end-stop incident and servo damage.

Needs live check: no judder, no end-stop hits, then UI work. No commit or push.

---

## 15. BODY lock for mode 3 (2026-11-21)

User: hand/face need too much pointing accuracy in mode 3; a human body is wide,
so low accuracy is fine if the beam lands anywhere on the torso.

| Item | Detail |
|---|---|
| Model | `simulation/pose_landmarker_lite.task` (MediaPipe Pose Lite, 5.8 MB, downloaded locally). Missing file disables only BODY; hand/face still load. |
| Setup | `PoseLandmarkerOptions`, `IMAGE`, `num_poses=4`; confidence originally `0.3`, tightened to `0.65` in §17 after false positives. Loaded in the same background thread as hand/face. |
| Selection | In mode 3, `T` cycles `HAND → FACE → BODY → HAND`. In mode 2, `T` still toggles HAND/FACE only, and switching to mode 2 resets BODY to HAND. |
| Lock point | Largest pose by visible bounding-box area; aim at the **torso centre** = mean of shoulders (11, 12) and hips (23, 24). Wide and forgiving; no face/hand precision needed. |
| Overlay | Skeleton drawn from `BODY_CONNECTIONS`; magenta ring on the torso lock point. |
| Aiming | Reuses the existing mode-3 path: normalized point → `aim_from_camera_point()` → IK → `apply_bias()` → `AIM_SMOOTH`. No new gains. |
| Laser | Same rule as other mode-3 sources: ON only while a body is detected; lost target holds last aim. |

**Verified:** py_compile PASS; runtime smoke test PASS with `[Track] MediaPipe tasks API ready (hand + face + body)`; standalone `PoseLandmarker.detect()` PASS. Live aim test still pending.

**UI reference used:** `projects/embedded/tbas/TBAS/web/tbas_interface.html` — dark tactical terminal theme (green on near-black, fine borders, scanline overlay), radar/bearing canvas, big mode + status, large angle readout, event log, connect dot. `TBAS/web/index.html` is the landing page with the same palette.

---

## 16. Tactical HUD restyle (2026-11-21)

User chose: restyle the existing pygame HUD, not a separate web dashboard.
Backup before UI edits: `simulation/main_pre_ui_backup.py`.

| Change | Detail |
|---|---|
| Palette | TBAS green-on-near-black (`BG 8,11,8`, `PANEL_FILL 12,16,12`, phosphor `GREEN 0,255,136`, dim green grid/borders). LASER stays red for safety; landmark magenta unchanged. |
| Chrome | `draw_frame()` square panels with corner ticks (TBAS style), reused by HUD, top/side views, tracker PIP, setup boxes and wall border. |
| Header strip | Above the wall feed: `LASER TURRET` title, subtitle, three **clickable mode tabs** (1 MANUAL / 2 HAND/FACE / 3 ENEMY) and link dot + IP. Keyboard 1/2/3 still work; both use `set_mode()` so BODY→HAND fallback stays consistent. |
| HUD | Big `X` / `Y` bearing lines, laser status chip (`LASER SAFE` / `LASER ON`), compact three-column key map so every command fits inside the panel, no more overflowing controls list. |
| Wall feed | `WALL FEED // CAMx` label strip, dim green border, bottom telemetry strip (mode / track / distance / link / key hints) in place of TBAS event log. |
| Scanlines | Pre-rendered CRT overlay, one blit per frame (subtle alpha 9), drawn last. |
| Setup screen | Same palette; green selected camera box. |

**Verified:** py_compile PASS; runtime PASS with the HUD path forced on (no exceptions); palette pixel counts confirm dark-green panels/grid are drawn. Live visual check still pending from the user. No commit or push.

---

## 17. BODY false positives + draggable PIP (2026-11-21)

User reported BODY mode locking onto random objects, and asked to drag/hide the
webcam window.

### BODY lock tightened

| Guard | Value / reason |
|---|---|
| Model confidence | `0.65` for detection / presence / tracking (was `0.3`). |
| Visible landmarks | At least **10 of 33** above 0.5 visibility. |
| Torso | At least **3 of** shoulders 11/12 + hips 23/24 must be visible. |
| Size | bounding box ≥ 4% of frame, width ≥ 0.06, height ≥ 0.08 normalized. |
| Shape | reject aspect ratios > 3:1 (flat/bag/chair-like blobs). |
| Time | `body_confirm` requires **2 consistent frames** before laser arms; one missed frame only drops the counter by one, so brief dropouts hold the lock. Other sources reset it. |

Still intentionally forgiving once a real person is accepted: aim stays at the
torso centre with the existing IK/bias/smoothing path.

### Webcam PIP

- **`P`** toggles the webcam window (`show_pip`), independent of `M` mask, `H`
  dot and hardware laser.
- Drag the PIP by its title bar; it clamps to the screen. Border turns cyan
  while dragging; title reads `TRACKER (USER CAM) :: DRAG`.
- Mouse clicks on the header mode tabs still take priority over PIP dragging.
- Camera image now fits inside the PIP frame (previous code drew 15 px past it).
- HUD key map and wall telemetry strip include `P PIP`.

**Verified:** py_compile PASS; runtime PASS; injected event test confirmed drag
from `(1002,426)` to `(100,215)`, `P` set `show_pip=False`, and drag flag cleared —
no exceptions. Live check pending. No commit or push.
