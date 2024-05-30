#!/bin/bash
SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )

# Get the process ID(s) of the running script
PIDS=$(pgrep -f "python $SCRIPT_DIR/dbus-shelly-3em-pvinverter.py")

# Check if any process IDs were found
if [ -z "$PIDS" ]; then
  echo "No running process found for dbus-shelly-3em-pvinverter.py"
else
  echo "Killing process ID(s): $PIDS"
  # Kill the process ID(s)
  kill $PIDS
fi

# Start the script again
echo "Starting dbus-shelly-3em-pvinverter.py script..."
python $SCRIPT_DIR/dbus-shelly-3em-pvinverter.py &
