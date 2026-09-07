#!/bin/bash
SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )
SERVICE_NAME=$(basename $SCRIPT_DIR)

if command -v svc >/dev/null 2>&1; then
    svc -t /service/$SERVICE_NAME
else
    pids=$(pgrep -f "python.*$SCRIPT_DIR/dbus-shelly-3em-pvinverter.py" || true)
    [ -n "$pids" ] && kill $pids
fi
