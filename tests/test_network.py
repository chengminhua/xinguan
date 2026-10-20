#!/usr/bin/python3
"""Network-rate baseline and physical-interface filtering tests."""
from pathlib import Path
import sys
import tempfile
import time
import types
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import metrics as m  # noqa: E402  (path setup must run first)

Counter = types.SimpleNamespace
Stat = types.SimpleNamespace


class NetworkTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="xinguan-network-")
        self.root = Path(self.tmp.name)
        (self.root / "class/net/eth0/device").mkdir(parents=True)
        (self.root / "class/net/tun0").mkdir(parents=True)
        self.c = m.Collector(sysfs_root=self.root, start_vendor=False)
        self.original_counters = m.psutil.net_io_counters
        self.original_stats = m.psutil.net_if_stats

    def tearDown(self):
        m.psutil.net_io_counters = self.original_counters
        m.psutil.net_if_stats = self.original_stats
        self.c.close()
        self.tmp.cleanup()

    def fake(self, counters):
        m.psutil.net_io_counters = lambda pernic=True, nowrap=False: counters
        m.psutil.net_if_stats = lambda: {
            "eth0": Stat(isup=True, speed=1000),
            "tun0": Stat(isup=True, speed=10000),
            "lo": Stat(isup=True, speed=0),
        }
        self.c._network_previous_monotonic = time.monotonic() - 1
        return self.c._network()

    def test_initial_sample_has_no_rate(self):
        result = self.fake({
            "eth0": Counter(bytes_recv=100, bytes_sent=200),
            "tun0": Counter(bytes_recv=1000, bytes_sent=2000),
            "lo": Counter(bytes_recv=3000, bytes_sent=3000),
        })
        self.assertFalse(result["ready"])
        self.assertIsNone(result["aggregate"]["rx_bytes_per_sec"])
        self.assertEqual(result["aggregate"]["interfaces"], ["eth0"])

    def test_delta_uses_elapsed_time_and_excludes_virtual(self):
        self.c._network_previous = {
            "eth0": (100, 200), "tun0": (1000, 2000), "lo": (3000, 3000),
        }
        result = self.fake({
            "eth0": Counter(bytes_recv=1100, bytes_sent=2200),
            "tun0": Counter(bytes_recv=9000, bytes_sent=9000),
            "lo": Counter(bytes_recv=9000, bytes_sent=9000),
        })
        self.assertEqual(result["aggregate"]["rx_bytes_per_sec"], 1000.0)
        self.assertEqual(result["aggregate"]["tx_bytes_per_sec"], 2000.0)
        self.assertTrue(result["ready"])
        self.assertEqual(result["active_interface"], "eth0")

    def test_counter_reset_is_missing_not_a_spike(self):
        self.c._network_previous = {"eth0": (10000, 10000)}
        result = self.fake({"eth0": Counter(bytes_recv=20, bytes_sent=30)})
        self.assertFalse(result["ready"])
        self.assertIsNone(result["aggregate"]["rx_bytes_per_sec"])
        self.assertIsNone(result["aggregate"]["tx_bytes_per_sec"])

    def test_pause_reset_discards_old_baseline(self):
        self.c._network_previous = {"eth0": (100, 200)}
        self.c._network_previous_monotonic = time.monotonic() - 100
        self.c.reset_network_baseline()
        self.assertEqual(self.c._network_previous, {})
        self.assertIsNone(self.c._network_previous_monotonic)


if __name__ == "__main__":
    unittest.main(verbosity=2)
