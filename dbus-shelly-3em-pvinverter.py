import platform
import logging
import sys
import os
import time
import requests
import configparser

if sys.version_info.major == 2:
    import gobject
else:
    from gi.repository import GLib as gobject

sys.path.insert(1, os.path.join(os.path.dirname(__file__), '/opt/victronenergy/dbus-systemcalc-py/ext/velib_python'))
from vedbus import VeDbusService


class DbusShelly3emService:
    def __init__(self, servicename, paths, productname='Shelly 3EM', connection='Shelly 3EM HTTP JSON service'):
        config = self._getConfig()
        deviceinstance = int(config['DEFAULT']['Deviceinstance'])
        customname = config['DEFAULT']['CustomName']

        self._dbusservice = VeDbusService("{}.http_{:02d}".format(servicename, deviceinstance))
        self._paths = paths

        logging.debug("%s /DeviceInstance = %d" % (servicename, deviceinstance))

        # Create the management objects, as specified in the ccgx dbus-api document
        self._dbusservice.add_path('/Mgmt/ProcessName', __file__)
        self._dbusservice.add_path('/Mgmt/ProcessVersion', 'Unknown version, and running on Python ' + platform.python_version())
        self._dbusservice.add_path('/Mgmt/Connection', connection)

        # Create the mandatory objects
        self._dbusservice.add_path('/DeviceInstance', deviceinstance)
        self._dbusservice.add_path('/ProductId', 0xFFFF)
        self._dbusservice.add_path('/ProductName', productname)
        self._dbusservice.add_path('/CustomName', customname)
        self._dbusservice.add_path('/Connected', 1)

        self._dbusservice.add_path('/Latency', None)
        self._dbusservice.add_path('/FirmwareVersion', self._getShellyFWVersion())
        self._dbusservice.add_path('/HardwareVersion', 0)
        self._dbusservice.add_path('/Position', int(config['DEFAULT']['Position']))
        self._dbusservice.add_path('/Serial', self._getShellySerial())
        self._dbusservice.add_path('/UpdateIndex', 0)

        # Add path values to dbus
        for path, settings in self._paths.items():
            self._dbusservice.add_path(
                path, settings['initial'], gettextcallback=settings['textformat'], writeable=True, onchangecallback=self._handlechangedvalue)

        # Last update
        self._lastUpdate = 0

        # Add _update function 'timer'
        gobject.timeout_add(250, self._update)  # pause 250ms before the next request

        # Add _signOfLife 'timer' to get feedback in log every 5 minutes
        gobject.timeout_add(self._getSignOfLifeInterval() * 60 * 1000, self._signOfLife)

    def _getShellySerial(self):
        meter_data = self._getShellyData()

        if not meter_data['mac']:
            raise ValueError("Response does not contain 'mac' attribute")

        serial = meter_data['mac']
        return serial

    def _getShellyFWVersion(self):
        meter_data = self._getShellyData()

        if not meter_data['update']['old_version']:
            raise ValueError("Response does not contain 'update/old_version' attribute")

        ver = meter_data['update']['old_version']
        return ver

    def _getConfig(self):
        config = configparser.ConfigParser()
        config.read("%s/config.ini" % (os.path.dirname(os.path.realpath(__file__))))
        return config

    def _getSignOfLifeInterval(self):
        config = self._getConfig()
        value = config['DEFAULT']['SignOfLifeLog']

        if not value:
            value = 0

        return int(value)

    def _getShellyStatusUrl(self):
        config = self._getConfig()
        accessType = config['DEFAULT']['AccessType']

        if accessType == 'OnPremise':
            URL = "http://%s:%s@%s/status" % (config['ONPREMISE']['Username'], config['ONPREMISE']['Password'], config['ONPREMISE']['Host'])
            URL = URL.replace(":@", "")
        else:
            raise ValueError("AccessType %s is not supported" % (config['DEFAULT']['AccessType']))

        return URL

    def _getShellyData(self):
        URL = self._getShellyStatusUrl()
        meter_r = requests.get(url=URL)

        # Check for response
        if not meter_r:
            raise ConnectionError("No response from Shelly 3EM - %s" % (URL))

        meter_data = meter_r.json()

        # Check for JSON
        if not meter_data:
            raise ValueError("Converting response to JSON failed")

        return meter_data

    def _signOfLife(self):
        logging.info("--- Start: sign of life ---")
        logging.info("Last _update() call: %s" % (self._lastUpdate))
        logging.info("Last '/Ac/Power': %s" % (self._dbusservice['/Ac/Power']))
        logging.info("--- End: sign of life ---")
        return True

    def _update(self):
        try:
            # Get data from Shelly 3EM
            meter_data = self._getShellyData()

            # Send data to DBus
            for i, phase in enumerate(['L1', 'L2', 'L3']):
                pre = '/Ac/' + phase
                emeter = meter_data['emeters'][i]

                voltage = emeter['voltage']
                current = emeter['current']
                power = emeter['power']
                total = emeter['total']

                self._dbusservice[pre + '/Voltage'] = voltage
                self._dbusservice[pre + '/Current'] = current
                self._dbusservice[pre + '/Power'] = power
                self._dbusservice[pre + '/Energy/Forward'] = total / 1000

            self._dbusservice['/Ac/Power'] = meter_data['total_power']
            self._dbusservice['/Ac/Energy/Forward'] = sum(emeter['total'] for emeter in meter_data['emeters']) / 1000
            

            # Increment UpdateIndex - to show that new data is available
            index = self._dbusservice['/UpdateIndex'] + 1  # increment index
            if index > 255:  # maximum value of the index
                index = 0  # overflow from 255 to 0
            self._dbusservice['/UpdateIndex'] = index

            # Update lastupdate vars
            self._lastUpdate = time.time()
        except Exception as e:
            logging.critical('Error at %s', '_update', exc_info=e)

        # Return true, otherwise add_timeout will be removed from GObject
        return True

    def _handlechangedvalue(self, path, value):
        logging.debug("someone else updated %s to %s" % (path, value))
        return True  # accept the change


def main():
    # Configure logging
    logging.basicConfig(format='%(asctime)s,%(msecs)d %(name)s %(levelname)s %(message)s',
                        datefmt='%Y-%m-%d %H:%M:%S',
                        level=logging.INFO,
                        handlers=[
                            logging.FileHandler("%s/current.log" % (os.path.dirname(os.path.realpath(__file__)))),
                            logging.StreamHandler()
                        ])

    try:
        logging.info("Start")

        from dbus.mainloop.glib import DBusGMainLoop
        # Have a mainloop, so we can send/receive asynchronous calls to and from dbus
        DBusGMainLoop(set_as_default=True)

        # Formatting
        _kwh = lambda p, v: (str(round(v, 2)) + 'kWh')
        _a = lambda p, v: (str(round(v, 1)) + 'A')
        _w = lambda p, v: (str(round(v, 1)) + 'W')
        _v = lambda p, v: (str(round(v, 1)) + 'V')

        # Start our main-service
        pvac_output = DbusShelly3emService(
            servicename='com.victronenergy.pvinverter',
            paths={
                '/Ac/Energy/Forward': {'initial': None, 'textformat': _kwh},  # energy produced by pv inverter
                '/Ac/Power': {'initial': 0, 'textformat': _w},  # power produced by pv inverter
                '/Ac/L1/Voltage': {'initial': 0, 'textformat': _v},
                '/Ac/L2/Voltage': {'initial': 0, 'textformat': _v},
                '/Ac/L3/Voltage': {'initial': 0, 'textformat': _v},
                '/Ac/L1/Current': {'initial': 0, 'textformat': _a},
                '/Ac/L2/Current': {'initial': 0, 'textformat': _a},
                '/Ac/L3/Current': {'initial': 0, 'textformat': _a},
                '/Ac/L1/Power': {'initial': 0, 'textformat': _w},
                '/Ac/L2/Power': {'initial': 0, 'textformat': _w},
                '/Ac/L3/Power': {'initial': 0, 'textformat': _w},
                '/Ac/L1/Energy/Forward': {'initial': None, 'textformat': _kwh},
                '/Ac/L2/Energy/Forward': {'initial': None, 'textformat': _kwh},
                '/Ac/L3/Energy/Forward': {'initial': None, 'textformat': _kwh},
            })

        logging.info('Connected to dbus, and switching over to gobject.MainLoop() (= event based)')
        mainloop = gobject.MainLoop()
        mainloop.run()
    except Exception as e:
        logging.critical('Error at %s', 'main', exc_info=e)


if __name__ == "__main__":
    main()
