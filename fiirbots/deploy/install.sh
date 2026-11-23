#!/usr/bin/env bash
set -euo pipefail
if [[ $(id -u) -ne 0 ]]; then echo 'Run: sudo bash deploy/install.sh'; exit 1; fi
if [[ $(uname -m) != aarch64 ]]; then echo 'Requires Raspberry Pi OS 64-bit (aarch64).'; exit 1; fi
if ! command -v raspi-config >/dev/null || [[ ! -e /etc/init.d/lightdm ]]; then
    echo 'Install Raspberry Pi OS with Desktop and LightDM before running this installer.'; exit 1
fi
desktop_user=${1:-${SUDO_USER:-}}
if [[ -z "$desktop_user" || "$desktop_user" == root ]]; then
    echo 'Specify the existing desktop user: sudo bash deploy/install.sh <username>'; exit 1
fi
desktop_home=$(getent passwd "$desktop_user" | cut -d: -f6)
if [[ -z "$desktop_home" || ! -d "$desktop_home" ]]; then echo 'Desktop user not found.'; exit 1; fi
project_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
# lgpio may build from source (for example Python 3.13 on aarch64).
# Its SWIG wrapper links against the system liblgpio development library.
packages=(python3-venv python3-dev python3-tk build-essential swig liblgpio-dev chromium curl rsync sudo iw network-manager bluez wlr-randr x11-xserver-utils)
missing=()
for package in "${packages[@]}"; do
    if [[ $(dpkg-query -W -f='${Status}' "$package" 2>/dev/null) != 'install ok installed' ]]; then missing+=("$package"); fi
done
if (( ${#missing[@]} )); then
    apt-get update
    apt-get install -y "${missing[@]}"
fi
getent group gpio >/dev/null || groupadd --system gpio
id fiirbots >/dev/null 2>&1 || useradd --system --user-group --home-dir /var/lib/fiirbots --shell /usr/sbin/nologin fiirbots
usermod -a -G dialout,gpio fiirbots
install -d -o fiirbots -g fiirbots -m 700 /var/lib/fiirbots
install -d -m 755 /opt/fiirbots
if [[ "$project_dir" != /opt/fiirbots ]]; then
    rsync -a --chown=root:root --chmod=D755,Fu+rw,Fgo+r --exclude=.venv --exclude=.pio --exclude=.git --exclude=.env --exclude=data --exclude=test-results --exclude=__pycache__ \
        "$project_dir/" /opt/fiirbots/
fi
python3 -m venv /opt/fiirbots/.venv
/opt/fiirbots/.venv/bin/pip install -r /opt/fiirbots/requirements.txt
/opt/fiirbots/.venv/bin/python -c 'import lgpio; print("lgpio import OK")'
if [[ ! -e /etc/fiirbots.env ]]; then
    install -m 600 /opt/fiirbots/.env.example /etc/fiirbots.env
    # Require explicit scope configuration before the first scan.
    sed -i 's/^FIIRBOTS_SCAN_NETWORK=.*/FIIRBOTS_SCAN_NETWORK=/' /etc/fiirbots.env
fi
printf '%s\n' 'fiirbots ALL=(root) NOPASSWD: /usr/bin/systemctl reboot' > /etc/sudoers.d/fiirbots-reboot
chmod 440 /etc/sudoers.d/fiirbots-reboot
visudo -cf /etc/sudoers.d/fiirbots-reboot
printf '%s\n' 'fiirbots ALL=(root) NOPASSWD: /usr/sbin/iw dev wlan0 scan' > /etc/sudoers.d/fiirbots-wifi
chmod 440 /etc/sudoers.d/fiirbots-wifi
visudo -cf /etc/sudoers.d/fiirbots-wifi
install -m 644 /opt/fiirbots/deploy/fiirbots.service /etc/systemd/system/fiirbots.service
chmod 755 /opt/fiirbots/deploy/kiosk.sh /opt/fiirbots/deploy/touch-web.sh
install -Dm644 /opt/fiirbots/deploy/fiirbots-touch.desktop /usr/local/share/applications/fiirbots-touch.desktop
desktop_dir=$(runuser -u "$desktop_user" -- xdg-user-dir DESKTOP 2>/dev/null || true)
desktop_dir=${desktop_dir:-"$desktop_home/Desktop"}
install -d -o "$desktop_user" -g "$(id -gn "$desktop_user")" "$desktop_dir"
install -m 755 -o "$desktop_user" -g "$(id -gn "$desktop_user")" \
    /opt/fiirbots/deploy/fiirbots-touch.desktop "$desktop_dir/FIIRBots Touch.desktop"
# Migrate the previous labwc-only launcher to Raspberry Pi OS desktop autostart.
autostart="$desktop_home/.config/labwc/autostart"
if [[ -f "$autostart" ]]; then
    runuser -u "$desktop_user" -- sed -i -e '\|^/opt/fiirbots/deploy/kiosk\.sh &$|d' \
        -e '\|^/opt/fiirbots/deploy/touch-web\.sh --native &$|d' "$autostart"
fi
runuser -u "$desktop_user" -- mkdir -p "$desktop_home/.config/autostart"
entry="$desktop_home/.config/autostart/fiirbots-touch.desktop"
runuser -u "$desktop_user" -- cp /opt/fiirbots/deploy/fiirbots-touch.desktop "$entry"
if [[ ${FIIRBOTS_BROWSER_KIOSK:-0} == 1 ]]; then
    runuser -u "$desktop_user" -- sed -i 's|^Exec=.*|Exec=/opt/fiirbots/deploy/kiosk.sh|' "$entry"
fi
env SUDO_USER="$desktop_user" raspi-config nonint do_boot_behaviour B4
systemctl daemon-reload
systemctl enable fiirbots.service
systemctl restart fiirbots.service
echo 'Installed. Edit /etc/fiirbots.env for the subnet, interface, serial device and optional Gemini key.'
echo 'FIIRBots opens at desktop login. The desktop icon can also launch it now.'
echo 'After configuration changes: sudo systemctl restart fiirbots'
