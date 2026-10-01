# Chapter Player for Audiobookshelf

A simple Raspberry Pi friendly Chapter player for Audiobookshelf.

Chapter Player for Audiobookshelf is an independent third-party project and is not affiliated with or supported by the Audiobookshelf project.

This prototype is a native Linux app built with Python, GTK 4, and GStreamer. It connects to an Audiobookshelf server with a user API token, shows large cover-art tiles, starts playback sessions, resumes from Audiobookshelf progress, and syncs progress back while listening.

The appliance target is a small enclosure with a 2.08 inch SH1122 SPI OLED, two KY-040 rotary encoder modules, an internal speaker for always-available playback, plus optional Sonos support for rooms that already have a speaker.

For a complete fresh Raspberry Pi Zero 2 W/WH build, see the [step-by-step install guide](docs/raspberry-pi-zero-2w-install.md).

After flashing Raspberry Pi OS Lite and connecting with SSH, the installer can perform the software setup:

```bash
curl -fsSL https://raw.githubusercontent.com/chrismtopher/chapter/main/scripts/install-raspberry-pi.sh | bash
sudo reboot
```

## Install on Raspberry Pi OS Lite

```bash
sudo apt update
sudo apt install -y git curl avahi-daemon network-manager rfkill gpiod fonts-dejavu-core \
  python3-pil python3-spidev python3-gpiozero python3-lgpio \
  alsa-utils gstreamer1.0-alsa python3-gi python3-gst-1.0 gir1.2-gstreamer-1.0 \
  gstreamer1.0-plugins-base gstreamer1.0-plugins-good gstreamer1.0-plugins-bad \
  gstreamer1.0-libav dnsmasq-base bluez
```

Enable SPI with `sudo raspi-config` before using the SH1122 OLED.

The original GTK prototype also needs `python3-gi-cairo` and `gir1.2-gtk-4.0`.

## Test the OLED

The setup web service does not draw to the OLED by itself. To verify the display wiring and SH1122 driver, run:

```bash
python3 -m abs_kids_player.oled_test
```

The test briefly turns all pixels on, then cycles through a few text screens. If it stays blank, check SPI and permissions:

```bash
ls /dev/spidev*
groups
gpioinfo | head
```

Expected display wiring:

- `SCL`/`CLK` -> GPIO11/SCLK, physical pin 23
- `SDA`/`DIN` -> GPIO10/MOSI, physical pin 19
- `CS` -> GPIO8/CE0, physical pin 24, controlled by the SPI driver
- `DC` -> GPIO24, physical pin 18
- `RES`/`RST` -> GPIO25, physical pin 22
- `VCC` -> 3.3V
- `GND` -> GND

## Start OLED On Boot

Install the early boot splash as a root system service. It writes the large `chapter` logo as soon as SPI is available, then exits and leaves the OLED on-screen while the Pi finishes booting:

```bash
sudo install -m 0644 deploy/audiobookshelf-player-boot-splash.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable audiobookshelf-player-boot-splash.service
```

The splash service retries SPI briefly inside the display process. It must not
depend on `systemd-udev-settle.service` or a `dev-spidev0.0.device` unit: either
can delay the first display update while unrelated hardware or a missing
systemd device event times out.

Install the OLED status service as an early system service running under the
`chapter` account:

```bash
systemctl --user disable --now audiobookshelf-player-oled.service 2>/dev/null || true
sudo install -m 0644 deploy/audiobookshelf-player-oled.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now audiobookshelf-player-oled.service
```

The OLED service starts without waiting for the rest of the user target. It
loads the last successful library from a user-scoped local cache, then refreshes
Audiobookshelf and Bluetooth status in the background. This keeps the home menu
responsive while Wi-Fi finishes reconnecting after a reboot.

The internal speaker is the immediate startup default. Normal playback does not
query or wait for Bluetooth; a confirmed background reconnect or an explicit
pairing action enables the Bluetooth audio sink afterward.

Check it:

```bash
systemctl status audiobookshelf-player-oled.service
journalctl -u audiobookshelf-player-oled.service -n 50
```

On boot, the OLED first shows `chapter`. If the setup hotspot is active or Wi-Fi is not connected, it shows `Connect to Chapter-Setup` and `Browse to http://10.42.0.1`. If Wi-Fi is connected and the player has an Audiobookshelf login saved, it loads the library home screen and shows the first audiobook title with `By <author>`. Long titles pause briefly, then scroll across the display. If Wi-Fi is connected but Audiobookshelf is not configured yet, it shows the setup page address for that network.

The OLED service also reads the volume KY-040 by default:

- `CLK` -> GPIO12, physical pin 32
- `DT` -> GPIO16, physical pin 36
- `SW` -> GPIO26, physical pin 37

Turning the knob changes system volume with `amixer`, clicking toggles mute, and holding for 10 seconds shows the setup address.

For the MAX98357 internal amp, leave `SD`/`SD_MODE` on its breakout default unless you add an isolated shutdown circuit. The appliance uses software mute plus a soft pause that keeps I2S audio alive with digital silence, which avoids the paused-amp hiss without pulling `SD` low. The OLED service still has an optional `--amp-shutdown-pin` flag for future hardware revisions, but it is not enabled by default.

To reduce MAX98357 pops when playback starts or resumes, keep the Raspberry Pi I2S output running through a fixed-rate ALSA mixer. Back up `/boot/firmware/config.txt`, add these lines, then reboot:

```text
dtoverlay=max98357a
dtoverlay=i2s-mmap
```

Create `/etc/asound.conf` with:

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

This follows Adafruit's MAX98357 Raspberry Pi I2S pop-reduction guidance: route default audio through `dmix` at a fixed `44100` Hz rate so the I2S bit clock does not change between playback starts.

## Run

```bash
python3 -m abs_kids_player
```

## First-Boot Wi-Fi Setup

Run the setup page with Wi-Fi fallback:

```bash
python3 -m abs_kids_player.setup_server --ensure-wifi
```

This uses NetworkManager's `nmcli`, the default Wi-Fi tool on current Raspberry Pi OS. If your user cannot create hotspots or change Wi-Fi, run this as the appliance system service or with appropriate NetworkManager permissions.

If the player is already connected to Wi-Fi, open this from a browser on the same network:

```text
http://raspberrypi.local
```

If the player is not connected to Wi-Fi, it starts a temporary setup hotspot:

```text
Network:  Chapter-Setup
Password: none
Page:     http://10.42.0.1
```

Connect to that network from a phone or laptop, open the page, and enter your home Wi-Fi name and password. The player will switch networks. Hold the volume knob for 10 seconds to show the new setup address on the OLED.

## Audiobookshelf Web Setup

The same setup page also lets you enter:

- Server URL, for example `https://books.example.com`
- Audiobookshelf username and password for the user this player should use
- Optional library ID

The player sends the username and password to Audiobookshelf's `/login` endpoint and stores only the returned user token. If no library ID is saved, the app loads the user's default library or first accessible audiobook library.

## Start Setup Page On Boot

Install the setup page as a system service. It runs as root so NetworkManager Wi-Fi changes work from the web page, but it still stores player settings in `/home/chapter/.config/abs-kids-player`.

```bash
systemctl --user disable --now audiobookshelf-player-setup.service
sudo install -m 0644 deploy/audiobookshelf-player-setup-system.service /etc/systemd/system/audiobookshelf-player-setup.service
sudo systemctl daemon-reload
sudo systemctl enable --now audiobookshelf-player-setup.service
```

Check it:

```bash
systemctl status audiobookshelf-player-setup.service
curl http://localhost:47831/health
```

The health page reports:

- setup server status
- Wi-Fi connection state and SSID
- Audiobookshelf login/server check

The same status is also shown at the top of the main setup page.

## Optional Port 80 Forwarding

The setup server listens on port `47831`, but the appliance can proxy normal web traffic from port `80` to `47831` so a parent can browse to `http://raspberrypi.local` or `http://10.42.0.1` without typing a port.

Install the root systemd forwarding service:

```bash
sudo install -m 0755 deploy/audiobookshelf-player-port80-proxy /usr/local/sbin/audiobookshelf-player-port80-proxy
sudo install -m 0644 deploy/audiobookshelf-player-port80-forward.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now audiobookshelf-player-port80-forward.service
```

Check it:

```bash
systemctl status audiobookshelf-player-port80-forward.service
curl http://localhost/health
```

This does not affect audiobook playback. It only claims inbound HTTP port `80` on the Pi, so do not enable it if the same Pi will also run another web server on port `80`.

## Optional Captive Portal DNS

To make the setup hotspot behave more like a captive portal, install the NetworkManager dnsmasq config:

```bash
sudo apt install -y dnsmasq-base
sudo mkdir -p /etc/NetworkManager/dnsmasq-shared.d
sudo install -m 0644 deploy/audiobookshelf-player-captive-portal-dnsmasq.conf /etc/NetworkManager/dnsmasq-shared.d/audiobookshelf-player-captive-portal.conf
sudo systemctl restart NetworkManager
```

Restarting NetworkManager can briefly drop your SSH session. This makes browser requests on the setup hotspot resolve to `10.42.0.1`, and the port `80` proxy shows the setup page for normal HTTP requests. Some phones should automatically show their captive network login screen. HTTPS pages cannot be silently redirected, so a user may still need to open `http://10.42.0.1` if the device does not show the captive portal prompt.

## Audiobookshelf Setup

Create a dedicated Audiobookshelf user for the player, restrict that user to the kid-friendly library or tags, then use that user's API token in this app.

## Current Prototype Features

- Large touch-friendly audiobook grid
- Cover art loading
- Play/pause, 30-second rewind, 30-second forward
- Resume from Audiobookshelf progress
- Continue/start-over prompt only when a book has listening history
- Periodic progress sync back to Audiobookshelf
- Multi-file audiobook playback
- Testable rotary/OLED menu state machine

## Appliance Direction

- Display: D-FLIFE 2.08 inch 256x64 SH1122 SPI OLED with a two-line text UI.
- Controls: two KY-040 rotary encoder modules, one for navigation and one for volume. Volume changes temporarily show a `Volume` screen with a fill bar. A short volume click mutes/unmutes; a 10-second hold shows the setup page IP address for 5 seconds.
- Internal speaker: Raspberry Pi I2S audio amp and small 4 ohm speaker, used as the default reliable output.
- Sonos support: optional network playback through SoCo, selected from a parent settings screen.
- Fallback behavior: if Sonos is unavailable, playback should return to the internal speaker.

See [docs/appliance-design.md](docs/appliance-design.md) for the hardware and software plan.

## License

This project is open source under the terms of the [MIT License](LICENSE).

## Next Good Steps

- Kiosk mode/autostart systemd service
- Internal I2S speaker setup
- Sonos output backend through SoCo
- SH1122 OLED driver validation on the real display
- GPIO event loop for both rotary encoders
- Parent settings lock
- Offline cache for selected books
- Hardware button support through GPIO
