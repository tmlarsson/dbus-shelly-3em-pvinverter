#!/usr/bin/env python3

import logging
import os
import platform
import sys
import time

import configparser
import dbus
import requests
from dbus.mainloop.glib import DBusGMainLoop
from gi.repository import GLib

sys.path.insert(1, "/opt/victronenergy/dbus-systemcalc-py/ext/velib_python")
from vedbus import VeDbusService

from shelly_3em import (
    apply_disconnect,
    apply_inverter,
    clamp_poll_seconds,
    clamp_sign_of_life_minutes,
    fetch_status,
    http_timeout_seconds,
    inverter_totals,
    shelly_firmware,
    shelly_serial,
    HostFailureTracker,
)

_sessions = {}


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


def _truthy(raw, default=False):
    if raw is None or str(raw).strip() == "":
        return default
    return str(raw).strip().lower() in ("1", "true", "yes", "on")


def _session_for_host(host):
    session = _sessions.get(host)
    if session is None:
        session = requests.Session()
        _sessions[host] = session
    return session


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
        self._allow_negative = _truthy(
            config["DEFAULT"].get("AllowNegativePower"), False
        )
        self._poll_seconds = clamp_poll_seconds(
            config["DEFAULT"].get("PollIntervalSeconds")
            or config["ONPREMISE"].get("PollIntervalSeconds")
        )
        self._http_timeout = http_timeout_seconds(self._poll_seconds)
        self._failures = HostFailureTracker()

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
        self._dbusservice.add_path("/CustomName", customname, writeable=True)
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
                writeable=False,
            )
        self._dbusservice.register()

    def poll_interval_ms(self):
        return int(self._poll_seconds * 1000)

    def sign_of_life_ms(self):
        raw = self._config["DEFAULT"].get("SignOfLifeLog")
        return clamp_sign_of_life_minutes(raw) * 60 * 1000

    def tick(self):
        try:
            status, elapsed = fetch_status(
                _session_for_host(self.host),
                self.host,
                self._username,
                self._password,
                timeout=self._http_timeout,
            )
            outcome = self._failures.note(self.host, True)
            if outcome == "recovered":
                logging.info("Shelly 3EM at %s recovered", self.host)
        except Exception:
            outcome = self._failures.note(self.host, False)
            if outcome == "first":
                logging.exception("Failed to read Shelly 3EM at %s", self.host)
            else:
                logging.warning("Shelly 3EM at %s still unreachable", self.host)
            apply_disconnect(self._dbusservice)
            GLib.timeout_add(self.poll_interval_ms(), self.tick)
            return False

        serial = shelly_serial(status)
        firmware = shelly_firmware(status)
        if serial:
            self._dbusservice["/Serial"] = serial
        if firmware:
            self._dbusservice["/FirmwareVersion"] = firmware

        totals = inverter_totals(status, allow_negative=self._allow_negative)
        apply_inverter(self._dbusservice, totals, latency=elapsed)

        index = self._dbusservice["/UpdateIndex"] + 1
        if index > 255:
            index = 0
        self._dbusservice["/UpdateIndex"] = index
        self._lastUpdate = time.time()
        GLib.timeout_add(self.poll_interval_ms(), self.tick)
        return False

    def sign_of_life(self):
        logging.info(
            "sign of life connected=%s power=%s last_update=%s",
            self._dbusservice["/Connected"],
            self._dbusservice["/Ac/Power"],
            self._lastUpdate,
        )
        return True


def main():
    logging.basicConfig(
        format="%(asctime)s,%(msecs)d %(name)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        level=logging.INFO,
        handlers=[logging.StreamHandler()],
    )

    DBusGMainLoop(set_as_default=True)

    config = get_config()
    service = DbusShelly3emService(config)
    service.tick()
    GLib.timeout_add(service.sign_of_life_ms(), service.sign_of_life)

    logging.info(
        "Connected to dbus, polling every %ss (http timeout %ss)",
        service.poll_interval_ms() / 1000.0,
        service._http_timeout,
    )
    GLib.MainLoop().run()


if __name__ == "__main__":
    main()
