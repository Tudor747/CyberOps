#!/usr/bin/env bash
# Read-only inventory. No scans, packet injection, installs, or service changes.
set -u
section() { printf '\n%s\n' "$1"; }
section 'OS / architecture'
uname -sm
if [[ -r /etc/os-release ]]; then
    grep -E '^(PRETTY_NAME|VERSION_CODENAME)=' /etc/os-release
fi
section 'Available commands'
for cmd in python3 nmcli iw ip lsusb chromium labwc raspi-config; do
    if command -v "$cmd" >/dev/null 2>&1; then
        printf '%s: available\n' "$cmd"
    else
        printf '%s: MISSING\n' "$cmd"
    fi
done
if command -v python3 >/dev/null 2>&1; then python3 --version; fi
section 'USB device models'
if command -v lsusb >/dev/null 2>&1; then lsusb; fi
section 'Network interfaces (no scan)'
if command -v ip >/dev/null 2>&1; then ip -brief link; fi
section 'Wi-Fi device and advertised driver capabilities (no scan)'
for phy_path in /sys/class/ieee80211/phy*; do
    [[ -e "$phy_path" ]] || continue
    printf 'PHY: %s\n' "${phy_path##*/}"
    if [[ -L "$phy_path/device/driver" ]]; then
        printf 'Driver path: '
        readlink -f "$phy_path/device/driver"
    fi
    if [[ -r "$phy_path/device/modalias" ]]; then
        printf 'Device identifier: '
        cat "$phy_path/device/modalias"
    fi
done
if command -v iw >/dev/null 2>&1; then
    iw dev
    iw list
fi
section 'Serial device paths'
if [[ -d /dev/serial/by-id ]]; then
    find /dev/serial/by-id -maxdepth 1 -type l -printf '%f\n'
else
    printf 'No stable serial device paths found\n'
fi
section 'Installed FIIRBots service'
if command -v systemctl >/dev/null 2>&1; then
    systemctl show fiirbots.service --no-pager \
        --property=LoadState,ActiveState,SubState,User,Group,AmbientCapabilities
fi
section 'Interpretation'
printf '%s\n' \
    'This inventory is not a functional test or a deployment readiness certificate.' \
    'Advertised Wi-Fi modes do not prove packet injection or concurrent-mode operation.' \
    'Identify both ESP boards before selecting firmware or assigning radio functions.'
