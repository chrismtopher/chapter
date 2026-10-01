from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from typing import Callable


SETUP_HOTSPOT_SSID = "Chapter-Setup"
SETUP_HOTSPOT_PASSWORD = ""
SETUP_HOTSPOT_URL = "http://10.42.0.1"


class WifiError(RuntimeError):
    pass


@dataclass(frozen=True)
class WifiDevice:
    name: str
    state: str


@dataclass(frozen=True)
class WifiStatus:
    connected: bool
    ssid: str = ""
    message: str = ""


CommandRunner = Callable[[list[str]], subprocess.CompletedProcess]


def run_command(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, check=True, text=True)


def require_nmcli() -> None:
    if shutil.which("nmcli") is None:
        raise WifiError("NetworkManager nmcli command was not found.")


def nmcli(args: list[str], runner: CommandRunner = run_command) -> subprocess.CompletedProcess:
    if runner is run_command:
        require_nmcli()
    try:
        return runner(["nmcli", *args])
    except subprocess.CalledProcessError as error:
        details = (error.stderr or error.stdout or str(error)).strip()
        raise WifiError(details) from error


def wifi_devices(runner: CommandRunner = run_command) -> list[WifiDevice]:
    result = nmcli(["-t", "-f", "DEVICE,TYPE,STATE", "device", "status"], runner)
    devices: list[WifiDevice] = []
    for line in result.stdout.splitlines():
        parts = line.split(":")
        if len(parts) >= 3 and parts[1] == "wifi":
            devices.append(WifiDevice(name=parts[0], state=parts[2]))
    return devices


def choose_wifi_device(runner: CommandRunner = run_command) -> str:
    devices = wifi_devices(runner)
    if not devices:
        raise WifiError("No Wi-Fi device was found.")
    return devices[0].name


def wifi_is_connected(runner: CommandRunner = run_command) -> bool:
    return any(device.state == "connected" for device in wifi_devices(runner))


def current_wifi_ssid(runner: CommandRunner = run_command) -> str:
    result = nmcli(["-t", "-f", "ACTIVE,SSID", "device", "wifi", "list"], runner)
    for line in result.stdout.splitlines():
        fields = split_nmcli_fields(line)
        if len(fields) >= 2 and fields[0] == "yes":
            return fields[1]
    return ""


def wifi_status(runner: CommandRunner = run_command) -> WifiStatus:
    try:
        ssid = current_wifi_ssid(runner)
        if ssid:
            return WifiStatus(connected=True, ssid=ssid)
        if wifi_is_connected(runner):
            return WifiStatus(connected=True, message="Connected, SSID unavailable")
        return WifiStatus(connected=False, message="Not connected")
    except WifiError as error:
        return WifiStatus(connected=False, message=str(error))


def active_wifi_connection_name(runner: CommandRunner = run_command) -> str:
    result = nmcli(["-t", "-f", "NAME,TYPE", "connection", "show", "--active"], runner)
    for line in result.stdout.splitlines():
        fields = split_nmcli_fields(line)
        if len(fields) >= 2 and fields[1] in {"802-11-wireless", "wifi"}:
            return fields[0]
    return ""


def saved_wifi_connection_names(runner: CommandRunner = run_command) -> list[str]:
    result = nmcli(["-t", "-f", "NAME,TYPE", "connection", "show"], runner)
    names: list[str] = []
    for line in result.stdout.splitlines():
        fields = split_nmcli_fields(line)
        if len(fields) >= 2 and fields[1] in {"802-11-wireless", "wifi"} and fields[0]:
            names.append(fields[0])
    return names


def connect_wifi(
    ssid: str,
    password: str,
    device: str | None = None,
    runner: CommandRunner = run_command,
) -> None:
    ssid = ssid.strip()
    if not ssid:
        raise WifiError("Wi-Fi network name is required.")

    device = device or choose_wifi_device(runner)
    args = ["device", "wifi", "connect", ssid]
    if password:
        args.extend(["password", password])
    args.extend(["ifname", device])
    nmcli(args, runner)


def start_setup_hotspot(
    ssid: str = SETUP_HOTSPOT_SSID,
    password: str = SETUP_HOTSPOT_PASSWORD,
    device: str | None = None,
    runner: CommandRunner = run_command,
) -> None:
    if password and len(password) < 8:
        raise WifiError("Setup hotspot password must be at least 8 characters.")

    device = device or choose_wifi_device(runner)
    if not password:
        start_open_setup_hotspot(ssid, device, runner)
        return

    nmcli(
        [
            "device",
            "wifi",
            "hotspot",
            "ifname",
            device,
            "con-name",
            ssid,
            "ssid",
            ssid,
            "password",
            password,
        ],
        runner,
    )


def start_open_setup_hotspot(
    ssid: str = SETUP_HOTSPOT_SSID,
    device: str | None = None,
    runner: CommandRunner = run_command,
) -> None:
    device = device or choose_wifi_device(runner)
    delete_connection(ssid, runner=runner, missing_ok=True)
    nmcli(
        [
            "connection",
            "add",
            "type",
            "wifi",
            "ifname",
            device,
            "con-name",
            ssid,
            "autoconnect",
            "no",
            "ssid",
            ssid,
        ],
        runner,
    )
    nmcli(
        [
            "connection",
            "modify",
            ssid,
            "802-11-wireless.mode",
            "ap",
            "802-11-wireless.band",
            "bg",
            "ipv4.method",
            "shared",
            "ipv6.method",
            "disabled",
        ],
        runner,
    )
    nmcli(["connection", "up", ssid], runner)


def delete_connection(
    connection_name: str,
    runner: CommandRunner = run_command,
    missing_ok: bool = False,
) -> None:
    try:
        nmcli(["connection", "delete", "id", connection_name], runner)
    except WifiError:
        if not missing_ok:
            raise


def deactivate_connection(
    connection_name: str,
    runner: CommandRunner = run_command,
    missing_ok: bool = False,
) -> None:
    try:
        nmcli(["connection", "down", "id", connection_name], runner)
    except WifiError:
        if not missing_ok:
            raise


def disconnect_wifi_device(
    device: str,
    runner: CommandRunner = run_command,
    missing_ok: bool = False,
) -> None:
    try:
        nmcli(["device", "disconnect", device], runner)
    except WifiError:
        if not missing_ok:
            raise


def forget_current_wifi_and_start_hotspot(runner: CommandRunner = run_command) -> None:
    device = choose_wifi_device(runner)
    connection_name = active_wifi_connection_name(runner)
    if connection_name:
        deactivate_connection(connection_name, runner=runner, missing_ok=True)
        delete_connection(connection_name, runner=runner)

    disconnect_wifi_device(device, runner=runner, missing_ok=True)
    start_setup_hotspot(device=device, runner=runner)


def forget_all_wifi_connections_and_start_hotspot(runner: CommandRunner = run_command) -> None:
    device = choose_wifi_device(runner)
    for connection_name in saved_wifi_connection_names(runner):
        if connection_name == SETUP_HOTSPOT_SSID:
            continue
        deactivate_connection(connection_name, runner=runner, missing_ok=True)
        delete_connection(connection_name, runner=runner, missing_ok=True)

    disconnect_wifi_device(device, runner=runner, missing_ok=True)
    start_setup_hotspot(device=device, runner=runner)


def ensure_wifi_or_hotspot(runner: CommandRunner = run_command) -> str:
    if wifi_is_connected(runner):
        return "wifi-connected"
    start_setup_hotspot(runner=runner)
    return "hotspot-started"


def split_nmcli_pair(line: str) -> tuple[str, str]:
    active, separator, value = line.partition(":")
    if not separator:
        return active, ""
    return unescape_nmcli(active), unescape_nmcli(value)


def split_nmcli_fields(line: str) -> list[str]:
    fields: list[str] = []
    current: list[str] = []
    escaped = False
    for character in line:
        if escaped:
            current.append(character)
            escaped = False
            continue
        if character == "\\":
            escaped = True
            continue
        if character == ":":
            fields.append("".join(current))
            current = []
            continue
        current.append(character)
    if escaped:
        current.append("\\")
    fields.append("".join(current))
    return fields


def unescape_nmcli(value: str) -> str:
    return value.replace("\\:", ":").replace("\\\\", "\\")
