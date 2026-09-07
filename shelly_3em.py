"""Parse Shelly 3EM /status JSON without D-Bus or HTTP."""

PHASES = ("L1", "L2", "L3")


def status_url(host, username="", password=""):
    host = (host or "").strip()
    if not host:
        raise ValueError("Host is empty")
    if username or password:
        return "http://%s:%s@%s/status" % (username, password, host)
    return "http://%s/status" % host


def shelly_serial(status):
    if not isinstance(status, dict):
        return None
    return status.get("mac") or None


def shelly_firmware(status):
    if not isinstance(status, dict):
        return None
    update = status.get("update") or {}
    return update.get("old_version") or None


def _as_float(value, default=0.0):
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def emeter_phase(status, index):
    """Return voltage, current, power, energy_kwh for emeters[index], or None."""
    if not isinstance(status, dict):
        return None
    emeters = status.get("emeters") or []
    if index < 0 or index >= len(emeters):
        return None
    meter = emeters[index] or {}
    if meter.get("is_valid") is False:
        return None
    return {
        "voltage": _as_float(meter.get("voltage")),
        "current": _as_float(meter.get("current")),
        "power": _as_float(meter.get("power")),
        "energy_kwh": _as_float(meter.get("total")) / 1000.0,
    }


def inverter_totals(status):
    phases = {}
    energy = 0.0
    for index, name in enumerate(PHASES):
        reading = emeter_phase(status, index)
        if reading is None:
            phases[name] = None
            continue
        phases[name] = reading
        energy += reading["energy_kwh"]
    total_power = status.get("total_power") if isinstance(status, dict) else None
    if total_power is None:
        total_power = sum(
            reading["power"] for reading in phases.values() if reading
        )
    return {
        "phases": phases,
        "power": _as_float(total_power),
        "energy_kwh": energy,
    }
