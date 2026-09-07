#!/bin/bash
SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )
SERVICE_NAME=$(basename "$SCRIPT_DIR")

if [ -f /data/rc.local ]; then
    sed -i "\|$SCRIPT_DIR/install.sh|d" /data/rc.local
fi
if command -v svc >/dev/null 2>&1; then
    svc -d /service/$SERVICE_NAME 2>/dev/null || true
else
    pids=$(pgrep -f "python.*$SCRIPT_DIR/dbus-shelly-3em-pvinverter.py" || true)
    [ -n "$pids" ] && kill $pids
fi
rm -f /service/$SERVICE_NAME
