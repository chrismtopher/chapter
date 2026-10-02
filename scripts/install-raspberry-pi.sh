#!/usr/bin/env bash
set -euo pipefail

REPO_URL="${CHAPTER_REPO_URL:-https://github.com/chrismtopher/chapter.git}"
RELEASE_REF="${CHAPTER_RELEASE_REF:-v0.3.8}"
INSTALL_USER="${CHAPTER_INSTALL_USER:-chapter}"
INSTALL_DIR="${CHAPTER_INSTALL_DIR:-}"
ASSUME_YES=0
NO_REBOOT=0
FORCE=0

APT_PACKAGES=(
  git
  curl
  avahi-daemon
  network-manager
  rfkill
  gpiod
  fonts-dejavu-core
  python3-pil
  python3-spidev
  python3-gpiozero
  python3-lgpio
  alsa-utils
  espeak-ng
  gstreamer1.0-alsa
  python3-gi
  python3-gst-1.0
  gir1.2-gstreamer-1.0
  gstreamer1.0-plugins-base
  gstreamer1.0-plugins-good
  gstreamer1.0-plugins-bad
  gstreamer1.0-libav
  dnsmasq-base
  bluez
)

SERVICES=(
  audiobookshelf-player-boot-splash.service
  audiobookshelf-player-oled.service
  audiobookshelf-player-setup.service
  audiobookshelf-player-port80-forward.service
  audiobookshelf-player-bluetooth-unblock.service
)

usage() {
  cat <<EOF
Install Chapter Player for Audiobookshelf on Raspberry Pi OS.

Usage:
  scripts/install-raspberry-pi.sh [options]

Options:
  --yes              Do not prompt; reboot automatically at the end.
  --no-reboot        Do not reboot at the end.
  --force            Skip the Raspberry Pi hardware check.
  --repo-url URL     Git repository to clone. Default: ${REPO_URL}
  --release-ref REF  Release tag or commit to install. Default: ${RELEASE_REF}
  --user USER        Service user. Default: ${INSTALL_USER}
  --install-dir DIR  Install directory. Default: /home/${INSTALL_USER}/audiobookshelf-player
  -h, --help         Show this help.

Environment overrides:
  CHAPTER_REPO_URL
  CHAPTER_RELEASE_REF
  CHAPTER_INSTALL_USER
  CHAPTER_INSTALL_DIR
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --yes)
      ASSUME_YES=1
      shift
      ;;
    --no-reboot)
      NO_REBOOT=1
      shift
      ;;
    --force)
      FORCE=1
      shift
      ;;
    --repo-url)
      REPO_URL="${2:?Missing value for --repo-url}"
      shift 2
      ;;
    --release-ref)
      RELEASE_REF="${2:?Missing value for --release-ref}"
      shift 2
      ;;
    --user)
      INSTALL_USER="${2:?Missing value for --user}"
      shift 2
      ;;
    --install-dir)
      INSTALL_DIR="${2:?Missing value for --install-dir}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ -z "$INSTALL_DIR" ]]; then
  INSTALL_DIR="/home/${INSTALL_USER}/audiobookshelf-player"
fi

log() {
  printf '\n==> %s\n' "$*"
}

warn() {
  printf 'Warning: %s\n' "$*" >&2
}

die() {
  printf 'Error: %s\n' "$*" >&2
  exit 1
}

sudo_run() {
  if [[ "${EUID}" -eq 0 ]]; then
    "$@"
  else
    sudo "$@"
  fi
}

as_install_user() {
  if command -v sudo >/dev/null 2>&1; then
    sudo -u "$INSTALL_USER" -H "$@"
    return
  fi
  if [[ "${EUID}" -eq 0 ]] && command -v runuser >/dev/null 2>&1; then
    runuser -u "$INSTALL_USER" -- env HOME="$(install_home)" "$@"
    return
  fi
  die "sudo or runuser is required to run commands as ${INSTALL_USER}."
}

require_raspberry_pi() {
  if [[ "$FORCE" -eq 1 ]]; then
    return
  fi
  if [[ ! -r /proc/device-tree/model ]]; then
    die "This installer is intended for Raspberry Pi OS. Re-run with --force to skip this check."
  fi
  local model
  model="$(tr -d '\0' </proc/device-tree/model)"
  case "$model" in
    Raspberry\ Pi*)
      log "Detected ${model}"
      ;;
    *)
      die "This does not look like a Raspberry Pi (${model}). Re-run with --force to skip this check."
      ;;
  esac
}

require_sudo() {
  if [[ "${EUID}" -eq 0 ]]; then
    return
  fi
  if ! command -v sudo >/dev/null 2>&1; then
    die "sudo is required."
  fi
  sudo -v
}

boot_config_path() {
  if [[ -n "${CHAPTER_BOOT_CONFIG:-}" ]]; then
    printf '%s\n' "$CHAPTER_BOOT_CONFIG"
  elif [[ -f /boot/firmware/config.txt ]]; then
    printf '%s\n' /boot/firmware/config.txt
  elif [[ -f /boot/config.txt ]]; then
    printf '%s\n' /boot/config.txt
  else
    die "Could not find /boot/firmware/config.txt or /boot/config.txt."
  fi
}

ensure_user() {
  log "Preparing ${INSTALL_USER} user"
  if ! id "$INSTALL_USER" >/dev/null 2>&1; then
    sudo_run adduser --disabled-password --gecos "" "$INSTALL_USER"
  fi

  local groups=()
  local group
  for group in audio gpio spi i2c input video netdev bluetooth; do
    if getent group "$group" >/dev/null 2>&1; then
      groups+=("$group")
    fi
  done

  if [[ "${#groups[@]}" -gt 0 ]]; then
    local joined
    joined="$(IFS=,; printf '%s' "${groups[*]}")"
    sudo_run usermod -aG "$joined" "$INSTALL_USER"
  fi
}

install_home() {
  getent passwd "$INSTALL_USER" | cut -d: -f6
}

prepare_storage_directories() {
  log "Preparing Chapter storage"
  local home_dir
  home_dir="$(install_home)"
  local config_dir="${home_dir}/.config/abs-kids-player"
  local state_dir="${home_dir}/.local/state/abs-kids-player"
  sudo_run install -d -m 0700 -o "$INSTALL_USER" -g "$INSTALL_USER" "$config_dir" "$state_dir"
  sudo_run chown -R "$INSTALL_USER:$INSTALL_USER" "$config_dir" "$state_dir"
}

install_packages() {
  log "Installing system packages"
  sudo_run apt-get update
  sudo_run env DEBIAN_FRONTEND=noninteractive apt-get install -y "${APT_PACKAGES[@]}"
}

sync_project() {
  log "Installing project into ${INSTALL_DIR}"
  sudo_run install -d -o "$INSTALL_USER" -g "$INSTALL_USER" "$(dirname "$INSTALL_DIR")"

  if [[ -d "${INSTALL_DIR}/.git" ]]; then
    sudo_run chown -R "$INSTALL_USER:$INSTALL_USER" "$INSTALL_DIR"
    as_install_user git -C "$INSTALL_DIR" fetch --tags origin
    as_install_user git -C "$INSTALL_DIR" checkout --force --detach "$RELEASE_REF"
    return
  fi

  if [[ -e "$INSTALL_DIR" ]]; then
    die "${INSTALL_DIR} already exists but is not a Git checkout. Move it aside or set CHAPTER_INSTALL_DIR."
  fi

  as_install_user git clone --no-checkout "$REPO_URL" "$INSTALL_DIR"
  as_install_user git -C "$INSTALL_DIR" checkout --detach "$RELEASE_REF"
}

ensure_boot_config_line() {
  local config_path="$1"
  local line="$2"
  local pattern="$3"
  if sudo_run grep -Eq "$pattern" "$config_path"; then
    return
  fi
  printf '\n%s\n' "$line" | sudo_run tee -a "$config_path" >/dev/null
}

configure_spi_and_i2s() {
  log "Configuring SPI and I2S audio"
  local config_path
  config_path="$(boot_config_path)"
  local backup_path="${config_path}.chapter-installer-$(date +%Y%m%d-%H%M%S).bak"
  sudo_run cp "$config_path" "$backup_path"
  log "Backed up ${config_path} to ${backup_path}"

  if command -v raspi-config >/dev/null 2>&1; then
    sudo_run raspi-config nonint do_spi 0 || warn "raspi-config could not enable SPI; adding dtparam=spi=on directly."
  fi

  sudo_run sed -i 's/^[[:space:]]*dtparam=audio=on/#dtparam=audio=on/' "$config_path"
  ensure_boot_config_line "$config_path" "dtparam=spi=on" '^[[:space:]]*dtparam=spi=on([[:space:]]|$)'
  ensure_boot_config_line "$config_path" "dtoverlay=max98357a" '^[[:space:]]*dtoverlay=max98357a([[:space:],]|$)'
  ensure_boot_config_line "$config_path" "dtoverlay=i2s-mmap" '^[[:space:]]*dtoverlay=i2s-mmap([[:space:],]|$)'
}

install_asound_config() {
  log "Installing ALSA config"
  local tmp
  tmp="$(mktemp)"
  cat >"$tmp" <<'EOF'
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
EOF
  sudo_run install -m 0644 "$tmp" /etc/asound.conf
  rm -f "$tmp"
}

install_services() {
  log "Installing systemd services"
  local deploy_dir="${INSTALL_DIR}/deploy"
  [[ -d "$deploy_dir" ]] || die "Missing deploy directory at ${deploy_dir}."
  local home_dir
  home_dir="$(install_home)"
  local tmpdir
  tmpdir="$(mktemp -d)"

  render_unit "${deploy_dir}/audiobookshelf-player-boot-splash.service" "${tmpdir}/audiobookshelf-player-boot-splash.service" "$home_dir"
  render_unit "${deploy_dir}/audiobookshelf-player-oled.service" "${tmpdir}/audiobookshelf-player-oled.service" "$home_dir"
  render_unit "${deploy_dir}/audiobookshelf-player-setup-system.service" "${tmpdir}/audiobookshelf-player-setup.service" "$home_dir"
  render_unit "${deploy_dir}/audiobookshelf-player-bluetooth-unblock.service" "${tmpdir}/audiobookshelf-player-bluetooth-unblock.service" "$home_dir"
  render_unit "${deploy_dir}/audiobookshelf-player-update.service" "${tmpdir}/audiobookshelf-player-update.service" "$home_dir"

  sudo_run install -m 0644 "${tmpdir}/audiobookshelf-player-boot-splash.service" /etc/systemd/system/
  sudo_run install -m 0644 "${tmpdir}/audiobookshelf-player-oled.service" /etc/systemd/system/
  sudo_run install -m 0644 "${tmpdir}/audiobookshelf-player-setup.service" /etc/systemd/system/audiobookshelf-player-setup.service
  sudo_run install -m 0644 "${tmpdir}/audiobookshelf-player-bluetooth-unblock.service" /etc/systemd/system/
  sudo_run install -m 0644 "${tmpdir}/audiobookshelf-player-update.service" /etc/systemd/system/
  sudo_run install -m 0755 "${deploy_dir}/audiobookshelf-player-port80-proxy" /usr/local/sbin/audiobookshelf-player-port80-proxy
  sudo_run install -m 0644 "${deploy_dir}/audiobookshelf-player-port80-forward.service" /etc/systemd/system/

  sudo_run install -d /etc/NetworkManager/dnsmasq-shared.d
  sudo_run install -m 0644 "${deploy_dir}/audiobookshelf-player-captive-portal-dnsmasq.conf" \
    /etc/NetworkManager/dnsmasq-shared.d/audiobookshelf-player-captive-portal.conf

  sudo_run systemctl daemon-reload
  sudo_run systemctl enable "${SERVICES[@]}"
  rm -rf "$tmpdir"
}

sed_replacement() {
  printf '%s' "$1" | sed 's/[&|]/\\&/g'
}

render_unit() {
  local source="$1"
  local target="$2"
  local home_dir="$3"
  local escaped_install_dir escaped_home_dir escaped_user
  escaped_install_dir="$(sed_replacement "$INSTALL_DIR")"
  escaped_home_dir="$(sed_replacement "$home_dir")"
  escaped_user="$(sed_replacement "$INSTALL_USER")"
  sed \
    -e "s|/home/chapter/audiobookshelf-player|__CHAPTER_INSTALL_DIR__|g" \
    -e "s|/home/chapter|${escaped_home_dir}|g" \
    -e "s|__CHAPTER_INSTALL_DIR__|${escaped_install_dir}|g" \
    -e "s|^User=chapter$|User=${escaped_user}|g" \
    -e "s|CHAPTER_INSTALL_USER=chapter|CHAPTER_INSTALL_USER=${escaped_user}|g" \
    -e "s|ABS_KIDS_PLAYER_STORAGE_OWNER=chapter|ABS_KIDS_PLAYER_STORAGE_OWNER=${escaped_user}|g" \
    "$source" >"$target"
}

verify_python_entrypoints() {
  log "Checking Python entry points"
  as_install_user bash -c 'cd "$1" && python3 -m abs_kids_player.setup_server --help >/dev/null' bash "$INSTALL_DIR"
  as_install_user bash -c 'cd "$1" && python3 -m abs_kids_player.oled_service --help >/dev/null' bash "$INSTALL_DIR"
}

maybe_reboot() {
  if [[ "$NO_REBOOT" -eq 1 ]]; then
    log "Install complete. Reboot later with: sudo reboot"
    return
  fi

  if [[ "$ASSUME_YES" -eq 1 ]]; then
    log "Install complete. Rebooting now."
    sudo_run reboot
    return
  fi

  log "Install complete."
  if [[ -t 0 ]]; then
    read -r -p "Reboot now? [y/N] " answer
    case "$answer" in
      y|Y|yes|YES)
        sudo_run reboot
        ;;
      *)
        echo "Reboot later with: sudo reboot"
        ;;
    esac
  else
    echo "Reboot with: sudo reboot"
  fi
}

main() {
  require_raspberry_pi
  require_sudo
  install_packages
  ensure_user
  prepare_storage_directories
  sync_project
  configure_spi_and_i2s
  install_asound_config
  install_services
  verify_python_entrypoints
  maybe_reboot
}

main "$@"
