# Appliance Design

This project is aimed at a small kid-friendly audiobook appliance. The device should work on its own with a built-in speaker, while also supporting Sonos output when a room speaker is available.

## Recommended Hardware

### Core Device

- Lowest-cost target: Raspberry Pi Zero 2 W
- Easier development target: Raspberry Pi 4, 2GB RAM or better
- Raspberry Pi OS Lite
- 16GB or 32GB A1/A2 microSD card
- Good 5V power supply sized for the Pi, OLED, and speaker amp

Moving from a graphical touchscreen to a two-line OLED makes the Pi Zero 2 W realistic. A Pi 4 is still nicer while developing, but it is no longer required for the finished appliance.

### Display

- D-FLIFE 2.08 inch SH1122 SPI OLED
- 256x64 pixels
- 4-wire SPI
- 3.3V logic and power
- Two-line UI: title on top, context/action on bottom

This display changes the product shape: cover art should not be shown on-device. The app can still use Audiobookshelf cover metadata later for a web admin view or companion app.

### Controls

Use two KY-040 rotary encoder modules:

- Navigation encoder: browse books, choose continue/start-over, play/pause, chapter navigation confirmation.
- Volume encoder: turn for volume, short-click for mute/unmute, 10-second hold to show setup IP.

The KY-040 has `CLK`, `DT`, `SW`, `+`, and `GND` pins. Power each module from the Pi's 3.3V rail, not 5V, so its pull-ups never expose a Raspberry Pi GPIO input to 5V. If clockwise/counter-clockwise feels reversed after mounting, either swap `CLK` and `DT` or set the encoder's `reversed` flag in software.

### Internal Speaker

Use an I2S amplifier board rather than Bluetooth. I2S keeps the build self-contained and works cleanly even on Pi models with no analog audio jack.

Recommended parts:

- MAX98357A I2S mono amplifier breakout
- One Visaton FRWS 5 - 4 Ohm full-range speaker
- Small speaker grille or perforated enclosure area

For audiobook voice playback, one internal mono speaker is enough. A stereo I2S amp or bonnet is fine too, but it is not required.

### Speaker Chamber

Target a sealed chamber of about 0.2 to 0.35 liters net internal volume for the Visaton FRWS 5 - 4 Ohm. Bigger is fine if the enclosure allows it; smaller still works for speech, but it will sound thinner and more constrained.

Good internal dimensions:

- 70 mm x 70 mm x 45 mm = 0.22 liters
- 80 mm x 70 mm x 45 mm = 0.25 liters
- 80 mm x 80 mm x 50 mm = 0.32 liters

Keep the chamber empty except for the speaker and speaker wires. A small amount of acoustic damping material is okay if the chamber sounds boxy, but keep it away from the back of the speaker cone. Seal the speaker gasket and the wire pass-through.

### Sonos Output

Sonos should be treated as an optional network output, not as the system audio device.

The app should:

- Discover Sonos rooms with SoCo.
- Let a parent choose a default Sonos room.
- Start Audiobookshelf playback sessions as usual.
- Send Sonos a playable stream URL.
- Poll Sonos position and playback state.
- Sync progress back to Audiobookshelf.
- Fall back to the internal speaker when Sonos is unavailable.

## Playback Architecture

```text
Audiobookshelf API
    |
    | library, metadata, sessions, progress
    v
Kids Player UI
    |
    +-- OLED: SH1122 SPI two-line display
    |
    +-- Inputs: navigation encoder + volume encoder
    |
    +-- Local output: GStreamer -> I2S internal speaker
    |
    +-- Sonos output: SoCo -> Sonos room pulls stream URL
```

## Two-Line UI

### Library

```text
Top:    audiobook title
Bottom: By author
```

Turn the navigation encoder to move through titles. Click to open the selected title.

### Continue or Start Over

```text
Top:    audiobook title
Bottom: > Continue
```

Show this screen only when the selected book has listening history. `Continue` is the default selection. Turn the navigation encoder to switch between `Continue` and `Start over`. Click to select. If the book has no listening history, selecting it starts from the beginning immediately.

### Playing

```text
Top:    audiobook title and time
Bottom: chapter, state, and action row
```

The bottom action row is ordered `Home | Prev | Play/Pause | Next`. The navigation encoder moves left and right through the row, stopping at the edges. Click to select the focused action. `Play/Pause` is focused by default when playback starts. `Prev` and `Next` ask for confirmation before seeking.

If the top title/time line is too long for the OLED, scroll it horizontally while the book is playing. Keep the bottom action row stable so the selected action does not move under the user's focus.

### Chapter Confirmation

```text
Top:    audiobook title
Bottom: Go Ch 4? Yes
```

Turn the navigation encoder to switch between `Yes` and `No`. Click to confirm.

### Volume

The volume encoder is global:

- Turn clockwise: volume up
- Turn counter-clockwise: volume down
- Short click: mute/unmute
- Hold for 10 seconds: show the setup web page IP address on the OLED for 5 seconds

The long hold should not also toggle mute.

When volume is adjusted, replace the current OLED screen with a temporary volume overlay:

```text
Top:    Volume
Bottom: graphical fill bar from 0-100%
```

The overlay should update on every volume step, then return to the previous screen after a short timeout.
Each additional volume adjustment refreshes the timeout, so the overlay remains visible for a few seconds after the user stops turning the knob.

## Suggested GPIO Pinout

This pinout avoids the I2S pins commonly used by a MAX98357A-style amplifier.

| Part | Signal | GPIO | Physical Pin |
| --- | --- | ---: | ---: |
| OLED | VCC | 3.3V | 1 |
| OLED | GND | GND | 6 |
| OLED | SCLK | GPIO11/SCLK | 23 |
| OLED | SDIN/MOSI | GPIO10/MOSI | 19 |
| OLED | CS | GPIO8/CE0 | 24 |
| OLED | DC | GPIO24 | 18 |
| OLED | RES | GPIO25 | 22 |
| Nav KY-040 | + | 3.3V | 1 |
| Nav KY-040 | GND | GND | 9 |
| Nav KY-040 | CLK | GPIO5 | 29 |
| Nav KY-040 | DT | GPIO6 | 31 |
| Nav KY-040 | SW | GPIO13 | 33 |
| Volume KY-040 | + | 3.3V | 17 |
| Volume KY-040 | GND | GND | 14 |
| Volume KY-040 | CLK | GPIO12 | 32 |
| Volume KY-040 | DT | GPIO16 | 36 |
| Volume KY-040 | SW | GPIO26 | 37 |
| I2S amp | BCLK | GPIO18 | 12 |
| I2S amp | LRCLK | GPIO19 | 35 |
| I2S amp | DIN | GPIO21 | 40 |

The two KY-040 modules can share 3.3V and ground rails. The code also enables Raspberry Pi internal pull-ups; this is harmless when the KY-040 module already has pull-ups, provided the module is powered from 3.3V.

## USB-C Power And Data

Use the Adafruit USB-C breakout as the appliance's rear USB-C service/power port. Wire it to the Raspberry Pi Zero 2 WH's 5V/GND and USB data test pads.

| Adafruit USB-C breakout | Raspberry Pi Zero 2 WH | Notes |
| --- | --- | --- |
| VBUS | 5V header pin 2 or 4, or 5V test pad | Add a 1.5-2A polyfuse if possible. |
| GND | GND header pin 6, or GND test pad | Tie USB shield to ground through the breakout's normal mounting/ground if provided. |
| D+ | `USB_DP` test pad | Keep short and route beside D-. |
| D- | `USB_DM` test pad | Keep short and route beside D+. |
| CC | no connection | Breakout already has the needed USB-C CC resistors. |
| SBU | no connection | Not needed for USB 2.0. |

Keep the D+/D- pair short, similar length, and away from the speaker amp wiring. For a printed enclosure, twisted 30 AWG wire-wrap wire or a short USB 2.0 pigtail works better than long loose hookup wires.

Recommended fuse options:

- Bourns `MF-MSMF150-2`, 1.5A hold / 3A trip, 6V, 1812 SMD
- Littelfuse `1812L150ZR`, 1.5A hold / 3A trip, 8V, 1812 SMD
- Prototype inline fuse: [Amazon ASIN B0813Q4S6P](https://www.amazon.com/dp/B0813Q4S6P)

Wire the fuse in series with USB-C `VBUS`, before the Pi and amplifier:

```text
USB-C VBUS -> fuse -> optional power switch -> Pi 5V / amp 5V
USB-C GND  -> Pi GND / amp GND
```

Do not put the fuse in series with `GND`, `D+`, or `D-`.

The lower-right hole in the front cover is for a 3 mm warm-white power indicator. Insert the LED from the back and hold it in place with a small dab of hot glue. Splice it as a parallel branch across fused 5 V and ground between the USB-C port and Pi; never put the LED in series with the Pi's supply. The indicator lights immediately when USB power is present, before the OLED service is ready.

The specified [Dioramo 13240](https://dioramo.com/products/13240) is rated for 5-6 V and includes its current-limiting resistor. Connect its white-marked anode wire directly to fused 5 V and its black cathode wire to ground; no additional resistor is required.

This gives the appliance one USB-C port for power and USB 2.0 data/device access. The Pi Zero 2 WH has only one USB OTG data port, so avoid using the original micro-USB data port at the same time. If plugging into a computer for service access, configure the Pi for USB gadget mode, such as USB Ethernet/SSH. If plugging into only a charger, it will simply power the appliance.

## Sonos Stream Strategy

Start with direct Audiobookshelf stream URLs:

```text
Sonos -> https://audiobookshelf.example.com/s/item/.../track.mp3?token=...
```

If direct playback is unreliable because of auth, TLS, redirects, or media format behavior, add a local proxy on the Pi:

```text
Sonos -> http://raspberrypi.local:47831/stream/session-id/track-index
Pi proxy -> Audiobookshelf with Authorization header
```

The proxy approach is more work, but it gives the appliance control over authentication, track transitions, and supported stream responses.

## Setup Web Page

The player exposes a local setup page on port `47831`. The appliance can also install a port `80` proxy so people can browse without typing a port:

```text
http://raspberrypi.local
```

On boot, the setup service should run with Wi-Fi fallback enabled:

```bash
python3 -m abs_kids_player.setup_server --ensure-wifi
```

This depends on NetworkManager's `nmcli`. In the finished appliance, run it as a system service with permission to manage Wi-Fi.

For the prototype, install the user systemd service in `deploy/audiobookshelf-player-setup.service` and enable lingering so the setup page starts after reboot without an SSH session.

If no Wi-Fi connection is active, the player starts a temporary setup hotspot:

```text
Network:  Chapter-Setup
Password: none
Page:     http://10.42.0.1
```

While the hotspot is active, the OLED should show:

```text
Top:    Connect to Chapter-Setup
Bottom: Browse to http://10.42.0.1
```

The setup page accepts home Wi-Fi credentials. After submitting, the player waits briefly so the browser can receive the response, then asks NetworkManager to join the selected Wi-Fi network.

The setup hotspot should be an open network. To improve captive portal behavior, install the NetworkManager dnsmasq shared-mode config from `deploy/audiobookshelf-player-captive-portal-dnsmasq.conf`. It resolves HTTP browser traffic on the setup hotspot to `10.42.0.1`, and the port `80` proxy returns the setup page for arbitrary HTTP GET paths. This should trigger captive portal prompts on many phones and laptops. HTTPS sites cannot be transparently redirected, so the OLED still shows the direct setup URL as a reliable fallback.

The page logs the player into Audiobookshelf with the selected user's username and password. The password is not stored. The player persists:

- Audiobookshelf server URL
- Returned user token
- Optional or resolved library ID

This lets a parent change which Audiobookshelf user the appliance uses without attaching a keyboard and display to the Pi.

To reveal the address without a monitor, hold the volume knob for 10 seconds while the unit is powered on. The OLED should show the setup URL, such as `http://192.168.1.42`, for 5 seconds and then return to the previous screen.

The main setup page should show whether the setup server is running, whether Wi-Fi is connected and which SSID is active, and whether the saved Audiobookshelf login can successfully reach the server. The `/health` route can show the same status as a convenience.

## Software Backlog

1. Add an output backend interface with `play`, `pause`, `seek`, `stop`, `current_time`, and `sync_progress`.
2. Move the current GStreamer controller behind a `LocalSpeakerBackend`.
3. Add a `SonosBackend` using SoCo discovery and `play_uri`.
4. Wire `ApplianceMenu` to `Sh1122Display` and `RotaryEncoderInputs`.
5. Validate SH1122 byte order and contrast on the physical OLED.
6. Add local proxy support if direct Sonos playback cannot handle Audiobookshelf URLs reliably.
7. Add a parent-only settings path for output mode, Sonos room selection, and re-login.
8. Add a boot-time health check that verifies internal audio output and Sonos reachability.

## Enclosure Notes

- Keep the speaker chamber separate from the Pi where possible.
- Leave airflow around the Pi and amplifier.
- Put the OLED and both encoders on the front face.
- Keep ports reachable for service, but hide them from everyday use.
- Add a small service hatch for the microSD card if possible.

## Render Reference

Use the current 3D printed prototype as the visual reference for future renders:

- Matte white PLA body with visible fine print texture.
- Warm tan/brown printed knobs with ridged/scalloped edges and textured top faces.
- Large navigation knob on the lower-right/front, smaller volume knob above it.
- OLED window on the upper-left/front with a black recessed display area and rounded rectangular cutout.
- Small 3 mm power-indicator opening at the lower-right of the front cover.
- Speaker grille on the lower-left/front, made from a dense grid of round holes.
- Matching side ventilation/speaker-style hole grid on the right side panel.
- Soft rounded outer corners and a gently rounded front perimeter.
- Top shell has an embossed/recessed `chapter` wordmark.
- Keep the render grounded as a real printed object, not a perfectly smooth injection-molded product.

## References

- SH1122 OLED module specs: https://www.displaymodule.com/products/2-08-inch-oled-graphic-monochrome-display-256x64-with-spi
- KY-040 rotary encoder module reference: https://componentindex.net/components/rotary-encoder/
- KY-040 Raspberry Pi wiring reference: https://sensorkit.joy-it.net/en/sensors/ky-040
- SoCo API docs: https://docs.python-soco.com/en/v0.28.0/api/soco.core.html
