#!/usr/bin/python3
"""Power semantics and missing-data boundaries for ``metrics.py``.

These tests build a temporary sysfs tree, so they never read or write the
real hardware interfaces of the machine running them.
"""
from pathlib import Path
import json
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import metrics as m  # noqa: E402  (path setup must run first)


class MetricsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="xinguan-sysfs-")
        self.root = Path(self.tmp.name)
        self.c = m.Collector(sysfs_root=self.root, start_vendor=False)

    def tearDown(self):
        self.c.close()
        self.tmp.cleanup()

    # -- fixture helpers -------------------------------------------------
    def put(self, path, value):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(str(value))

    def pm(self, instance, label, value):
        self.put(f"bus/acpi/devices/ACPI000D:{instance:02}/path", r"\_SB_.I2C9." + label)
        self.put(f"bus/acpi/devices/ACPI000D:{instance:02}/power1_average", value)

    def battery(self, status="Discharging", ac="0",
                voltage="16000000", current="2500000"):
        fields = {
            "type": "Battery", "scope": "System", "present": "1",
            "status": status, "capacity": "70",
            "voltage_now": voltage, "current_now": current,
        }
        for key, value in fields.items():
            if value is not None:
                self.put("class/power_supply/BAT0/" + key, value)
        if ac is not None:
            self.put("class/power_supply/ADP0/type", "Mains")
            self.put("class/power_supply/ADP0/online", ac)

    def whole(self):
        return self.c.sample()["power"]["whole_w"]

    # -- whole-machine power --------------------------------------------
    def test_battery_only_correct_si_units(self):
        self.battery()
        self.assertEqual(self.whole(), 40.0)

    def test_ac_plugged_discharge_conflict_no_total(self):
        self.battery(ac="1")
        self.assertIsNone(self.whole())

    def test_full_residual_current_no_total(self):
        self.battery(status="Full", ac="0")
        self.assertIsNone(self.whole())

    def test_charging_no_total(self):
        self.battery(status="Charging", ac="0")
        self.assertIsNone(self.whole())

    def test_ac_missing_no_total(self):
        self.battery(ac=None)
        self.assertIsNone(self.whole())

    def test_ac_unreadable_no_total(self):
        self.battery(ac="unknown")
        self.assertIsNone(self.whole())

    def test_usb_online_blocks_total(self):
        self.battery()
        self.put("class/power_supply/USB0/type", "USB_C")
        self.put("class/power_supply/USB0/online", "1")
        self.assertIsNone(self.whole())

    def test_usb_unknown_blocks_total(self):
        self.battery()
        self.put("class/power_supply/USB0/type", "USB_C")
        self.assertIsNone(self.whole())

    def test_multiple_system_batteries_no_partial_total(self):
        self.battery()
        self.put("class/power_supply/BAT1/type", "Battery")
        self.assertIsNone(self.whole())

    def test_mouse_battery_excluded(self):
        self.battery()
        self.put("class/power_supply/MOUSE/type", "Battery")
        self.put("class/power_supply/MOUSE/scope", "Device")
        self.assertEqual(self.whole(), 40.0)

    def test_missing_current_no_zero(self):
        self.battery(current=None)
        self.assertIsNone(self.whole())

    def test_missing_voltage_no_zero(self):
        self.battery(voltage=None)
        self.assertIsNone(self.whole())

    def test_zero_voltage_no_fake_total(self):
        self.battery(voltage="0")
        self.assertIsNone(self.whole())

    def test_signed_current_allowed(self):
        self.battery(current="-2500000")
        self.assertEqual(self.whole(), 40.0)

    def test_nonfinite_invalid_current_no_total(self):
        for value in ("nan", "inf", "-inf", "garbage"):
            self.battery(current=value)
            self.assertIsNone(self.whole(), value)

    def test_power_now_fallback(self):
        self.battery(current=None, voltage=None)
        self.put("class/power_supply/BAT0/power_now", "42500000")
        self.assertEqual(self.whole(), 42.5)

    # -- PM00 / PM01 / PM02 rails ---------------------------------------
    def test_pm_mapping_not_total(self):
        for index, value in enumerate((11, 6, 8)):
            self.pm(index, f"PM{index:02}", value * 1000000)
        power = self.c.sample()["power"]
        self.assertEqual((power["other_w"], power["cpu_w"], power["gpu_w"]), (11, 6, 8))
        self.assertIsNone(power["whole_w"])

    def test_pm_reordered_instance_mapping(self):
        self.pm(8, "PM01", 6000000)
        self.pm(1, "PM02", 8000000)
        self.pm(5, "PM00", 11000000)
        power = self.c._rails()
        self.assertEqual((power["other_w"], power["cpu_w"], power["gpu_w"]), (11, 6, 8))

    def test_unknown_pm_identity_not_guessed(self):
        self.put("bus/acpi/devices/ACPI000D:01/power1_average", 6000000)
        self.assertIsNone(self.c._rails()["cpu_w"])

    def test_missing_rails_no_zero(self):
        power = self.c._rails()
        self.assertEqual([power[k] for k in ("cpu_w", "gpu_w", "other_w")], [None] * 3)

    def test_invalid_rails_no_zero(self):
        for index, value in enumerate(("NaN", -5000000, "oops")):
            self.pm(index, f"PM{index:02}", value)
        power = self.c._rails()
        self.assertEqual([power[k] for k in ("cpu_w", "gpu_w", "other_w")], [None] * 3)

    def test_zero_rail_is_real_zero(self):
        self.pm(1, "PM01", 0)
        self.assertEqual(self.c._rails()["cpu_w"], 0)

    # -- temperature and fan boundaries ---------------------------------
    def test_protection_zone_unknown_identity_not_temperature(self):
        self.put("class/thermal/thermal_zone6/type", "acpitz")
        self.put("class/thermal/thermal_zone6/temp", 26000)
        self.put("class/thermal/thermal_zone6/perf_limit", 0)
        temps = self.c._temperatures(self.c._vendor_snapshot())
        self.assertEqual([item["name"] for item in temps], ["CPU", "GPU"])

    def test_tz07_excluded_by_identity(self):
        for number, tag in ((0, "TZ00"), (1, "TZ07"), (6, "TZ05")):
            self.put(f"class/thermal/thermal_zone{number}/device/path", r"\_TZ_." + tag)
            self.put(f"class/thermal/thermal_zone{number}/temp", 60000 + number * 1000)
        temps = self.c._temperatures(self.c._vendor_snapshot())
        self.assertEqual([item["name"] for item in temps],
                         ["CPU", "GPU", "温区 TZ00", "温区 TZ05"])

    def test_missing_fan_no_zero(self):
        self.put("class/hwmon/hwmon1/fan1_input", "bad")
        self.assertIsNone(self.c._fans()[0]["rpm"])

    # -- vendor data ----------------------------------------------------
    def test_vendor_stale_is_unavailable(self):
        self.c._vendor = {
            "name": "M1000", "percent": 23, "cpu_temp": 50, "gpu_temp": 51,
            "sampled_monotonic": m.time.monotonic() - 11, "error": None,
        }
        data = self.c._vendor_snapshot()
        self.assertIsNone(data["percent"])
        self.assertIsNone(data["cpu_temp"])
        self.assertIsNone(data["gpu_temp"])

    def test_vendor_failure_preserves_json(self):
        sample = self.c.sample()
        self.assertIsNone(sample["gpu"]["percent"])
        json.dumps(sample, allow_nan=False)


if __name__ == "__main__":
    unittest.main(verbosity=2)
