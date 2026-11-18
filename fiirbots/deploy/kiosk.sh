#!/usr/bin/env bash
set -eu
# The desktop session supplies DISPLAY / WAYLAND_DISPLAY. Do not run as root.
while ! curl --fail --silent --max-time 2 http://127.0.0.1:8000/api/health >/dev/null; do
    sleep 2
done
while true; do
    chromium --kiosk --no-first-run --noerrdialogs --disable-session-crashed-bubble \
        --password-store=basic --user-data-dir="$HOME/.config/fiirbots-browser" \
        http://127.0.0.1:8000/ || true
    sleep 2
done
