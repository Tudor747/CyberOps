#!/usr/bin/env bash
set -eu

if [[ ${1:-} == --native ]]; then
    exec 9>"${XDG_RUNTIME_DIR:-/run/user/$(id -u)}/fiirbots-touch.lock"
    flock -n 9 || exit 0
fi

output=${FIIRBOTS_TOUCH_OUTPUT:-}
graphics=()
if [[ -n ${WAYLAND_DISPLAY:-} ]]; then
    platform=wayland
elif [[ -n ${DISPLAY:-} ]]; then
    platform=x11
    graphics=(--disable-gpu)
else
    printf '%s\n' 'FIIRBots Touch requires a graphical session (WAYLAND_DISPLAY or DISPLAY).' >&2
    exit 1
fi

if [[ -z "$output" ]]; then
    if [[ $platform == wayland ]]; then
        mapfile -t enabled < <(wlr-randr | awk '/^[^[:space:]]/ { name=$1 } $1=="Enabled:" && $2=="yes" { print name }')
    else
        mapfile -t enabled < <(xrandr --query | awk '$2=="connected" && /[0-9]+x[0-9]+[+-][0-9]+[+-][0-9]+/ { print $1 }')
    fi
    if [[ ${#enabled[@]} == 1 ]]; then
        output=${enabled[0]}
    fi
fi
rotate() {
    [[ -n "$output" ]] || return 1
    if [[ $platform == wayland ]]; then
        wlr-randr --output "$output" --transform 90
    else
        xrandr --output "$output" --rotate left
    fi
}

if ! rotate; then
    if command -v notify-send >/dev/null; then
        notify-send 'FIIRBots Touch' 'Display rotation could not be applied. Check the active display.' || true
    fi
fi

curl --fail --silent --retry 4 --retry-delay 1 --retry-connrefused --max-time 2 \
    http://127.0.0.1:8000/api/health >/dev/null || true
if [[ ${1:-} == --native ]]; then
    exec /usr/bin/python3 /opt/fiirbots/desktop.py --fullscreen
fi
exec chromium --ozone-platform="$platform" "${graphics[@]}" --app='http://127.0.0.1:8000/?touch=1' \
    --start-fullscreen --no-first-run --noerrdialogs --disable-session-crashed-bubble --password-store=basic \
    --user-data-dir="$HOME/.config/fiirbots-touch-web"
