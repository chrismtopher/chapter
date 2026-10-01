# Raspberry Pi Zero 2 W Install Guide

This guide walks through building a fresh Chapter Player for Audiobookshelf on a Raspberry Pi Zero 2 W or Zero 2 WH.

It assumes you already have an Audiobookshelf server running somewhere on your network or reachable by URL. The player stores an Audiobookshelf user token, so create a dedicated Audiobookshelf user for the player instead of using an admin account.

## What To Buy

- Raspberry Pi Zero 2 WH, or a Raspberry Pi Zero 2 W plus a soldered 40-pin header.
- 16 GB or larger microSD card. Raspberry Pi OS Lite fits on less, but 16 GB or 32 GB gives you room for updates and logs.
- Good 5 V power supply. Use at least a 2 A supply; 2.5 A is safer with the OLED and speaker amp.
- 2.08 inch 256x64 SH1122 SPI OLED module.
- Two KY-040 rotary encoder modules.
- MAX98357A I2S mono amplifier breakout.
- 4 ohm speaker.
- Jumper wires or soldered wiring, plus an enclosure.

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

## Update The Pi

```bash
sudo apt update
sudo apt full-upgrade -y
sudo reboot
```

Reconnect after the reboot:

```bash
ssh chapter@chapter-player.local
```

## Install System Packages

```bash
sudo apt update
sudo apt install -y git curl avahi-daemon rfkill gpiod fonts-dejavu-core \
  python3-pil python3-spidev python3-gpiozero python3-lgpio \
  alsa-utils gstreamer1.0-alsa python3-gi python3-gst-1.0 gir1.2-gstreamer-1.0 \
  gstreamer1.0-plugins-base gstreamer1.0-plugins-good gstreamer1.0-plugins-bad \
  gstreamer1.0-libav dnsmasq-base
```

Make sure the `chapter` user can use audio, GPIO, and SPI devices:

```bash
sudo usermod -aG audio,gpio,spi,i2c chapter
```

## Clone The Project

Use the GitHub URL for this repository:

```bash
cd /home/chapter
git clone git@github.com:chrismtopher/chapter.git audiobookshelf-player
cd /home/chapter/audiobookshelf-player
```

Check that Python can see the project:

```bash
python3 -m abs_kids_player.setup_server --help
python3 -m abs_kids_player.oled_service --help
```

## Enable SPI

The OLED uses SPI. Enable it with:

```bash
sudo raspi-config
```

Choose **Interface Options**, enable **SPI**, then exit.

You can also do this non-interactively:

```bash
sudo raspi-config nonint do_spi 0
```

Reboot so the group membership and SPI change both take effect:

```bash
sudo reboot
```

Reconnect and check for the SPI device:

```bash
ssh chapter@chapter-player.local
ls /dev/spidev*
groups
```

You should see `/dev/spidev0.0`, and `groups` should include `gpio`, `spi`, and `audio`.

## Wire The Hardware

Power the Pi off before wiring:

```bash
sudo shutdown -h now
```

Disconnect power, then wire the parts.

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

## Configure I2S Audio

Power the Pi back on and reconnect with SSH.

Back up the boot config:

```bash
sudo cp /boot/firmware/config.txt /boot/firmware/config.txt.bak
```

Edit the file:

```bash
sudo nano /boot/firmware/config.txt
```

If you see this line, comment it out:

```text
dtparam=audio=on
```

Add these lines near the end:

```text
dtoverlay=max98357a
dtoverlay=i2s-mmap
```

Create `/etc/asound.conf`:

```bash
sudo nano /etc/asound.conf
```

Paste:

```text
pcm.speakerbonnet {
   type hw
   card 0
}

pcm.!default {
   type plug
   slave.pcm "dmixer"
}

pcm.dmixer {
   type dmix
   ipc_key 1024
   ipc_perm 0666
   slave {
     pcm "speakerbonnet"
     period_time 0
     period_size 1024
     buffer_size 8192
     rate 44100
     channels 2
   }
}

ctl.dmixer {
  type hw
  card 0
}
```

Reboot:

```bash
sudo reboot
```

Check that ALSA sees the amp:

```bash
aplay -l
speaker-test -t wav -c 2
```

Press `Ctrl+C` to stop the speaker test.

## Test The OLED

From the project directory:

```bash
cd /home/chapter/audiobookshelf-player
python3 -m abs_kids_player.oled_test
```

The display should briefly turn all pixels on, then show a few text screens. If the screen is blank, power off and re-check `VCC`, `GND`, `CLK`, `DIN`, `CS`, `DC`, and `RES`.

## Install The Services

Install the setup web page, OLED service, boot splash, port 80 proxy, Bluetooth unblock helper, and captive portal DNS config:

```bash
cd /home/chapter/audiobookshelf-player

sudo install -m 0644 deploy/audiobookshelf-player-boot-splash.service /etc/systemd/system/
sudo install -m 0644 deploy/audiobookshelf-player-oled.service /etc/systemd/system/
sudo install -m 0644 deploy/audiobookshelf-player-setup-system.service /etc/systemd/system/audiobookshelf-player-setup.service
sudo install -m 0644 deploy/audiobookshelf-player-bluetooth-unblock.service /etc/systemd/system/

sudo install -m 0755 deploy/audiobookshelf-player-port80-proxy /usr/local/sbin/audiobookshelf-player-port80-proxy
sudo install -m 0644 deploy/audiobookshelf-player-port80-forward.service /etc/systemd/system/

sudo mkdir -p /etc/NetworkManager/dnsmasq-shared.d
sudo install -m 0644 deploy/audiobookshelf-player-captive-portal-dnsmasq.conf /etc/NetworkManager/dnsmasq-shared.d/audiobookshelf-player-captive-portal.conf

sudo systemctl daemon-reload
sudo systemctl enable audiobookshelf-player-boot-splash.service
sudo systemctl enable audiobookshelf-player-oled.service
sudo systemctl enable audiobookshelf-player-setup.service
sudo systemctl enable audiobookshelf-player-port80-forward.service
sudo systemctl enable audiobookshelf-player-bluetooth-unblock.service
sudo reboot
```

After reboot, the OLED should show `chapter` and then either the setup address, the setup hotspot instructions, or the library home screen.

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

## Check Service Status

```bash
systemctl status audiobookshelf-player-setup.service
systemctl status audiobookshelf-player-oled.service
systemctl status audiobookshelf-player-port80-forward.service
journalctl -u audiobookshelf-player-setup.service -n 80
tail -n 80 /home/chapter/audiobookshelf-player-oled.log
```

The setup page health endpoint should also respond:

```bash
curl http://localhost:47831/health
curl http://localhost/health
```

## Using The Player

- Turn the navigation knob to browse books.
- Click the navigation knob to select.
- Turn the volume knob to change volume.
- Click the volume knob to mute or unmute.
- Hold the volume knob for 10 seconds to show the setup address.

## Updating Later

```bash
cd /home/chapter/audiobookshelf-player
git pull
sudo systemctl restart audiobookshelf-player-setup.service
sudo systemctl restart audiobookshelf-player-oled.service
```

If service files changed, reinstall them with the commands in the service section.

## Troubleshooting

### SSH Does Not Connect

Make sure the Pi was flashed with SSH enabled, the hostname is `chapter-player`, and the Wi-Fi network is 2.4 GHz. If `.local` does not work, use the IP address from your router.

### OLED Is Blank

Run:

```bash
ls /dev/spidev*
groups
python3 -m abs_kids_player.oled_test
```

If `/dev/spidev0.0` is missing, SPI is not enabled. If `groups` does not include `spi` and `gpio`, re-run the `usermod` command and reboot.

### No Sound

Run:

```bash
aplay -l
speaker-test -t wav -c 2
```

If there is no sound card, re-check `/boot/firmware/config.txt` and the I2S wiring. If there is a sound card but no audio, re-check the speaker wires and MAX98357A `VIN` and `GND`.

### Setup Page Does Not Open

Run:

```bash
systemctl status audiobookshelf-player-setup.service
curl http://localhost:47831/health
```

If the direct port works but `http://chapter-player.local` does not, check:

```bash
systemctl status audiobookshelf-player-port80-forward.service
```

### The Pi Shows The Setup Hotspot Instead Of Joining Wi-Fi

Connect to `Chapter-Setup`, open `http://10.42.0.1`, and enter the home Wi-Fi credentials. The setup page uses NetworkManager to switch from the hotspot to the selected Wi-Fi network.

## References

- Raspberry Pi getting started guide: https://www.raspberrypi.com/documentation/computers/getting-started.html
- Raspberry Pi Zero 2 W hardware information: https://www.raspberrypi.com/documentation/computers/raspberry-pi.html
- Raspberry Pi configuration guide: https://www.raspberrypi.com/documentation/computers/configuration.html
- Adafruit MAX98357A Raspberry Pi setup: https://learn.adafruit.com/adafruit-max98357-i2s-class-d-mono-amp/raspberry-pi-usage
