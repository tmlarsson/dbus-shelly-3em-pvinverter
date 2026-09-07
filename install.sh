#!/bin/bash
SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )
SERVICE_NAME=$(basename $SCRIPT_DIR)

chmod 744 $SCRIPT_DIR/restart.sh
chmod 744 $SCRIPT_DIR/uninstall.sh
chmod 744 $SCRIPT_DIR/dbus-shelly-3em-pvinverter.py
chmod 755 $SCRIPT_DIR/service/run
chmod 755 $SCRIPT_DIR/service/log/run

ln -sfn $SCRIPT_DIR/service /service/$SERVICE_NAME

filename=/data/rc.local
if [ ! -f $filename ]
then
    touch $filename
    chmod 755 $filename
    echo "#!/bin/bash" >> $filename
    echo >> $filename
fi

grep -qxF "$SCRIPT_DIR/install.sh" $filename || echo "$SCRIPT_DIR/install.sh" >> $filename
