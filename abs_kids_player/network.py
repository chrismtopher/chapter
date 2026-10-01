from __future__ import annotations

import socket
import subprocess

from .rotary_ui import TwoLineFrame, WifiSetupFrame
from .wifi import SETUP_HOTSPOT_SSID, SETUP_HOTSPOT_URL


def get_lan_ip() -> str:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        return sock.getsockname()[0]
    except OSError:
        return fallback_ip()
    finally:
        sock.close()


def fallback_ip() -> str:
    hostname_ip = hostname_ips()
    if hostname_ip:
        return hostname_ip
    try:
        return socket.gethostbyname(socket.gethostname())
    except OSError:
        return "IP unavailable"


def hostname_ips() -> str:
    try:
        result = subprocess.run(["hostname", "-I"], capture_output=True, check=True, text=True)
    except (OSError, subprocess.CalledProcessError):
        return ""

    for candidate in result.stdout.split():
        if candidate and not candidate.startswith("127."):
            return candidate
    return ""


def ip_address_frame(ip_address: str | None = None, port: int | None = None) -> TwoLineFrame:
    ip_address = ip_address or get_lan_ip()
    if ip_address == "IP unavailable":
        return TwoLineFrame("Setup address", "IP unavailable")
    url = f"http://{ip_address}" if port in (None, 80) else f"http://{ip_address}:{port}"
    return TwoLineFrame("Setup address", url)


def wifi_setup_frame(
    ssid: str = SETUP_HOTSPOT_SSID,
    url: str = SETUP_HOTSPOT_URL,
) -> WifiSetupFrame:
    return WifiSetupFrame(ssid=ssid, url=url)
