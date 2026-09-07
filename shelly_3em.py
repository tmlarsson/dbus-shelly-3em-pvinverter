"""Parse Shelly 3EM /status JSON without D-Bus."""

PHASES = ("L1", "L2", "L3")
DEFAULT_POLL_SECONDS = 2
MIN_POLL_SECONDS = 1
DEFAULT_SIGN_OF_LIFE_MINUTES = 5
MAX_HTTP_TIMEOUT_SECONDS = 5.0


def status_url(host):
    host = (host or "").strip()
    if not host:
        raise ValueError("Host is empty")
    return "http://%s/status" % host


def http_auth(username="", password=""):
    """Return a requests-compatible (user, password) tuple, or None."""
    if not (username or password):
        return None
    return (username, password)


def clamp_poll_seconds(raw, default=DEFAULT_POLL_SECONDS, minimum=MIN_POLL_SECONDS):
    try:
        seconds = float(raw) if raw else default
    except (TypeError, ValueError):
        seconds = default
    return max(minimum, seconds)


def clamp_sign_of_life_minutes(raw, default=DEFAULT_SIGN_OF_LIFE_MINUTES):
    try:
        minutes = int(raw) if raw else default
    except (TypeError, ValueError):
        minutes = default
    return max(1, minutes)


def http_timeout_seconds(poll_seconds):
    """Keep the HTTP timeout strictly below the poll interval."""
    try:
        poll_seconds = float(poll_seconds)
    except (TypeError, ValueError):
        poll_seconds = DEFAULT_POLL_SECONDS
    return max(0.5, min(MAX_HTTP_TIMEOUT_SECONDS, poll_seconds - 0.5))


def shelly_serial(status):
    if not isinstance(status, dict):
        return None
    return status.get("mac") or None


def shelly_firmware(status):
    if not isinstance(status, dict):
        return None
    update = status.get("update") or {}
    return update.get("old_version") or None


def _as_float(value, default=None):
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def emeter_phase(status, index):
    """Return a phase reading. Instantaneous fields may be None if invalid.

    Lifetime `total` is still returned so kWh does not drop when is_valid is false.
    """
    if not isinstance(status, dict):
        return None
    emeters = status.get("emeters") or []
    if index < 0 or index >= len(emeters):
        return None
    meter = emeters[index] or {}
    energy_kwh = _as_float(meter.get("total"))
    if energy_kwh is not None:
        energy_kwh = energy_kwh / 1000.0
    valid = meter.get("is_valid") is not False
    if not valid:
        return {
            "voltage": None,
            "current": None,
            "power": None,
            "energy_kwh": energy_kwh,
            "valid": False,
        }
    return {
        "voltage": _as_float(meter.get("voltage"), 0.0),
        "current": _as_float(meter.get("current"), 0.0),
        "power": _as_float(meter.get("power"), 0.0),
        "energy_kwh": energy_kwh if energy_kwh is not None else 0.0,
        "valid": True,
    }


def clamp_generation(power, allow_negative=False):
    if power is None:
        return None
    if allow_negative:
        return power
    return max(0.0, power)


def monotonic_energy(previous, new):
    if previous is None:
        return new
    if new is None:
        return previous
    return max(previous, new)


def inverter_totals(status, allow_negative=False):
    phases = {}
    energy = 0.0
    energy_seen = False
    power_sum = 0.0
    power_seen = False
    for index, name in enumerate(PHASES):
        reading = emeter_phase(status, index)
        if reading is None:
            phases[name] = None
            continue
        if reading["power"] is not None:
            reading["power"] = clamp_generation(reading["power"], allow_negative)
            power_sum += reading["power"]
            power_seen = True
        if reading["energy_kwh"] is not None:
            energy += reading["energy_kwh"]
            energy_seen = True
        phases[name] = reading
    total_power = None
    if isinstance(status, dict) and status.get("total_power") is not None:
        total_power = clamp_generation(
            _as_float(status.get("total_power")), allow_negative
        )
    elif power_seen:
        total_power = power_sum
    return {
        "phases": phases,
        "power": total_power if total_power is not None else 0.0,
        "energy_kwh": energy if energy_seen else None,
    }


def _path_get(values, path):
    try:
        return values[path]
    except Exception:
        return None


def apply_disconnect(values):
    """Zero live watts; never touch lifetime Energy/Forward."""
    values["/Connected"] = 0
    values["/Ac/Power"] = 0
    values["/Latency"] = None
    for name in PHASES:
        values["/Ac/" + name + "/Power"] = 0
        values["/Ac/" + name + "/Current"] = 0


def apply_inverter(values, totals, latency=None):
    """Write inverter paths. Energy/Forward is monotonic; invalid phases keep kWh."""
    for name in PHASES:
        reading = totals["phases"].get(name) if totals.get("phases") else None
        prefix = "/Ac/" + name
        if reading is None:
            values[prefix + "/Voltage"] = None
            values[prefix + "/Current"] = 0
            values[prefix + "/Power"] = 0
            continue
        values[prefix + "/Voltage"] = reading["voltage"]
        values[prefix + "/Current"] = 0 if reading["current"] is None else reading["current"]
        values[prefix + "/Power"] = 0 if reading["power"] is None else reading["power"]
        values[prefix + "/Energy/Forward"] = monotonic_energy(
            _path_get(values, prefix + "/Energy/Forward"),
            reading["energy_kwh"],
        )

    values["/Ac/Power"] = totals["power"] if totals.get("power") is not None else 0
    energy_sum = 0.0
    energy_seen = False
    for name in PHASES:
        energy = _path_get(values, "/Ac/" + name + "/Energy/Forward")
        if energy is not None:
            energy_sum += energy
            energy_seen = True
    if energy_seen:
        values["/Ac/Energy/Forward"] = monotonic_energy(
            _path_get(values, "/Ac/Energy/Forward"),
            energy_sum,
        )
    elif totals.get("energy_kwh") is not None:
        values["/Ac/Energy/Forward"] = monotonic_energy(
            _path_get(values, "/Ac/Energy/Forward"),
            totals["energy_kwh"],
        )
    values["/Connected"] = 1
    if latency is not None:
        values["/Latency"] = latency


def fetch_status(session, host, username="", password="", timeout=1.5):
    """GET /status. Auth is a requests tuple, never userinfo in the URL."""
    url = status_url(host)
    response = session.get(
        url,
        timeout=timeout,
        auth=http_auth(username, password),
    )
    response.raise_for_status()
    data = response.json()
    if not data:
        raise ValueError("Empty JSON from %s" % host)
    elapsed = None
    if getattr(response, "elapsed", None) is not None:
        elapsed = response.elapsed.total_seconds()
    return data, elapsed


class HostFailureTracker:
    """Log a traceback on first host failure, one-liners after that."""

    def __init__(self):
        self._failed = set()

    def note(self, host, ok):
        if ok:
            recovered = host in self._failed
            self._failed.discard(host)
            return "recovered" if recovered else "ok"
        if host in self._failed:
            return "repeat"
        self._failed.add(host)
        return "first"
