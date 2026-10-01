from __future__ import annotations

import unittest
from unittest.mock import patch

from abs_kids_player.bluetooth_audio import (
    BluetoothDevice,
    CommandResult,
    audio_candidates,
    bluetooth_powered,
    connection_successful,
    connected_bluetooth_audio_device,
    enrich_device_name,
    named_devices,
    pair_bluetooth_audio_device,
    pair_bluetooth_device,
    paired_bluetooth_audio_device,
    parse_bluetooth_devices,
    scan_bluetooth_devices,
    scan_for_devices,
    set_bluetooth_power,
    unpair_connected_bluetooth_audio_device,
)


class FakeBluetoothctl:
    def __init__(self) -> None:
        self.powered = False
        self.calls: list[tuple[str, ...]] = []
        self.device_outputs: list[str] = ["Device AA:BB:CC:DD:EE:FF Test Headphones"]
        self.removed_devices: set[str] = set()

    def __call__(self, args, _timeout: float) -> CommandResult:
        args = tuple(args)
        self.calls.append(args)
        if args == ("show",):
            return CommandResult(0, f"Powered: {'yes' if self.powered else 'no'}")
        if args == ("power", "on"):
            self.powered = True
            return CommandResult(0, "Changing power on succeeded")
        if args == ("power", "off"):
            self.powered = False
            return CommandResult(0, "Changing power off succeeded")
        if args in {
            ("agent", "on"),
            ("agent", "NoInputNoOutput"),
            ("default-agent",),
            ("pairable", "on"),
            ("scan", "off"),
        }:
            return CommandResult(0, "")
        if args == ("scan", "on"):
            return CommandResult(0, "Discovery started")
        if args == ("devices",):
            if len(self.device_outputs) > 1:
                return CommandResult(0, self.device_outputs.pop(0))
            return CommandResult(0, self.device_outputs[0])
        if args == ("devices", "Connected"):
            return CommandResult(0, "Device AA:BB:CC:DD:EE:FF Test Headphones")
        if args == ("info", "AA:BB:CC:DD:EE:FF"):
            if "AA:BB:CC:DD:EE:FF" in self.removed_devices:
                return CommandResult(1, "Device AA:BB:CC:DD:EE:FF not available")
            return CommandResult(
                0,
                "\n".join(
                    [
                        "Name: Test Headphones",
                        "Connected: yes",
                        "UUID: Audio Sink",
                    ]
                ),
            )
        if args == ("info", "22:33:44:55:66:77"):
            return CommandResult(
                0,
                "\n".join(
                    [
                        "Name: Portable Speaker",
                        "Alias: Kitchen Speaker",
                        "Connected: no",
                        "UUID: Audio Sink",
                    ]
                ),
            )
        if args == ("info", "33:44:55:66:77:88"):
            return CommandResult(
                0,
                "\n".join(
                    [
                        "Name: ProSmart 236142E",
                        "Connected: no",
                        "UUID: Audio Sink",
                    ]
                ),
            )
        if args == ("info", "44:55:66:77:88:99"):
            return CommandResult(
                0,
                "\n".join(
                    [
                        "Name: Bose SoundLink Wireless Mobile speaker",
                        "Connected: no",
                        "UUID: Audio Sink",
                    ]
                ),
            )
        if args == ("pair", "AA:BB:CC:DD:EE:FF"):
            return CommandResult(0, "Pairing successful")
        if args == ("trust", "AA:BB:CC:DD:EE:FF"):
            return CommandResult(0, "trust succeeded")
        if args == ("untrust", "AA:BB:CC:DD:EE:FF"):
            return CommandResult(0, "untrust succeeded")
        if args == ("unblock", "AA:BB:CC:DD:EE:FF"):
            return CommandResult(0, "unblock succeeded")
        if args == ("connect", "AA:BB:CC:DD:EE:FF"):
            return CommandResult(0, "Connection successful")
        if args == ("disconnect", "AA:BB:CC:DD:EE:FF"):
            return CommandResult(0, "Successful disconnected")
        if args == ("remove", "AA:BB:CC:DD:EE:FF"):
            self.removed_devices.add("AA:BB:CC:DD:EE:FF")
            return CommandResult(0, "Device has been removed")
        return CommandResult(1, "unexpected command")


class BluetoothAudioTest(unittest.TestCase):
    def test_parse_bluetooth_devices_reads_scan_and_device_lines(self) -> None:
        devices = parse_bluetooth_devices(
            "\n".join(
                [
                    "[\x1b[0;93mCHG\x1b[0m] Device aa:bb:cc:dd:ee:ff RSSI: -72",
                    "[\x1b[0;92mNEW\x1b[0m] Device aa:bb:cc:dd:ee:ff AA-BB-CC-DD-EE-FF",
                    "[\x1b[0;93mCHG\x1b[0m] Device aa:bb:cc:dd:ee:ff ManufacturerData Key: 0x004c",
                    "[\x1b[0;93mCHG\x1b[0m] Device aa:bb:cc:dd:ee:ff Name: Test Headphones",
                    "Device 11:22:33:44:55:66 Other Device",
                ]
            )
        )

        self.assertEqual(devices[0], BluetoothDevice("AA:BB:CC:DD:EE:FF", "Test Headphones"))
        self.assertEqual(devices[1], BluetoothDevice("11:22:33:44:55:66", "Other Device"))

    def test_bluetooth_power_helpers_use_bluetoothctl(self) -> None:
        runner = FakeBluetoothctl()

        self.assertFalse(bluetooth_powered(runner))
        result = set_bluetooth_power(True, runner)

        self.assertTrue(result.success)
        self.assertTrue(result.enabled)
        self.assertTrue(bluetooth_powered(runner))

    def test_audio_candidates_accept_uuid_or_name_matches(self) -> None:
        runner = FakeBluetoothctl()
        devices = [
            BluetoothDevice("AA:BB:CC:DD:EE:FF", "Test Headphones"),
            BluetoothDevice("11:22:33:44:55:66", "Keyboard"),
        ]

        candidates = audio_candidates(devices, runner)

        self.assertEqual(candidates, [devices[0]])

    def test_named_devices_filters_address_only_entries(self) -> None:
        devices = named_devices(
            [
                BluetoothDevice("AA:BB:CC:DD:EE:FF", "AA:BB:CC:DD:EE:FF"),
                BluetoothDevice("11:22:33:44:55:66", "11-22-33-44-55-66"),
                BluetoothDevice("22:33:44:55:66:77", "Bose Speaker"),
            ]
        )

        self.assertEqual(devices, [BluetoothDevice("22:33:44:55:66:77", "Bose Speaker")])

    def test_connection_success_requires_connect_not_just_pair(self) -> None:
        self.assertFalse(connection_successful("Pairing successful"))
        self.assertTrue(connection_successful("Connection successful"))
        self.assertTrue(connection_successful("Connected: yes"))

    def test_enrich_device_name_replaces_mac_name_with_alias(self) -> None:
        runner = FakeBluetoothctl()

        device = enrich_device_name(BluetoothDevice("22:33:44:55:66:77", "22:33:44:55:66:77"), runner)

        self.assertEqual(device, BluetoothDevice("22:33:44:55:66:77", "Kitchen Speaker"))

    def test_pair_bluetooth_audio_device_scans_pairs_trusts_and_connects(self) -> None:
        runner = FakeBluetoothctl()

        result = pair_bluetooth_audio_device(
            scan_seconds=0.1,
            runner=runner,
            scanner=lambda _seconds, _runner: [BluetoothDevice("AA:BB:CC:DD:EE:FF", "Test Headphones")],
        )

        self.assertTrue(result.success)
        self.assertEqual(result.device_name, "Test Headphones")
        self.assertIn(("pair", "AA:BB:CC:DD:EE:FF"), runner.calls)
        self.assertIn(("trust", "AA:BB:CC:DD:EE:FF"), runner.calls)
        self.assertIn(("connect", "AA:BB:CC:DD:EE:FF"), runner.calls)

    def test_scan_bluetooth_devices_returns_devices_without_pairing(self) -> None:
        runner = FakeBluetoothctl()

        result = scan_bluetooth_devices(
            scan_seconds=0.1,
            runner=runner,
            scanner=lambda _seconds, _runner: [BluetoothDevice("22:33:44:55:66:77", "22:33:44:55:66:77")],
        )

        self.assertTrue(result.success)
        self.assertEqual(result.message, "Choose a device")
        self.assertEqual(result.devices, (BluetoothDevice("22:33:44:55:66:77", "Kitchen Speaker"),))
        self.assertNotIn(("pair", "22:33:44:55:66:77"), runner.calls)

    def test_scan_bluetooth_devices_prefers_audio_devices_when_available(self) -> None:
        runner = FakeBluetoothctl()

        result = scan_bluetooth_devices(
            scan_seconds=0.1,
            runner=runner,
            scanner=lambda _seconds, _runner: [
                BluetoothDevice("11:22:33:44:55:66", "Keyboard"),
                BluetoothDevice("22:33:44:55:66:77", "Bose Speaker"),
            ],
        )

        self.assertTrue(result.success)
        self.assertEqual(result.devices, (BluetoothDevice("22:33:44:55:66:77", "Bose Speaker"),))

    def test_scan_bluetooth_devices_sorts_speaker_names_before_uuid_only_audio_devices(self) -> None:
        runner = FakeBluetoothctl()

        result = scan_bluetooth_devices(
            scan_seconds=0.1,
            runner=runner,
            scanner=lambda _seconds, _runner: [
                BluetoothDevice("33:44:55:66:77:88", "ProSmart 236142E"),
                BluetoothDevice("44:55:66:77:88:99", "Bose SoundLink Wireless Mobile speaker"),
            ],
        )

        self.assertTrue(result.success)
        self.assertEqual(
            result.devices,
            (
                BluetoothDevice("44:55:66:77:88:99", "Bose SoundLink Wireless Mobile speaker"),
                BluetoothDevice("33:44:55:66:77:88", "ProSmart 236142E"),
            ),
        )

    def test_scan_bluetooth_devices_runs_extra_scan_for_preferred_audio_name(self) -> None:
        runner = FakeBluetoothctl()
        calls = []

        def scanner(seconds, _runner):
            calls.append(seconds)
            if len(calls) == 1:
                return [BluetoothDevice("33:44:55:66:77:88", "ProSmart 236142E")]
            return [BluetoothDevice("44:55:66:77:88:99", "Bose SoundLink Wireless Mobile speaker")]

        result = scan_bluetooth_devices(scan_seconds=0.1, runner=runner, scanner=scanner)

        self.assertTrue(result.success)
        self.assertEqual(calls, [0.1, 15])
        self.assertEqual(
            result.devices,
            (
                BluetoothDevice("44:55:66:77:88:99", "Bose SoundLink Wireless Mobile speaker"),
                BluetoothDevice("33:44:55:66:77:88", "ProSmart 236142E"),
            ),
        )

    def test_pair_bluetooth_device_pairs_selected_device(self) -> None:
        runner = FakeBluetoothctl()

        result = pair_bluetooth_device(BluetoothDevice("AA:BB:CC:DD:EE:FF", "Test Speaker"), runner)

        self.assertTrue(result.success)
        self.assertEqual(result.device_name, "Test Speaker")
        self.assertIn(("pair", "AA:BB:CC:DD:EE:FF"), runner.calls)

    def test_pair_bluetooth_device_still_tries_connect_when_pair_fails(self) -> None:
        class ConnectAfterPairFailure(FakeBluetoothctl):
            def __call__(self, args, timeout: float) -> CommandResult:
                if tuple(args) == ("pair", "AA:BB:CC:DD:EE:FF"):
                    self.calls.append(tuple(args))
                    return CommandResult(1, "Failed to pair")
                return super().__call__(args, timeout)

        runner = ConnectAfterPairFailure()

        result = pair_bluetooth_device(BluetoothDevice("AA:BB:CC:DD:EE:FF", "Test Speaker"), runner)

        self.assertTrue(result.success)
        self.assertIn(("connect", "AA:BB:CC:DD:EE:FF"), runner.calls)

    def test_pair_bluetooth_device_retries_connect(self) -> None:
        class ConnectOnSecondAttempt(FakeBluetoothctl):
            def __init__(self) -> None:
                super().__init__()
                self.connect_attempts = 0

            def __call__(self, args, timeout: float) -> CommandResult:
                if tuple(args) == ("connect", "AA:BB:CC:DD:EE:FF"):
                    self.calls.append(tuple(args))
                    self.connect_attempts += 1
                    if self.connect_attempts == 1:
                        return CommandResult(1, "Connection failed")
                    return CommandResult(0, "Connection successful")
                return super().__call__(args, timeout)

        runner = ConnectOnSecondAttempt()

        result = pair_bluetooth_device(BluetoothDevice("AA:BB:CC:DD:EE:FF", "Test Speaker"), runner)

        self.assertTrue(result.success)
        self.assertEqual(runner.connect_attempts, 2)

    def test_scan_for_devices_keeps_scanning_until_audio_device_is_found(self) -> None:
        runner = FakeBluetoothctl()
        runner.device_outputs = [
            "Device 11:22:33:44:55:66 Keyboard",
            "Device 11:22:33:44:55:66 Keyboard\nDevice AA:BB:CC:DD:EE:FF Test Speaker",
        ]

        with patch(
            "abs_kids_player.bluetooth_audio.run_timed_scan",
            return_value="Device AA:BB:CC:DD:EE:FF Test Speaker",
        ):
            devices = scan_for_devices(5, runner)

        self.assertIn(BluetoothDevice("AA:BB:CC:DD:EE:FF", "Test Speaker"), devices)

    def test_connected_bluetooth_audio_device_returns_connected_headphones(self) -> None:
        runner = FakeBluetoothctl()

        device = connected_bluetooth_audio_device(runner)

        self.assertIsNotNone(device)
        self.assertEqual(device.name, "Test Headphones")

    def test_unpair_connected_bluetooth_audio_device_disconnects_without_forgetting_device(self) -> None:
        runner = FakeBluetoothctl()

        result = unpair_connected_bluetooth_audio_device(runner)

        self.assertTrue(result.success)
        self.assertFalse(result.connected)
        self.assertEqual(result.device_name, "Test Headphones")
        self.assertIn(("untrust", "AA:BB:CC:DD:EE:FF"), runner.calls)
        self.assertIn(("unblock", "AA:BB:CC:DD:EE:FF"), runner.calls)
        self.assertIn(("disconnect", "AA:BB:CC:DD:EE:FF"), runner.calls)
        self.assertNotIn(("remove", "AA:BB:CC:DD:EE:FF"), runner.calls)

    def test_paired_bluetooth_audio_device_finds_remembered_audio_device(self) -> None:
        class PairedButDisconnected(FakeBluetoothctl):
            def __call__(self, args, timeout: float) -> CommandResult:
                if tuple(args) == ("devices", "Connected"):
                    self.calls.append(tuple(args))
                    return CommandResult(0, "")
                if tuple(args) == ("info", "AA:BB:CC:DD:EE:FF"):
                    self.calls.append(tuple(args))
                    return CommandResult(
                        0,
                        "\n".join(
                            [
                                "Name: Test Headphones",
                                "Connected: no",
                                "Paired: yes",
                                "Trusted: yes",
                                "UUID: Audio Sink",
                            ]
                        ),
                    )
                return super().__call__(args, timeout)

        runner = PairedButDisconnected()

        device = paired_bluetooth_audio_device(runner)

        self.assertIsNotNone(device)
        self.assertEqual(device.name, "Test Headphones")


if __name__ == "__main__":
    unittest.main()
