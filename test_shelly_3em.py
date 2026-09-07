#!/usr/bin/env python3
import copy
import unittest

from shelly_3em import (
    HostFailureTracker,
    apply_disconnect,
    apply_inverter,
    clamp_generation,
    clamp_poll_seconds,
    clamp_sign_of_life_minutes,
    emeter_phase,
    fetch_status,
    http_auth,
    http_timeout_seconds,
    inverter_totals,
    monotonic_energy,
    shelly_firmware,
    shelly_serial,
    status_url,
)

SAMPLE = {
    "mac": "C8C9A315C9D7",
    "total_power": -3.73,
    "update": {"old_version": "v1.14.0"},
    "emeters": [
        {
            "power": 0.0,
            "current": 0.08,
            "voltage": 236.68,
            "is_valid": True,
            "total": 2504555.6,
        },
        {
            "power": 3.05,
            "current": 0.12,
            "voltage": 236.95,
            "is_valid": True,
            "total": 2615459.1,
        },
        {
            "power": -6.78,
            "current": 0.11,
            "voltage": 236.16,
            "is_valid": True,
            "total": 2492506.0,
        },
    ],
}


class _Elapsed(object):
    def total_seconds(self):
        return 0.04


class FakeResponse(object):
    def __init__(self, payload=None):
        self._payload = payload if payload is not None else SAMPLE
        self.elapsed = _Elapsed()

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class FakeSession(object):
    def __init__(self, payload=None, error=None):
        self.calls = []
        self._payload = payload
        self._error = error

    def get(self, url, timeout=None, auth=None):
        self.calls.append({"url": url, "timeout": timeout, "auth": auth})
        if self._error is not None:
            raise self._error
        return FakeResponse(self._payload)


class UrlTests(unittest.TestCase):
    def test_without_auth(self):
        self.assertEqual(status_url("192.168.42.10"), "http://192.168.42.10/status")

    def test_password_not_in_url(self):
        url = status_url("192.168.42.10")
        self.assertNotIn("p@ss:1/x", url)
        self.assertNotIn("user", url)
        self.assertEqual(http_auth("u", "p@ss:1/x"), ("u", "p@ss:1/x"))

    def test_empty_host_rejected(self):
        with self.assertRaises(ValueError):
            status_url("  ")

    def test_fetch_uses_auth_tuple_not_url(self):
        session = FakeSession()
        data, elapsed = fetch_status(
            session, "192.168.42.10", "u", "p@ss:1/x", timeout=1.5
        )
        self.assertEqual(data["mac"], "C8C9A315C9D7")
        self.assertAlmostEqual(elapsed, 0.04)
        call = session.calls[0]
        self.assertEqual(call["url"], "http://192.168.42.10/status")
        self.assertNotIn("p@ss:1/x", call["url"])
        self.assertEqual(call["auth"], ("u", "p@ss:1/x"))
        self.assertEqual(call["timeout"], 1.5)


class ParseTests(unittest.TestCase):
    def test_serial_and_firmware(self):
        self.assertEqual(shelly_serial(SAMPLE), "C8C9A315C9D7")
        self.assertEqual(shelly_firmware(SAMPLE), "v1.14.0")

    def test_phase_l3(self):
        l3 = emeter_phase(SAMPLE, 2)
        self.assertAlmostEqual(l3["power"], -6.78)
        self.assertAlmostEqual(l3["energy_kwh"], 2492.506)

    def test_missing_emeter(self):
        self.assertIsNone(emeter_phase({"emeters": []}, 2))

    def test_invalid_emeter_keeps_energy(self):
        status = copy.deepcopy(SAMPLE)
        status["emeters"][1]["is_valid"] = False
        before = inverter_totals(SAMPLE, allow_negative=True)["energy_kwh"]
        after = inverter_totals(status, allow_negative=True)["energy_kwh"]
        self.assertAlmostEqual(before, after)
        self.assertIsNone(inverter_totals(status)["phases"]["L2"]["power"])

    def test_default_clamps_negative_generation(self):
        totals = inverter_totals(SAMPLE)
        self.assertGreaterEqual(totals["power"], 0.0)
        self.assertGreaterEqual(totals["phases"]["L3"]["power"], 0.0)

    def test_allow_negative_power(self):
        totals = inverter_totals(SAMPLE, allow_negative=True)
        self.assertAlmostEqual(totals["power"], -3.73)

    def test_energy_is_monotonic(self):
        previous = 100.0
        self.assertEqual(monotonic_energy(previous, 99.0), 100.0)
        self.assertEqual(monotonic_energy(previous, None), 100.0)
        self.assertEqual(monotonic_energy(previous, 101.0), 101.0)

    def test_failure_tracker(self):
        tracker = HostFailureTracker()
        self.assertEqual(tracker.note("h", False), "first")
        self.assertEqual(tracker.note("h", False), "repeat")
        self.assertEqual(tracker.note("h", True), "recovered")
        self.assertEqual(tracker.note("h", True), "ok")
        self.assertEqual(tracker.note("h", False), "first")


class ClampTests(unittest.TestCase):
    def test_clamp_generation(self):
        self.assertEqual(clamp_generation(-3.73), 0.0)
        self.assertEqual(clamp_generation(-3.73, allow_negative=True), -3.73)

    def test_poll_interval(self):
        self.assertEqual(clamp_poll_seconds(""), 2)
        self.assertEqual(clamp_poll_seconds("nope"), 2)
        self.assertEqual(clamp_poll_seconds("0"), 1)
        self.assertEqual(clamp_poll_seconds("2"), 2)

    def test_sign_of_life(self):
        self.assertEqual(clamp_sign_of_life_minutes("bogus"), 5)
        self.assertEqual(clamp_sign_of_life_minutes(""), 5)
        self.assertEqual(clamp_sign_of_life_minutes("1"), 1)

    def test_http_timeout_below_poll(self):
        self.assertEqual(http_timeout_seconds(2), 1.5)
        self.assertEqual(http_timeout_seconds(1), 0.5)
        self.assertEqual(http_timeout_seconds(20), 5.0)


class ApplyTests(unittest.TestCase):
    def _live(self):
        values = {}
        apply_inverter(values, inverter_totals(SAMPLE), latency=0.04)
        return values

    def test_disconnect_zeros_power_keeps_energy(self):
        values = self._live()
        energy = values["/Ac/Energy/Forward"]
        l3_energy = values["/Ac/L3/Energy/Forward"]
        apply_disconnect(values)
        self.assertEqual(values["/Connected"], 0)
        self.assertEqual(values["/Ac/Power"], 0)
        self.assertEqual(values["/Ac/L1/Power"], 0)
        self.assertEqual(values["/Ac/L2/Power"], 0)
        self.assertEqual(values["/Ac/L3/Power"], 0)
        self.assertEqual(values["/Ac/L3/Current"], 0)
        self.assertEqual(values["/Ac/Energy/Forward"], energy)
        self.assertEqual(values["/Ac/L3/Energy/Forward"], l3_energy)
        self.assertIsNone(values["/Latency"])

    def test_invalid_l2_does_not_drop_energy(self):
        values = self._live()
        before = values["/Ac/Energy/Forward"]
        l2_before = values["/Ac/L2/Energy/Forward"]
        status = copy.deepcopy(SAMPLE)
        status["emeters"][1]["is_valid"] = False
        apply_inverter(values, inverter_totals(status))
        self.assertGreaterEqual(values["/Ac/Energy/Forward"], before)
        self.assertEqual(values["/Ac/L2/Energy/Forward"], l2_before)
        self.assertEqual(values["/Ac/L2/Power"], 0)
        self.assertEqual(values["/Connected"], 1)

    def test_missing_emeter_does_not_drop_energy(self):
        values = self._live()
        before = values["/Ac/Energy/Forward"]
        l3_before = values["/Ac/L3/Energy/Forward"]
        status = copy.deepcopy(SAMPLE)
        status["emeters"] = status["emeters"][:1]
        apply_inverter(values, inverter_totals(status))
        self.assertGreaterEqual(values["/Ac/Energy/Forward"], before)
        self.assertEqual(values["/Ac/L3/Energy/Forward"], l3_before)
        self.assertEqual(values["/Ac/L3/Power"], 0)

    def test_energy_non_decreasing_across_statuses(self):
        values = {}
        previous = None
        statuses = [SAMPLE]
        invalid = copy.deepcopy(SAMPLE)
        invalid["emeters"][1]["is_valid"] = False
        statuses.append(invalid)
        dropped = copy.deepcopy(SAMPLE)
        dropped["emeters"][2]["total"] = 100
        statuses.append(dropped)
        missing = copy.deepcopy(SAMPLE)
        missing["emeters"] = missing["emeters"][:1]
        statuses.append(missing)
        for status in statuses:
            apply_inverter(values, inverter_totals(status))
            energy = values["/Ac/Energy/Forward"]
            if previous is not None:
                self.assertGreaterEqual(energy, previous)
            previous = energy

    def test_default_publish_is_not_negative(self):
        values = self._live()
        self.assertGreaterEqual(values["/Ac/Power"], 0.0)
        self.assertGreaterEqual(values["/Ac/L3/Power"], 0.0)

    def test_latency_from_fetch(self):
        values = self._live()
        self.assertAlmostEqual(values["/Latency"], 0.04)


if __name__ == "__main__":
    unittest.main()
