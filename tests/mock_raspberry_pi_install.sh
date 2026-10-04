#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MOCK_WORKSPACE="$(mktemp -d)"
MOCK_PI_ROOT="${MOCK_WORKSPACE}/raspberry-pi-os-lite"
MOCK_BIN="${MOCK_WORKSPACE}/bin"
MOCK_INSTALL_LOG="${MOCK_WORKSPACE}/commands.log"
INSTALL_DIR="${MOCK_PI_ROOT}/home/chapter/audiobookshelf-player"
BOOT_CONFIG="${MOCK_PI_ROOT}/boot/firmware/config.txt"

cleanup() {
  if [[ "${KEEP_MOCK_INSTALL:-0}" == "1" ]]; then
    printf 'Mock filesystem retained at %s\n' "$MOCK_WORKSPACE"
    return
  fi
  rm -rf "$MOCK_WORKSPACE"
}
trap cleanup EXIT

fail() {
  printf 'Mock install failed: %s\n' "$*" >&2
  exit 1
}

assert_file() {
  [[ -f "$1" ]] || fail "missing file $1"
}

assert_contains() {
  grep -Fq "$2" "$1" || fail "$1 does not contain: $2"
}

assert_line_once() {
  local count
  count="$(grep -Fxc "$2" "$1" || true)"
  [[ "$count" == "1" ]] || fail "expected one '$2' line in $1, found $count"
}

mkdir -p "$MOCK_BIN" "$(dirname "$BOOT_CONFIG")"
printf 'dtparam=audio=on\n' >"$BOOT_CONFIG"
: >"$MOCK_INSTALL_LOG"

for command in sudo apt-get raspi-config systemctl usermod chown adduser id getent git install sed tee; do
  ln -s "$PROJECT_ROOT/tests/fixtures/mock-install-command" "$MOCK_BIN/$command"
done

export MOCK_PI_ROOT MOCK_INSTALL_LOG
export MOCK_PROJECT_SOURCE="$PROJECT_ROOT"
export PATH="$MOCK_BIN:$PATH"
export CHAPTER_REPO_URL="$PROJECT_ROOT"
export CHAPTER_INSTALL_USER=chapter
export CHAPTER_INSTALL_DIR="$INSTALL_DIR"
export CHAPTER_BOOT_CONFIG="$BOOT_CONFIG"
export PYTHONPYCACHEPREFIX="${MOCK_WORKSPACE}/pycache"

run_installer() {
  bash "$PROJECT_ROOT/scripts/install-raspberry-pi.sh" --force --no-reboot
}

run_installer
run_installer

assert_line_once "$BOOT_CONFIG" "#dtparam=audio=on"
assert_line_once "$BOOT_CONFIG" "dtparam=spi=on"
assert_line_once "$BOOT_CONFIG" "dtoverlay=max98357a"
assert_line_once "$BOOT_CONFIG" "dtoverlay=i2s-mmap"

assert_file "$MOCK_PI_ROOT/etc/asound.conf"
assert_file "$MOCK_PI_ROOT/etc/systemd/system/audiobookshelf-player-boot-splash.service"
assert_file "$MOCK_PI_ROOT/etc/systemd/system/audiobookshelf-player-oled.service"
assert_file "$MOCK_PI_ROOT/etc/systemd/system/audiobookshelf-player-setup.service"
assert_file "$MOCK_PI_ROOT/etc/systemd/system/audiobookshelf-player-port80-forward.service"
assert_file "$MOCK_PI_ROOT/etc/systemd/system/audiobookshelf-player-bluetooth-unblock.service"
assert_file "$MOCK_PI_ROOT/etc/systemd/system/audiobookshelf-player-update.service"
assert_file "$MOCK_PI_ROOT/etc/NetworkManager/dnsmasq-shared.d/audiobookshelf-player-captive-portal.conf"
assert_file "$MOCK_PI_ROOT/usr/local/sbin/audiobookshelf-player-port80-proxy"
assert_file "$INSTALL_DIR/abs_kids_player/storage.py"

SETUP_SERVICE="$MOCK_PI_ROOT/etc/systemd/system/audiobookshelf-player-setup.service"
OLED_SERVICE="$MOCK_PI_ROOT/etc/systemd/system/audiobookshelf-player-oled.service"
UPDATE_SERVICE="$MOCK_PI_ROOT/etc/systemd/system/audiobookshelf-player-update.service"
assert_contains "$SETUP_SERVICE" "WorkingDirectory=$INSTALL_DIR"
assert_contains "$SETUP_SERVICE" "Environment=ABS_KIDS_PLAYER_STORAGE_OWNER=chapter"
assert_contains "$OLED_SERVICE" "User=chapter"
assert_contains "$OLED_SERVICE" "WorkingDirectory=$INSTALL_DIR"
assert_contains "$UPDATE_SERVICE" "WorkingDirectory=$INSTALL_DIR"
assert_contains "$UPDATE_SERVICE" "Environment=CHAPTER_INSTALL_USER=chapter"
assert_contains "$UPDATE_SERVICE" "Environment=CHAPTER_INSTALL_DIR=$INSTALL_DIR"

assert_contains "$MOCK_INSTALL_LOG" "apt-get update"
assert_contains "$MOCK_INSTALL_LOG" "python3-gpiozero"
assert_contains "$MOCK_INSTALL_LOG" "gstreamer1.0-libav"
assert_contains "$MOCK_INSTALL_LOG" "espeak-ng"
assert_contains "$MOCK_INSTALL_LOG" "bluez-alsa-utils"
assert_contains "$MOCK_INSTALL_LOG" "git clone --no-checkout"
assert_contains "$MOCK_INSTALL_LOG" "git -C $INSTALL_DIR checkout --detach v0.3.11"
assert_contains "$MOCK_INSTALL_LOG" "git -C $INSTALL_DIR checkout --force --detach v0.3.11"
assert_contains "$MOCK_INSTALL_LOG" "git -C $INSTALL_DIR fetch --tags origin"
assert_contains "$MOCK_INSTALL_LOG" "systemctl enable"
assert_contains "$MOCK_INSTALL_LOG" "audiobookshelf-player-oled.service"
assert_contains "$MOCK_INSTALL_LOG" "audiobookshelf-player-update.service"
assert_contains "$MOCK_INSTALL_LOG" "systemctl enable --now bluealsa.service"
assert_contains "$MOCK_INSTALL_LOG" "chown -R chapter:chapter"

printf 'Mock Raspberry Pi OS Lite install passed.\n'
printf 'Validated clean install, second-run update, boot configuration, services, storage setup, and Python entry points.\n'
