#!/usr/bin/env python3
import unittest

from shelly_3em import emeter_phase, inverter_totals, shelly_firmware, shelly_serial, status_url

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


class UrlTests(unittest.TestCase):
    def test_without_auth(self):
        self.assertEqual(status_url("192.168.42.10"), "http://192.168.42.10/status")

    def test_with_auth(self):
        self.assertEqual(
            status_url("192.168.42.10", "u", "p"),
            "http://u:p@192.168.42.10/status",
        )


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

    def test_totals(self):
        totals = inverter_totals(SAMPLE)
        self.assertAlmostEqual(totals["power"], -3.73)
        self.assertAlmostEqual(totals["energy_kwh"], 7612.5207, places=3)
        self.assertIsNotNone(totals["phases"]["L1"])


if __name__ == "__main__":
    unittest.main()
