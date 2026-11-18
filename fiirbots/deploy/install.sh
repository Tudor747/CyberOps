#!/usr/bin/env bash
set -euo pipefail
if [[ $(id -u) -ne 0 ]]; then echo 'Run: sudo bash deploy/install.sh'; exit 1; fi
if [[ $(uname -m) != aarch64 ]]; then echo 'Requires Raspberry Pi OS 64-bit (aarch64).'; exit 1; fi
if ! command -v labwc >/dev/null || ! command -v raspi-config >/dev/null || [[ ! -e /etc/init.d/lightdm ]]; then
    echo 'Install Raspberry Pi OS with Desktop (labwc / LightDM) before running this installer.'; exit 1
fi
desktop_user=${1:-${SUDO_USER:-}}
if [[ -z "$desktop_user" || "$desktop_user" == root ]]; then
    echo 'Specify the existing desktop user: sudo bash deploy/install.sh <username>'; exit 1
fi
desktop_home=$(getent passwd "$desktop_user" | cut -d: -f6)
if [[ -z "$desktop_home" || ! -d "$desktop_home" ]]; then echo 'Desktop user not found.'; exit 1; fi
project_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
apt-get update
apt-get install -y python3-venv python3-dev build-essential chromium curl rsync sudo
getent group gpio >/dev/null || groupadd --system gpio
id fiirbots >/dev/null 2>&1 || useradd --system --user-group --home-dir /var/lib/fiirbots --shell /usr/sbin/nologin fiirbots
usermod -a -G dialout,gpio fiirbots
install -d -o fiirbots -g fiirbots -m 700 /var/lib/fiirbots
install -d -m 755 /opt/fiirbots
if [[ "$project_dir" != /opt/fiirbots ]]; then
    rsync -a --exclude=.venv --exclude=.pio --exclude=.git --exclude=.env --exclude=data --exclude=__pycache__ \
        "$project_dir/" /opt/fiirbots/
fi
python3 -m venv /opt/fiirbots/.venv
/opt/fiirbots/.venv/bin/pip install -r /opt/fiirbots/requirements.txt
if [[ ! -e /etc/fiirbots.env ]]; then
    install -m 600 /opt/fiirbots/.env.example /etc/fiirbots.env
    # Require explicit scope configuration before the first scan.
    sed -i 's/^FIIRBOTS_SCAN_NETWORK=.*/FIIRBOTS_SCAN_NETWORK=/' /etc/fiirbots.env
fi
printf '%s\n' 'fiirbots ALL=(root) NOPASSWD: /usr/bin/systemctl reboot' > /etc/sudoers.d/fiirbots-reboot
chmod 440 /etc/sudoers.d/fiirbots-reboot
visudo -cf /etc/sudoers.d/fiirbots-reboot
install -m 644 /opt/fiirbots/deploy/fiirbots.service /etc/systemd/system/fiirbots.service
chmod 755 /opt/fiirbots/deploy/kiosk.sh
# labwc autostart is used by current Raspberry Pi OS desktop images.
install -d -o "$desktop_user" -g "$(id -gn "$desktop_user")" "$desktop_home/.config/labwc"
autostart="$desktop_home/.config/labwc/autostart"
if [[ ! -e "$autostart" && -f /etc/xdg/labwc/autostart ]]; then cp /etc/xdg/labwc/autostart "$autostart"; fi
touch "$autostart"
grep -Fq '/opt/fiirbots/deploy/kiosk.sh' "$autostart" || printf '\n/opt/fiirbots/deploy/kiosk.sh &\n' >> "$autostart"
chown "$desktop_user:$(id -gn "$desktop_user")" "$autostart"
env SUDO_USER="$desktop_user" raspi-config nonint do_boot_behaviour B4
systemctl daemon-reload
systemctl enable --now fiirbots.service
echo 'Installed. Edit /etc/fiirbots.env for the subnet, interface, serial device and optional Gemini key.'
echo 'Desktop autologin and kiosk startup are enabled. Reboot after completing configuration.'
echo 'After configuration changes: sudo systemctl restart fiirbots'
