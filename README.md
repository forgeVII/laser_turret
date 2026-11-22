# Multi-Input Laser Turret

PC-driven laser turret simulator and firmware. The PC does vision, aiming and
control; the STM32 drives two servos and the laser; an ESP32 provides a wireless
transparent TCP-to-UART bridge.

> Hardware submission unit: STM32 board + two servos + laser + wiring.
> The PC, cameras and Python tooling stay with the build.

## Architecture

```
PC (pygame + vision)
  -> ESP32 SoftAP "TURRET_LINK" (TCP 192.168.4.1:8888)
  -> UART0 -> STM32 -> pan/tilt servos + laser
```

- Envelope: `X50..150`, `Y40..140`, centre `X100 Y80`.
- `S<pan>,<tilt>` = move + laser ON and hold; `F` = laser OFF and hold.
- 2 s no-link watchdog = laser OFF, position held. No auto-park, rest or fold.
- Modes: `1` manual, `2` hand/face, `3` enemy track on the front camera.

## Quick start

1. Power the PSU, join PC Wi-Fi to the open `TURRET_LINK` network.
2. Run `python main.py` from `simulation/`.
3. The simulator connects to `192.168.4.1:8888` automatically (fast retry for the
   first 12 s). `L` forces a reconnect; `Tab` opens camera setup.
4. `F9` windowed, `F10` fullscreen, `F11` toggle. Rendering is native-resolution
   at the desktop size.

Full key map and calibration notes are in `CONTEXT.md`.

## Documentation

| File | Contents |
|---|---|
| `CONTEXT.md` | full technical context, keys, calibration, verification log, gotchas |
| `TRACKER.md` | build tracker and component list |
| `UI_HANDOVER.md` | bounded UI constraints and display architecture |
| `MEDIA.md` | reserved slots for photos, videos and social links |

Power supply docs live in their own repo:
[forgeVII/laser_turret_psu](https://github.com/forgeVII/laser_turret_psu).

## Firmware

| Folder | Target |
|---|---|
| `firmware/turret_main/` | STM32 servo + laser + link watchdog |
| `firmware/esp32_bridge/` | ESP32 SoftAP TCP-to-UART bridge + OTA |

Old sketches are in `firmware/esp32_bridge_archive/` for reference only.

## Media

Photos, videos and social posts are reserved in `MEDIA.md` and the `media/`
folders; content is added later.
