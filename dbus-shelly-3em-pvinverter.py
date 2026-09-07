#!/usr/bin/env python3

import logging
import os
import platform
import sys
import time

import configparser
import dbus
import requests
from gi.repository import GLib

sys.path.insert(
    1,
    os.path.join(
        os.path.dirname(__file__),
        "/opt/victronenergy/dbus-systemcalc-py/ext/velib_python",
    ),
)
from vedbus import VeDbusService

from shelly_3em import (
    PHASES,
    inverter_totals,
    shelly_firmware,
    shelly_serial,
    status_url,
)

DEFAULT_POLL_SECONDS = 2
HTTP_TIMEOUT_SECONDS = 5


class SystemBus(dbus.bus.BusConnection):
    def __new__(cls):
        return dbus.bus.BusConnection.__new__(cls, dbus.bus.BusConnection.TYPE_SYSTEM)


class SessionBus(dbus.bus.BusConnection):
    def __new__(cls):
        return dbus.bus.BusConnection.__new__(cls, dbus.bus.BusConnection.TYPE_SESSION)


def dbusconnection():
    return SessionBus() if "DBUS_SESSION_BUS_ADDRESS" in os.environ else SystemBus()


def get_config():
    config = configparser.ConfigParser()
    config.read(os.path.join(os.path.dirname(os.path.realpath(__file__)), "config.ini"))
    return config


def fetch_shelly_status(host, username="", password=""):
    url = status_url(host, username, password)
    response = requests.get(url, timeout=HTTP_TIMEOUT_SECONDS)
    response.raise_for_status()
    data = response.json()
    if not data:
        raise ValueError("Empty JSON from %s" % host)
    return data


def _fmt(suffix):
    def _callback(path, value):
        if value is None:
            return ""
        return str(round(value, 2)) + suffix

    return _callback


class DbusShelly3emService:
    def __init__(self, config):
        self._config = config
        deviceinstance = int(config["DEFAULT"]["Deviceinstance"])
        customname = config["DEFAULT"]["CustomName"]
        self.host = config["ONPREMISE"]["Host"].strip()
        self._username = config["ONPREMISE"].get("Username", "")
        self._password = config["ONPREMISE"].get("Password", "")
        position = int(config["DEFAULT"].get("Position", 1))

        service_name = "com.victronenergy.pvinverter.http_{:02d}".format(deviceinstance)
        self._dbusservice = VeDbusService(service_name, dbusconnection(), register=False)
        self._lastUpdate = 0

        logging.info("PV inverter instance=%s host=%s", deviceinstance, self.host)

        self._dbusservice.add_path("/Mgmt/ProcessName", __file__)
        self._dbusservice.add_path(
            "/Mgmt/ProcessVersion",
            "Unknown version, and running on Python " + platform.python_version(),
        )
        self._dbusservice.add_path("/Mgmt/Connection", "Shelly 3EM HTTP JSON service")
        self._dbusservice.add_path("/DeviceInstance", deviceinstance)
        self._dbusservice.add_path("/ProductId", 0xFFFF)
        self._dbusservice.add_path("/ProductName", "Shelly 3EM")
        self._dbusservice.add_path("/CustomName", customname)
        self._dbusservice.add_path("/Connected", 0)
        self._dbusservice.add_path("/Latency", None)
        self._dbusservice.add_path("/FirmwareVersion", "")
        self._dbusservice.add_path("/HardwareVersion", 0)
        self._dbusservice.add_path("/Position", position)
        self._dbusservice.add_path("/Serial", "")
        self._dbusservice.add_path("/UpdateIndex", 0)

        paths = {
            "/Ac/Energy/Forward": {"initial": None, "textformat": _fmt("kWh")},
            "/Ac/Power": {"initial": 0, "textformat": _fmt("W")},
            "/Ac/L1/Voltage": {"initial": 0, "textformat": _fmt("V")},
            "/Ac/L2/Voltage": {"initial": 0, "textformat": _fmt("V")},
            "/Ac/L3/Voltage": {"initial": 0, "textformat": _fmt("V")},
            "/Ac/L1/Current": {"initial": 0, "textformat": _fmt("A")},
            "/Ac/L2/Current": {"initial": 0, "textformat": _fmt("A")},
            "/Ac/L3/Current": {"initial": 0, "textformat": _fmt("A")},
            "/Ac/L1/Power": {"initial": 0, "textformat": _fmt("W")},
            "/Ac/L2/Power": {"initial": 0, "textformat": _fmt("W")},
            "/Ac/L3/Power": {"initial": 0, "textformat": _fmt("W")},
            "/Ac/L1/Energy/Forward": {"initial": None, "textformat": _fmt("kWh")},
            "/Ac/L2/Energy/Forward": {"initial": None, "textformat": _fmt("kWh")},
            "/Ac/L3/Energy/Forward": {"initial": None, "textformat": _fmt("kWh")},
        }
        for path, settings in paths.items():
            self._dbusservice.add_path(
                path,
                settings["initial"],
                gettextcallback=settings["textformat"],
                writeable=True,
                onchangecallback=self._handlechangedvalue,
            )
        self._dbusservice.register()

    def poll_interval_ms(self):
        raw = self._config["DEFAULT"].get("PollIntervalSeconds")
        if not raw:
            raw = self._config["ONPREMISE"].get("PollIntervalSeconds")
        try:
            seconds = float(raw) if raw else DEFAULT_POLL_SECONDS
        except ValueError:
            seconds = DEFAULT_POLL_SECONDS
        return int(max(1.0, seconds) * 1000)

    def sign_of_life_ms(self):
        try:
            minutes = int(self._config["DEFAULT"].get("SignOfLifeLog") or 5)
        except ValueError:
            minutes = 5
        return max(1, minutes) * 60 * 1000

    def tick(self):
        try:
            status = fetch_shelly_status(self.host, self._username, self._password)
        except Exception:
            logging.exception("Failed to read Shelly 3EM at %s", self.host)
            self._dbusservice["/Connected"] = 0
            return True

        serial = shelly_serial(status)
        firmware = shelly_firmware(status)
        if serial:
            self._dbusservice["/Serial"] = serial
        if firmware:
            self._dbusservice["/FirmwareVersion"] = firmware

        totals = inverter_totals(status)
        for name in PHASES:
            reading = totals["phases"][name]
            prefix = "/Ac/" + name
            if reading is None:
                self._dbusservice[prefix + "/Voltage"] = None
                self._dbusservice[prefix + "/Current"] = None
                self._dbusservice[prefix + "/Power"] = None
                self._dbusservice[prefix + "/Energy/Forward"] = None
                continue
            self._dbusservice[prefix + "/Voltage"] = reading["voltage"]
            self._dbusservice[prefix + "/Current"] = reading["current"]
            self._dbusservice[prefix + "/Power"] = reading["power"]
            self._dbusservice[prefix + "/Energy/Forward"] = reading["energy_kwh"]

        self._dbusservice["/Ac/Power"] = totals["power"]
        self._dbusservice["/Ac/Energy/Forward"] = totals["energy_kwh"]
        self._dbusservice["/Connected"] = 1

        index = self._dbusservice["/UpdateIndex"] + 1
        if index > 255:
            index = 0
        self._dbusservice["/UpdateIndex"] = index
        self._lastUpdate = time.time()
        return True

    def sign_of_life(self):
        logging.info(
            "sign of life connected=%s power=%s last_update=%s",
            self._dbusservice["/Connected"],
            self._dbusservice["/Ac/Power"],
            self._lastUpdate,
        )
        return True

    def _handlechangedvalue(self, path, value):
        logging.debug("someone else updated %s to %s", path, value)
        return True


def main():
    logging.basicConfig(
        format="%(asctime)s,%(msecs)d %(name)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        level=logging.INFO,
        handlers=[logging.StreamHandler()],
    )

    from dbus.mainloop.glib import DBusGMainLoop

    DBusGMainLoop(set_as_default=True)

    config = get_config()
    service = DbusShelly3emService(config)
    service.tick()
    GLib.timeout_add(service.poll_interval_ms(), service.tick)
    GLib.timeout_add(service.sign_of_life_ms(), service.sign_of_life)

    logging.info("Connected to dbus, polling every %ss", service.poll_interval_ms() / 1000.0)
    GLib.MainLoop().run()


if __name__ == "__main__":
    main()
