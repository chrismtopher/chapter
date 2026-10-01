# Chapter Player for Audiobookshelf

A simple Raspberry Pi friendly Chapter player for Audiobookshelf.

Chapter Player for Audiobookshelf is an independent third-party project and is not affiliated with or supported by the Audiobookshelf project.

This prototype is a native Linux appliance app built with Python and GStreamer. It connects to an Audiobookshelf server with a user API token, shows a simple two-line OLED library and playback interface, starts playback sessions, resumes from Audiobookshelf progress, and syncs progress back while listening.

The target device is a small enclosure with a 2.08 inch SH1122 SPI OLED, two KY-040 rotary encoders, a MAX98357A I2S amp, and an internal speaker.

## Quick Install

Flash Raspberry Pi OS Lite onto a Raspberry Pi Zero 2 W/WH, enable SSH, and connect to the Pi. The recommended setup username is `chapter` and hostname is `chapter-player`.

Then run:

```bash
curl -fsSL https://raw.githubusercontent.com/chrismtopher/chapter/main/scripts/install-raspberry-pi.sh | bash
sudo reboot
```

The installer handles the software setup:

- system packages
- project clone/update in `/home/chapter/audiobookshelf-player`
- SPI enablement
- MAX98357A I2S audio and ALSA config
- setup web page service
- OLED service and boot splash
- port 80 setup-page proxy
- captive portal DNS helper
- Bluetooth unblock helper

For the complete hardware, flashing, wiring, setup, and troubleshooting walkthrough, see the [Raspberry Pi Zero 2 W install guide](docs/raspberry-pi-zero-2w-install.md).

## Hardware

Recommended build:

- Raspberry Pi Zero 2 WH, or Raspberry Pi Zero 2 W with a soldered 40-pin header
- 16 GB or larger microSD card
- 5 V power supply, ideally 2.5 A
- 2.08 inch 256x64 SH1122 SPI OLED
- Two KY-040 rotary encoder modules
- MAX98357A I2S mono amplifier breakout
- 4 ohm speaker
- Inline fuse on the USB-C 5 V positive lead
- Cross-connect wires for component wiring

The wiring tables are in the [install guide](docs/raspberry-pi-zero-2w-install.md#wire-the-hardware).

Purchase links for the recommended parts are in [docs/hardware-links.md](docs/hardware-links.md).

Printable case files are in [hardware/case](hardware/case).

## Setup

After installation and reboot, open the setup page from a phone or computer on the same network:

```text
http://chapter-player.local
```

If the player is not connected to Wi-Fi, it starts an open setup hotspot:

```text
Network:  Chapter-Setup
Password: none
Page:     http://10.42.0.1
```

The setup page lets you enter your Wi-Fi details and log the player into Audiobookshelf. Create a dedicated Audiobookshelf user for the player and restrict that user to the appropriate library or tags.

For a simple handout, see the [first boot one-sheet](docs/first-boot-one-sheet.md).

## Controls

- Turn the navigation knob to browse books.
- Click the navigation knob to select.
- Turn the volume knob to change volume.
- Click the volume knob to mute or unmute.
- Hold the volume knob for 10 seconds to show the setup address.
- Hold the navigation knob for 3 seconds to open the Bluetooth menu.
- In the Bluetooth menu, turn the navigation knob to choose `Enable`, `Disable`, `Pair`, `Unpair`, or `Back`, then click to select.
- To pair a speaker or headphones, put the device in pairing mode, choose `Pair`, wait for the device list, turn to the device name, and click to connect.

## Features

- Two-line SH1122 OLED library and playback UI
- Rotary encoder navigation and volume control
- Internal speaker playback through GStreamer
- Audiobookshelf login through the local setup page
- Admin web page player controls, including play/pause and volume
- Resume from Audiobookshelf progress
- Periodic progress sync back to Audiobookshelf
- Multi-file audiobook playback
- Continue/start-over prompt when a book has listening history
- Wi-Fi setup fallback hotspot
- Testable rotary/OLED menu state machine

## Development

Run the test suite with:

```bash
python3 -m unittest discover -s tests
```

See [docs/appliance-design.md](docs/appliance-design.md) for hardware notes, UI behavior, and future direction.

## License

This project is open source under the terms of the [MIT License](LICENSE).
