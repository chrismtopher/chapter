# Appliance Design

This project is a small kid-friendly audiobook appliance. The released build works on its own with a built-in speaker and can optionally send audio to a paired Bluetooth speaker or headphones. Sonos and AirPlay output are not currently implemented.

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

Use two KY-040 rotary encoder modules, labeled `Select` and `Volume` on the case:

- Select knob: browse books, choose continue/start-over, play/pause, and confirm chapter navigation.
- Volume knob: turn for volume, short-click for mute/unmute, and hold for 10 seconds to show the setup IP.

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
    +-- Inputs: Select knob + Volume knob
    |
    +-- Local output: GStreamer -> I2S internal speaker
    |
    +-- Optional output: paired Bluetooth speaker or headphones
```

## Two-Line UI

### Library

```text
Top:    audiobook title
Bottom: By author
```

Turn the Select knob to move through titles. Click it to open the selected title.

### Continue or Start Over

```text
Top:    audiobook title
Bottom: Home | Continue | Start over
```

When the selected book has listening history, `Continue` is the default selection. Turn the Select knob to move between `Home`, `Continue`, and `Start over`, then click to choose. If the book has no listening history, show only `Home` and `Start`.

### Playing

```text
Top:    scrolling chapter title with remaining time at the upper-right
Bottom: Home | Prev | Play/Pause | Next
```

The Select knob moves left and right through the action row, stopping at the edges. Click it to choose the focused action. `Play/Pause` is focused by default when playback starts. `Prev` and `Next` ask for confirmation before changing chapters. Returning to `Home` while audio continues playing automatically returns to this playback screen after five seconds without input.

Long chapter titles scroll horizontally while the remaining-time display and bottom action row stay fixed.

### Chapter Confirmation

```text
Top:    Are you sure you want to listen to the previous/next chapter?
Bottom: Yes | No
```

Turn the Select knob to switch between `Yes` and `No`. Click to confirm. The prompt returns to the playback screen after five seconds without input.

### Volume

The Volume knob is global:

- Turn clockwise: volume up
- Turn counter-clockwise: volume down
- Short click: mute/unmute
- Hold for 10 seconds: show the setup web page IP address on the OLED for 5 seconds

The long hold should not also toggle mute.

When volume is adjusted, replace the current OLED screen with a temporary volume overlay:

```text
Top:    Volume, or Muted at zero
Bottom: rounded graphical fill bar
```

The overlay should update on every volume step, then return to the previous screen after a short timeout.
Each additional volume adjustment refreshes the timeout, so the overlay remains visible for a few seconds after the user stops turning the knob.

## Suggested GPIO Pinout

This pinout avoids the I2S pins used by the MAX98357A amplifier. `GPIO` values use BCM numbering; `Physical Pin` values identify positions on the 40-pin header.

| Part | Signal | GPIO | Physical Pin |
| --- | --- | ---: | ---: |
| OLED | VCC | 3.3V | 1 |
| OLED | GND | GND | 6 |
| OLED | SCLK | GPIO11/SCLK | 23 |
| OLED | SDIN/MOSI | GPIO10/MOSI | 19 |
| OLED | CS | GPIO8/CE0 | 24 |
| OLED | DC | GPIO24 | 18 |
| OLED | RES | GPIO25 | 22 |
| Select knob KY-040 | + | 3.3V | 1 |
| Select knob KY-040 | GND | GND | 9 |
| Select knob KY-040 | CLK | GPIO5 | 29 |
| Select knob KY-040 | DT | GPIO6 | 31 |
| Select knob KY-040 | SW | GPIO13 | 33 |
| Volume knob KY-040 | + | 3.3V | 17 |
| Volume knob KY-040 | GND | GND | 14 |
| Volume knob KY-040 | CLK | GPIO12 | 32 |
| Volume knob KY-040 | DT | GPIO16 | 36 |
| Volume knob KY-040 | SW | GPIO26 | 37 |
| I2S amp | VIN | 5V | 2 or 4 |
| I2S amp | GND | GND | Any available GND pin |
| I2S amp | BCLK | GPIO18 | 12 |
| I2S amp | LRCLK | GPIO19 | 35 |
| I2S amp | DIN | GPIO21 | 40 |
| I2S amp | SD | Not connected | - |
| Speaker | + / - | I2S amp speaker output | - |

The two KY-040 modules can share 3.3V and ground rails. The code also enables Raspberry Pi internal pull-ups; this is harmless when the KY-040 module already has pull-ups, provided the module is powered from 3.3V.

The MAX98357A speaker output is differential. Connect the speaker only between the amplifier's `+` and `-` speaker terminals; never connect either speaker terminal to Raspberry Pi ground. Leave the amplifier `SD` pad disconnected in the released build.

## USB-C Power

Use the Adafruit 5993 vertical USB-C breakout as the appliance's rear power port. Chapter uses this connector for power only; leave `D+`, `D-`, `CC`, and `SBU` unwired.

For power, solder the positive lead to either Adafruit 5993 pad labeled `VBUS` and the negative lead to either pad labeled `GND`. Its two breakout rows duplicate the same connections, so either matching pair may be used. `VBUS` carries raw USB 5 V. Use red wire for `VBUS` and black wire for `GND`, and do not use the `CC`, `SBU`, `D+`, or `D-` pads as power connections.

| Adafruit 5993 pad | Raspberry Pi Zero 2 WH | Notes |
| --- | --- | --- |
| `VBUS` (+5 V) | 5V header pin 2 or 4, or 5V test pad | Positive power lead; install a 1.5 A fuse in series. |
| `GND` (-) | GND header pin 6, or GND test pad | Negative power lead; connect to the Pi and amplifier common ground. |

Recommended fuse options:

- Bourns `MF-MSMF150-2`, 1.5A hold / 3A trip, 6V, 1812 SMD
- Littelfuse `1812L150ZR`, 1.5A hold / 3A trip, 8V, 1812 SMD
- Inline holder: [Amazon ASIN B0813Q4S6P](https://www.amazon.com/dp/B0813Q4S6P), fitted with the included 1.5 A fast-blow 5x20 mm fuse

Wire the fuse in series with USB-C `VBUS`, before the Pi and amplifier:

```text
USB-C VBUS -> 1.5 A fuse -> optional power switch -> Pi 5V / amp 5V
USB-C GND  -> Pi GND / amp GND
```

Do not put the fuse in series with `GND`, `D+`, or `D-`.

Adafruit specifies this breakout arrangement for 5 V at up to 1.5 A. Raspberry Pi recommends a 2 A-capable supply for the Zero 2 W, so the tested 5993 is the limiting part of this power path. If Chapter reports undervoltage, reboots at high volume, or behaves unreliably, replace the input path with a regulated 5 V solution rated for at least 2 A.

Powering through a 5 V header pin bypasses the Pi's normal input protection. Verify polarity and voltage before connecting power, and never power the appliance through the 5993 and the Pi's original `PWR IN` micro-USB port simultaneously.

The lower-right hole in the front cover is for a 3 mm warm-white power indicator. Insert the LED from the back and hold it in place with a small dab of hot glue. Splice it as a parallel branch across fused 5 V and ground between the USB-C port and Pi; never put the LED in series with the Pi's supply. The indicator lights immediately when USB power is present, before the OLED service is ready.

The specified [Dioramo 13240](https://dioramo.com/products/13240) is rated for 5-6 V and includes its current-limiting resistor. Connect its white-marked anode wire directly to fused 5 V and its black cathode wire to ground; no additional resistor is required.

The USB-C connector supplies power only. Continue to use Wi-Fi or the Pi's original USB data port for servicing the appliance.

## Setup Web Page

The player exposes a local setup page on port `47831`. The appliance can also install a port `80` proxy so people can browse without typing a port:

```text
http://raspberrypi.local
```

On boot, the setup service should run with Wi-Fi fallback enabled:

```bash
python3 -m abs_kids_player.setup_server --ensure-wifi
```

This depends on NetworkManager's `nmcli`. The automated installer installs the setup page as a root-owned system service so it can manage Wi-Fi and start after reboot without an SSH session.

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
- Returned access and refresh tokens
- Audiobookshelf username
- Resolved library ID

This lets a parent change which Audiobookshelf user the appliance uses without attaching a keyboard and display to the Pi.

To reveal the address without a monitor, hold the Volume knob for 10 seconds while the unit is powered on. The OLED should show the setup URL, such as `http://192.168.1.42`, for 5 seconds and then return to the previous screen.

The web interface shows separate status rows for Wi-Fi, Audiobookshelf, Bluetooth, and current playback. Its System tab shows the installed version, available software updates, reboot control, and device-reset control. The `/health` route exposes machine-readable status for diagnostics.

## Enclosure Notes

- Keep the speaker chamber separate from the Pi where possible.
- Leave airflow around the Pi and amplifier.
- Put the OLED, speaker grille, wordmark, and power indicator on the front cover.
- Mount the two rotary encoders on the top panel and label them `SELECT` and `VOLUME`.
- Keep ports reachable for service, but hide them from everyday use.
- Add a small service hatch for the microSD card if possible.

## Render Reference

Use the current 3D printed prototype as the visual reference for future renders:

- Matte off-white PLA body and front cover with visible fine print texture.
- Warm tan/brown printed knobs with ridged/scalloped edges and textured top faces.
- Two similarly sized, low-profile knobs on the top panel: `SELECT` on the left and `VOLUME` on the right.
- OLED window on the upper-left/front with a black recessed display area and rounded rectangular cutout.
- Lowercase `chapter` wordmark in warm brown on the upper-right/front.
- Small 3 mm power-indicator opening at the lower-right of the front cover.
- Speaker grille on the lower-left/front, made from a dense grid of round holes.
- Matching side ventilation/speaker-style hole grid on the right side panel.
- Soft rounded outer corners and a gently rounded front perimeter.
- Keep the render grounded as a real printed object, not a perfectly smooth injection-molded product.

## References

- SH1122 OLED module specs: https://www.displaymodule.com/products/2-08-inch-oled-graphic-monochrome-display-256x64-with-spi
- KY-040 rotary encoder module reference: https://componentindex.net/components/rotary-encoder/
- KY-040 Raspberry Pi wiring reference: https://sensorkit.joy-it.net/en/sensors/ky-040
- Adafruit MAX98357A Raspberry Pi wiring: https://learn.adafruit.com/adafruit-max98357-i2s-class-d-mono-amp/raspberry-pi-wiring
- Adafruit 5993 USB-C breakout: https://www.adafruit.com/product/5993
