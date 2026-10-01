# Raspberry Pi Zero 2 W Install Guide

This guide walks through building a fresh Chapter Player for Audiobookshelf on a Raspberry Pi Zero 2 W or Zero 2 WH.

It assumes you already have an Audiobookshelf server running somewhere on your network or reachable by URL. The player stores an Audiobookshelf user token, so create a dedicated Audiobookshelf user for the player instead of using an admin account.

The software setup is handled by the installer. This guide covers the parts a new builder still needs: buying parts, flashing Raspberry Pi OS Lite, wiring the hardware, running the installer, opening the setup page, and troubleshooting.

## What To Buy

- Raspberry Pi Zero 2 WH, or a Raspberry Pi Zero 2 W plus a soldered 40-pin header.
- 16 GB or larger microSD card. Raspberry Pi OS Lite fits on less, but 16 GB or 32 GB gives you room for updates and logs.
- Good 5 V power supply. Use at least a 2 A supply; 2.5 A is safer with the OLED and speaker amp.
- 2.08 inch 256x64 SH1122 SPI OLED module.
- Two KY-040 rotary encoder modules.
- MAX98357A I2S mono amplifier breakout.
- 4 ohm speaker.
- Jumper wires or soldered wiring, plus an enclosure.

For links to the recommended parts, see the [hardware links](hardware-links.md).

The Pi Zero 2 W Wi-Fi radio is 2.4 GHz only. Use a 2.4 GHz network during setup.

## Flash Raspberry Pi OS

1. Install Raspberry Pi Imager on your computer.
2. Insert the microSD card.
3. In Imager, choose the Pi model and select **Raspberry Pi OS Lite**.
4. Open OS customisation before writing the card.
5. Set the hostname to `chapter-player`.
6. Set the username to `chapter`.
7. Set a password you will remember.
8. Configure your 2.4 GHz Wi-Fi network and country.
9. Enable SSH.
10. Write the card, insert it into the Pi, and power the Pi.

Wait a few minutes for the first boot. Then connect from your computer:

```bash
ssh chapter@chapter-player.local
```

If `.local` does not resolve on your network, find the Pi's IP address from your router and use:

```bash
ssh chapter@192.168.1.42
```

## Run The Installer

Run this on the Pi:

```bash
curl -fsSL https://raw.githubusercontent.com/chrismtopher/chapter/main/scripts/install-raspberry-pi.sh | bash
```

The installer handles the software setup:

- installs required system packages
- creates or updates the `chapter` service user
- clones or updates the project in `/home/chapter/audiobookshelf-player`
- enables SPI for the OLED
- configures the MAX98357A I2S audio overlay
- installs the ALSA mixer config
- installs and enables the setup page service
- installs and enables the OLED service and boot splash
- installs the port 80 setup-page proxy
- installs the captive portal DNS helper
- installs the Bluetooth unblock helper

When it finishes, it will tell you to reboot. If you have not wired the hardware yet, shut the Pi down instead:

```bash
sudo shutdown -h now
```

If the hardware is already wired, reboot:

```bash
sudo reboot
```

To inspect the installer before running it:

```bash
curl -fsSLO https://raw.githubusercontent.com/chrismtopher/chapter/main/scripts/install-raspberry-pi.sh
less install-raspberry-pi.sh
bash install-raspberry-pi.sh
```

## Wire The Hardware

Power the Pi off before wiring. Disconnect power, then wire the parts.

### OLED

| OLED Pin | Raspberry Pi Signal | Physical Pin |
| --- | --- | ---: |
| `VCC` | 3.3 V | 1 |
| `GND` | GND | 6 |
| `SCL` / `CLK` | GPIO11 / SCLK | 23 |
| `SDA` / `DIN` | GPIO10 / MOSI | 19 |
| `CS` | GPIO8 / CE0 | 24 |
| `DC` | GPIO24 | 18 |
| `RES` / `RST` | GPIO25 | 22 |

### Navigation Encoder

Power the KY-040 from 3.3 V, not 5 V.

| KY-040 Pin | Raspberry Pi Signal | Physical Pin |
| --- | --- | ---: |
| `+` | 3.3 V | 1 |
| `GND` | GND | 9 |
| `CLK` | GPIO5 | 29 |
| `DT` | GPIO6 | 31 |
| `SW` | GPIO13 | 33 |

### Volume Encoder

| KY-040 Pin | Raspberry Pi Signal | Physical Pin |
| --- | --- | ---: |
| `+` | 3.3 V | 17 |
| `GND` | GND | 14 |
| `CLK` | GPIO12 | 32 |
| `DT` | GPIO16 | 36 |
| `SW` | GPIO26 | 37 |

### MAX98357A I2S Amp

| Amp Pin | Raspberry Pi Signal | Physical Pin |
| --- | --- | ---: |
| `VIN` | 5 V | 2 or 4 |
| `GND` | GND | 20, 25, 30, 34, or 39 |
| `BCLK` | GPIO18 | 12 |
| `LRC` / `LRCLK` | GPIO19 | 35 |
| `DIN` | GPIO21 | 40 |
| `SD` / `SD_MODE` | Leave disconnected | - |
| Speaker `+` / `-` | Speaker terminals | - |

The default software leaves `SD` / `SD_MODE` alone. That lets the breakout's own mode resistor choose the default mono mix.

## First Boot

After the installer has run and the hardware is wired, power the Pi on.

On boot, the OLED should show `chapter` and then one of these:

- setup page address
- setup hotspot instructions
- library home screen

The installer starts the setup page and OLED services automatically on boot.

## Open The Setup Page

If the Pi is on your Wi-Fi, open one of these from a phone or computer on the same network:

```text
http://chapter-player.local
http://<the-pi-ip-address>
```

The setup page also runs directly on port `47831`:

```text
http://chapter-player.local:47831
```

If the Pi is not connected to Wi-Fi, the setup service should start an open setup hotspot:

```text
Network:  Chapter-Setup
Password: none
Page:     http://10.42.0.1
```

Connect a phone or laptop to `Chapter-Setup`, then open `http://10.42.0.1`.

## Connect Audiobookshelf

On the setup page, enter:

- Audiobookshelf server URL, for example `https://books.example.com`.
- Username for the dedicated player user.
- Password for that user.

The password is sent to Audiobookshelf once. The player stores the returned user token, not the password.

If no library is selected, the player uses the user's default audiobook library or the first accessible audiobook library.

## Using The Player

- Turn the navigation knob to browse books.
- Click the navigation knob to select.
- Turn the volume knob to change volume.
- Click the volume knob to mute or unmute.
- Hold the volume knob for 10 seconds to show the setup address.

## Updating Later

Run the installer again:

```bash
curl -fsSL https://raw.githubusercontent.com/chrismtopher/chapter/main/scripts/install-raspberry-pi.sh | bash
sudo reboot
```

It updates the project checkout and refreshes the installed service files.

## Troubleshooting

### SSH Does Not Connect

Make sure the Pi was flashed with SSH enabled, the hostname is `chapter-player`, and the Wi-Fi network is 2.4 GHz. If `.local` does not work, use the IP address from your router.

### OLED Is Blank

Check that SPI exists and that the `chapter` user has device permissions:

```bash
ls /dev/spidev*
groups chapter
```

Run the OLED test from the installed project:

```bash
cd /home/chapter/audiobookshelf-player
python3 -m abs_kids_player.oled_test
```

If `/dev/spidev0.0` is missing, rerun the installer and reboot. If the OLED test still stays blank, power off and re-check `VCC`, `GND`, `CLK`, `DIN`, `CS`, `DC`, and `RES`.

### No Sound

Check that ALSA sees the amp:

```bash
aplay -l
speaker-test -t wav -c 2
```

Press `Ctrl+C` to stop the speaker test.

If there is no sound card, rerun the installer and reboot. If there is a sound card but no audio, re-check the speaker wires and MAX98357A `VIN` and `GND`.

### Setup Page Does Not Open

Check the setup service and health endpoint:

```bash
systemctl status audiobookshelf-player-setup.service
curl http://localhost:47831/health
```

If the direct port works but `http://chapter-player.local` does not, check the port 80 proxy:

```bash
systemctl status audiobookshelf-player-port80-forward.service
curl http://localhost/health
```

### The Pi Shows The Setup Hotspot Instead Of Joining Wi-Fi

Connect to `Chapter-Setup`, open `http://10.42.0.1`, and enter the home Wi-Fi credentials. The setup page uses NetworkManager to switch from the hotspot to the selected Wi-Fi network.

### View Service Logs

```bash
journalctl -u audiobookshelf-player-setup.service -n 80
journalctl -u audiobookshelf-player-oled.service -n 80
tail -n 80 /home/chapter/audiobookshelf-player-oled.log
```

## References

- Raspberry Pi getting started guide: https://www.raspberrypi.com/documentation/computers/getting-started.html
- Raspberry Pi Zero 2 W hardware information: https://www.raspberrypi.com/documentation/computers/raspberry-pi.html
- Raspberry Pi configuration guide: https://www.raspberrypi.com/documentation/computers/configuration.html
- Adafruit MAX98357A Raspberry Pi setup: https://learn.adafruit.com/adafruit-max98357-i2s-class-d-mono-amp/raspberry-pi-usage
