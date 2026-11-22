# Laser Turret Project — Chat Tracker

> **Project type:** workshop build
> **Started:** 2026-09-04
> **Status:** Simulation framework created, testing needed

---

## Project Identity

- **Name:** Multi-Input Laser Turret System
- **Philosophy:** PC = brain, MCU = muscle. Only the actuator unit is handed over.
- **Handover unit:** MCU + 2 servos + laser + wires (permanently soldered)
- **You keep:** PC, gamepad, camera, Python code, GitHub repo
- **Coding:** AI writes all code, Harish builds the idea and tests

---

## Architecture (locked)

```
INPUTS               PC (Python Hub)           OUTPUT
------              -----------------         ------
Manual -------+
Gamepad HID ---+--> Mode Router + Processor --> MCU --> Servo Pan (X)
Webcam CV ----+                                  |     --> Servo Tilt (Y)
                                                |     --> Laser (on/off)
                                                |
                                     PC = brain    MCU = actuator
```

---

## Modes (locked)

| # | Mode | Input | Difficulty | Key Library |
|---|---|---|---|---|
| 1 | Manual Control | Serial terminal / gamepad sticks | Easy | pyserial, pygame |
| 2 | Head Tracking | Gamepad MPU6050 -> USB HID | Medium | pygame/hidapi |
| 3a | Hand Tracking | Webcam -> MediaPipe Hands | Hard | mediapipe, opencv |
| 3b | Face Tracking | Webcam -> MediaPipe Face Mesh | Hard | mediapipe, opencv |
| 3c | Object Tracking | Webcam -> YOLOv8-nano | Hard | ultralytics, opencv |
| 4 | Auto-Point & Measure | HC-SR04 on turret | Medium | (MCU-side, ultrasonic) |

Mode switching: Keyboard press (1/2/3). Camera sub-modes: 3a/3b/3c.

---

## Hardware — Handover Unit

| Component | Source | Cost |
|---|---|---|
| 2x SG90 servo | Buy | ~200 (~100 each) |
| 1x Laser module (5V TTL) | Buy | ~20 |
| 1x HC-SR04 ultrasonic | Buy (not available from TBAS) | ~40 |
| External 5V supply (servos) | Buy | ~50-80 |
| Perfboard + wires + headers | Buy/scrap | ~30-50 |
| MCU | **TBD** | **TBD** |
| **Subtotal** | | **~340-390 + MCU** |

---

## Hardware — What You Keep (not handed over)

| Component | Notes |
|---|---|
| PC (laptop) | Runs Python, processes all modes |
| DIY Gamepad (Blue Pill + MPU6050) | Input for modes 2, 3 |
| Webcam / phone camera | Input for modes 3a, 3b, 3c |
| CP2102 adapter | If needed for serial |

---

## MCU — OPEN QUESTION

**Situation:**
- Harish owns 1 Blue Pill -> committed to gamepad
- TBAS (Nano) hardware is not available
- Blue Pill supports USB HID upload (no ST-Link, no TTL needed)
- Servos powered externally, not from MCU

**Options:**
| MCU | Price | Pros | Cons |
|---|---|---|---|
| Buy new Blue Pill | ~160 | USB HID native, 5V, proven toolchain, known | Overkill for "just servos" |
| Arduino Nano clone | ~200 | Simple, ATmega328P, known from TBAS | No USB HID (needs FTDI/CP2102) |
| CH32V003 | ~10-15 chip | Cheapest RISC-V, 48MHz | 3.3V logic, needs WCH-Link, incomplete Arduino |
| ESP32 | ~200-350 | WiFi/BT potential | Overkill, 3.3V logic |

**Upload note:** Blue Pill supports USB HID direct upload (no ST-Link, no TTL). Turret MCU could also do USB HID communication with PC if using Blue Pill.

---

## Pin Count (locked — 7 GPIO)

| Pin | Function | Type |
|---|---|---|
| PA0 | Servo X (pan) — PWM | Digital/PWM out |
| PA1 | Servo Y (tilt) — PWM | Digital/PWM out |
| PA2 | Laser ON/OFF | Digital out |
| PA3 | HC-SR04 TRIG | Digital out |
| PA4 | HC-SR04 ECHO | Digital in |
| PA9 | UART TX (to PC) | UART TX |
| PA10 | UART RX (from PC) | UART RX |

**Note:** If using USB HID instead of UART, PA9/PA10 free up -> only 5 GPIO needed.

---

## Power Design

Power supply docs are in the dedicated
[forgeVII/laser_turret_psu](https://github.com/forgeVII/laser_turret_psu) repo
(`PSU.md`, `BUILD_NOTES.md`).

As built: two 5 V rails — MP1584 fixed 5 V for ESP32 + Blue Pill, XL4015 variable
5 V (CC 2.0 A) for servos + laser — with one common GND and a BMS/charger. The
HC-SR04 was discarded and is not used.

---

## PC Software Structure (AI writes, Harish tests)

```
laser_turret/
  main.py                    -> Entry point, mode selector
  mcu_firmware/
    turret_controller.ino    -> MCU firmware (~50 lines)
  modes/
    manual.py                -> Serial + joystick
    head_track.py            -> Gamepad MPU6050
    camera_tracker.py        -> Hand/face/object (swappable detector)
  common/
    serial_comm.py           -> Serial to MCU
    gamepad_reader.py        -> USB HID reader
    coord_mapper.py          -> Any input -> servo angles
  requirements.txt
```

---

## Simulation Framework (created 2026-09-04)

Digital twin built BEFORE hardware. Simulates entire system in Python.

```
simulation/
  main.py                    -> Entry point, mode selector, visual loop
  common/
    virtual_mcu.py           -> Simulates MCU (servos, laser, HC-SR04)
    gamepad_reader.py        -> Reads REAL gamepad via USB HID
    coord_mapper.py          -> Maps inputs -> servo angles
    visualizer.py            -> Real-time matplotlib display (top/side/status)
  modes/
    manual.py                -> Keyboard + gamepad sticks
    head_track.py            -> Gamepad MPU6050 orientation
    camera_tracker.py        -> Mouse = simulated hand/face/object
    auto_measure.py          -> Sweep + simulated distance
  requirements.txt          -> matplotlib, pygame (+ opencv/mediapipe optional)
```

**How to run:** `cd simulation && python main.py`

**Key features:**
- Real gamepad controls virtual turret
- Visual display shows top view (pan) + side view (tilt) + laser
- All 4 modes work digitally
- Camera tracker uses mouse position as simulated detection
- When hardware arrives: swap VirtualMCU for serial to real STM32

---

## Key Facts (for this project)

- **Zero coding experience** — AI writes all code, Harish builds the idea
- **Strengths:** Ideas, features, mechanical construction, testing, research
- **Gamepad firmware:** Arduino variant with MPU6050 working (original or v2)
- **Gamepad HID:** Sends X/Y/Z (MPU yaw/pitch/roll) + Rx/Ry/Rz (sticks) + buttons via USB
- **Budget:** Under 1k for this build
- **Timeline:** Flexible, start whenever ready
- **TBAS:** Hardware released, not recoverable
- **Python:** Complete beginner — AI writes everything

---

## TBAS Hardware Status

TBAS hardware was released. All TBAS components (Nano, mics, LM393, TSOP1838, IR LED, servo) are NOT available. Must buy fresh for this project.

---

## What's Left to Decide

1. **MCU choice** — Blue Pill buy, Nano, or something else?
2. **Communication** — USB HID (cleaner) or UART via CP2102 (simpler)?
3. **Servo power details** — what 5V supply exactly?
4. **Laser module type** — TTL (on/off) or analog (dimming)?

---

## Handover Checklist

- [ ] MCU with permanently soldered servos + laser
- [ ] HC-SR04 mounted on turret
- [ ] USB cable for PC connection
- [ ] README / documentation
- [ ] Demo: all 4 modes working

---

## Changes Log

| Date | Change |
|---|---|
| 2026-09-04 | Initial planning session. All modes locked. Architecture locked. |
| 2026-09-04 | Price correction: servos ~200 (not 80). HC-SR04 added as Mode 4. |
| 2026-09-04 | Clarified: 1 Blue Pill (gamepad), TBAS hardware released, servo power external. |
