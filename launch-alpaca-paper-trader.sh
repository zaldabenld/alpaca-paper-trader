#!/usr/bin/env bash
# Linux launcher for Alpaca Paper Trader (the Linux counterpart of the .cmd/.vbs launchers).
#   launch-alpaca-paper-trader.sh                    start the backend if needed and open the app window
#   launch-alpaca-paper-trader.sh --stop             stop the running backend
#   launch-alpaca-paper-trader.sh --install-desktop  add the app-menu entry pointing at this checkout
set -euo pipefail

ROOT="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
PYTHON="$ROOT/.venv/bin/python"
APP_DATA="${LOCALAPPDATA:-$HOME}/AlpacaPaperTrader"
INSTANCE="$APP_DATA/instance.json"
PORT="${ALPACA_TRADER_PORT:-8765}"
URL="http://127.0.0.1:$PORT"
DESKTOP_ID="alpaca-paper-trader"

fail() {
    command -v notify-send >/dev/null && notify-send -i dialog-error "Alpaca Paper Trader" "$1"
    echo "$1" >&2
    exit 1
}

healthy() {
    curl -fsS --max-time 1 "$URL/api/health" >/dev/null 2>&1
}

instance_pid() {
    [ -f "$INSTANCE" ] || return 0
    "$PYTHON" -c 'import json,sys; print(int(json.load(open(sys.argv[1])).get("pid") or 0))' "$INSTANCE" 2>/dev/null || true
}

stop_backend() {
    local pid
    pid="$(instance_pid)"
    # Only signal the pid if it is still this checkout's backend, not a reused pid.
    if [ -n "$pid" ] && [ "$pid" -gt 0 ] && tr '\0' ' ' <"/proc/$pid/cmdline" 2>/dev/null | grep -q "$ROOT/python_app/run.py"; then
        kill "$pid"
        echo "Stopped Alpaca Paper Trader backend (pid $pid)."
    else
        echo "Alpaca Paper Trader backend is not running."
    fi
}

install_desktop() {
    local apps="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
    mkdir -p "$apps"
    cat >"$apps/$DESKTOP_ID.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Alpaca Paper Trader
Comment=Alpaca paper-trading desktop app
Exec="$ROOT/launch-alpaca-paper-trader.sh"
Icon=$ROOT/python_app/static/alpaca-paper-trader-512.png
Terminal=false
Categories=Finance;Office;
StartupWMClass=chrome-127.0.0.1__-Default
Actions=stop;

[Desktop Action stop]
Name=Stop Alpaca Paper Trader
Exec="$ROOT/launch-alpaca-paper-trader.sh" --stop
EOF
    command -v update-desktop-database >/dev/null && update-desktop-database "$apps" >/dev/null 2>&1 || true
    echo "Installed $apps/$DESKTOP_ID.desktop"
}

open_window() {
    local browser
    for browser in google-chrome chromium chromium-browser brave-browser microsoft-edge; do
        if command -v "$browser" >/dev/null; then
            # A dedicated profile keeps the app window separate from normal browsing. On
            # Wayland the window's app id is chrome-127.0.0.1__-Default (--class is
            # ignored), which the desktop entry's StartupWMClass matches.
            setsid "$browser" --user-data-dir="$APP_DATA/browser-profile" --no-first-run \
                --app="$URL" >/dev/null 2>&1 &
            return
        fi
    done
    xdg-open "$URL" >/dev/null 2>&1 &
}

case "${1:-}" in
    --stop) stop_backend; exit 0 ;;
    --install-desktop) install_desktop; exit 0 ;;
    "") ;;
    *) fail "Unknown option: $1" ;;
esac

[ -x "$PYTHON" ] || fail "Missing $ROOT/.venv. Create it with: python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"
"$PYTHON" "$ROOT/python_app/run.py" --smoke >/dev/null 2>&1 || fail "Python dependencies failed to import. Reinstall with: .venv/bin/pip install -r requirements.txt"

mkdir -p "$APP_DATA"
chmod 700 "$APP_DATA"
# run.py reuses a current backend, restarts a stale one, or starts a new one.
setsid "$PYTHON" "$ROOT/python_app/run.py" --no-browser >>"$APP_DATA/launcher.log" 2>&1 &

for _ in $(seq 1 60); do
    healthy && break
    sleep 0.5
done
healthy || fail "Backend did not start. See $APP_DATA/launcher.log"
open_window
