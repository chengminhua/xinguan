#!/usr/bin/python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 chengminhua
"""Read-only metrics for the AIBOOK hardware panel.

Fast metrics come from Linux proc/sysfs. The vendor tool runs in a daemon
thread, never inside sample(), so its approximately 0.6 s query cannot hold
up the interface. All power numbers are watts; missing data stays None.
"""

from __future__ import annotations

import argparse
import copy
import datetime as dt
import json
import math
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

import psutil


STATUS_LABELS = {
    "Charging": "正在充电",
    "Discharging": "正在放电",
    "Full": "已充满",
    "Not charging": "未充电",
    "Unknown": "状态未知",
}
ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def _read(path: Path) -> str | None:
    try:
        return path.read_text().strip()
    except (OSError, UnicodeError):
        return None


def _number(path: Path, divisor: float = 1.0) -> float | None:
    value = _read(path)
    try:
        number = float(value) / divisor
        return number if math.isfinite(number) else None
    except (ValueError, TypeError, ZeroDivisionError):
        return None


def _nonnegative(value: float | None) -> float | None:
    return value if value is not None and value >= 0 else None


def _sorted_paths(root: Path, pattern: str) -> list[Path]:
    try:
        return sorted(root.glob(pattern), key=lambda p: p.name)
    except OSError:
        return []


class Collector:
    """One instance per panel; call sample() on the same sampling thread.

    Construction starts a vendor query worker. CPU percentages represent the
    interval since the previous sample (or construction for the first sample).
    Call close() when the window closes. The optional sysfs_root helps exercise
    power-state rules against fixture files without modifying actual sysfs.
    """

    def __init__(self, vendor_interval: float = 3.0,
                 sysfs_root: str | Path = "/sys", start_vendor: bool = True):
        self.sysfs = Path(sysfs_root)
        self.vendor_interval = max(2.0, float(vendor_interval))
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._vendor: dict[str, Any] = {
            "percent": None, "name": "M1000", "cpu_temp": None,
            "gpu_temp": None, "sampled_monotonic": None,
            "error": "等待 GPU 数据",
        }
        self._cpu_previous = self._cpu_ticks()
        self._network_previous: dict[str, tuple[int, int]] = {}
        self._network_previous_monotonic: float | None = None
        self._smi = shutil.which("mthreads-smi")
        self._thread: threading.Thread | None = None
        if start_vendor:
            self._thread = threading.Thread(
                target=self._vendor_loop, name="hardware-vendor-reader", daemon=True)
            self._thread.start()

    @staticmethod
    def _cpu_ticks() -> dict[str, tuple[float, float]]:
        result = {}
        text = _read(Path("/proc/stat")) or ""
        for line in text.splitlines():
            parts = line.split()
            if not parts or not re.fullmatch(r"cpu\d*", parts[0]):
                continue
            try:
                # guest/guest_nice are already included in user/nice.
                values = [float(item) for item in parts[1:9]]
                result[parts[0]] = (sum(values), values[3] + values[4])
            except (ValueError, IndexError):
                continue
        return result

    def _cpu(self) -> dict[str, Any]:
        current = self._cpu_ticks()
        percentages = {}
        for name, (total, idle) in current.items():
            previous = self._cpu_previous.get(name)
            delta = total - previous[0] if previous else 0
            percentages[name] = (
                round(min(100.0, max(0.0, (delta - idle + previous[1]) / delta * 100)), 1)
                if previous and delta > 0 else None)
        self._cpu_previous = current
        names = sorted((n for n in current if n != "cpu"), key=lambda n: int(n[3:]))
        frequencies = []
        for path in _sorted_paths(self.sysfs / "devices/system/cpu/cpufreq", "policy*"):
            value = _number(path / "scaling_cur_freq", 1000)
            if value is not None and value > 0:
                frequencies.append(value)
        return {
            "percent": percentages.get("cpu"),
            "cores": [percentages.get(name) for name in names],
            "count": len(names) or psutil.cpu_count(),
            "freq_mhz": round(sum(frequencies) / len(frequencies), 1) if frequencies else None,
            "source": "/proc/stat",
        }

    def _vendor_loop(self) -> None:
        if not self._smi:
            with self._lock:
                self._vendor["error"] = "未找到 mthreads-smi"
            return
        while not self._stop.is_set():
            started = time.monotonic()
            values: dict[str, Any] = {
                "percent": None, "name": "M1000", "cpu_temp": None,
                "gpu_temp": None, "sampled_monotonic": None, "error": None,
            }
            try:
                output = subprocess.run(
                    [self._smi, "-q", "cpu", "gpu"],
                    capture_output=True, text=True, timeout=3.0, check=True,
                ).stdout
                output = ANSI.sub("", output)
                for key, label in (("percent", "gpu utilization"),
                                   ("cpu_temp", "cpu temperature"),
                                   ("gpu_temp", "gpu temperature")):
                    match = re.search(re.escape(label) + r":\s*([-+]?\d+(?:\.\d+)?)", output, re.I)
                    if match:
                        value = float(match.group(1))
                        if (key == "percent" and 0 <= value <= 100) or (key != "percent" and -100 <= value <= 200):
                            values[key] = value
                values["sampled_monotonic"] = time.monotonic()
                if values["percent"] is None:
                    values["error"] = "厂商工具未返回 GPU 占用"
            except subprocess.TimeoutExpired:
                values["error"] = "GPU 查询超时"
            except (OSError, subprocess.SubprocessError, UnicodeError, ValueError):
                values["error"] = "GPU 查询暂不可用"
            with self._lock:
                self._vendor = values
            self._stop.wait(max(0.1, self.vendor_interval - (time.monotonic() - started)))

    def _vendor_snapshot(self) -> dict[str, Any]:
        with self._lock:
            result = copy.copy(self._vendor)
        sampled = result.pop("sampled_monotonic")
        result["age_s"] = round(time.monotonic() - sampled, 1) if sampled else None
        if sampled and time.monotonic() - sampled > max(10, self.vendor_interval * 3):
            result.update(percent=None, cpu_temp=None, gpu_temp=None, error="GPU 数据已过期")
        return result

    def _rails(self) -> dict[str, Any]:
        result: dict[str, Any] = {"cpu_w": None, "gpu_w": None, "other_w": None}
        source = {}
        # Verified against the installed mthreads-smi query using strace.
        # Firmware PM names survive a renumbering of ACPI or hwmon devices.
        mapping = {"PM00": "other_w", "PM01": "cpu_w", "PM02": "gpu_w"}
        for device in _sorted_paths(self.sysfs / "bus/acpi/devices", "ACPI000D:*"):
            firmware_path = _read(device / "path")
            pm = firmware_path.rsplit(".", 1)[-1] if firmware_path else None
            if pm not in mapping:
                continue
            key = mapping[pm]
            candidates = [device / "power1_average"]
            candidates.extend(_sorted_paths(device / "hwmon", "hwmon*/power1_average"))
            for path in candidates:
                value = _nonnegative(_number(path, 1_000_000))
                if value is not None:
                    result[key] = round(value, 3)
                    source[key] = {"name": pm, "path": str(path)}
                    break
        result["sources"] = source
        return result

    def _battery(self) -> dict[str, Any]:
        supplies = _sorted_paths(self.sysfs / "class/power_supply", "*")
        batteries = []
        external = []
        for device in supplies:
            kind = _read(device / "type")
            scope = _read(device / "scope")
            if scope == "Device":
                continue  # Mouse / keyboard batteries are not system power.
            if kind == "Battery":
                present = _number(device / "present")
                if present is None or present == 1:
                    batteries.append(device)
            elif kind is None or (device / "online").exists() or kind in {"Mains", "USB", "USB_DCP", "USB_CDP", "USB_ACA", "USB_C", "USB_PD", "USB_PD_DRP", "Wireless"}:
                external.append(_number(device / "online"))
        # Unknown or absent source detection is NOT proof that all power is off.
        ac_online = True if any(v == 1 for v in external) else (False if external and all(v == 0 for v in external) else None)
        battery: dict[str, Any] = {
            "present": bool(batteries), "percent": None, "status": None,
            "status_label": "未检测到系统电池", "voltage_v": None,
            "current_a": None, "power_w": None, "ac_online": ac_online,
            "source": None, "system_battery_count": len(batteries),
        }
        if not batteries:
            return battery
        device = next((p for p in batteries if p.name == "BAT0"), batteries[0])
        status = _read(device / "status")
        voltage = _nonnegative(_number(device / "voltage_now", 1_000_000))
        if voltage == 0:
            voltage = None  # A zero-voltage battery cannot power the laptop.
        current = _number(device / "current_now", 1_000_000)
        power = _number(device / "power_now", 1_000_000)
        method = "power_now"
        if power is None and voltage is not None and current is not None:
            power = voltage * current
            method = "voltage_now × current_now"
        capacity = _number(device / "capacity")
        if capacity is not None and not 0 <= capacity <= 100:
            capacity = None
        battery.update(
            percent=capacity, status=status,
            status_label=STATUS_LABELS.get(status, status or "状态未知"),
            voltage_v=voltage, current_a=abs(current) if current is not None else None,
            power_w=round(abs(power), 3) if power is not None else None,
            source=str(device), power_method=method if power is not None else None,
        )
        return battery

    def _temperatures(self, vendor: dict[str, Any]) -> list[dict[str, Any]]:
        result = []
        for name, key in (("CPU", "cpu_temp"), ("GPU", "gpu_temp")):
            result.append({"name": name, "celsius": vendor[key], "source": "mthreads-smi", "age_s": vendor["age_s"]})
        for device in _sorted_paths(self.sysfs / "class/thermal", "thermal_zone*"):
            try:
                number = int(device.name.removeprefix("thermal_zone"))
            except ValueError:
                continue
            # Identify TZ07 by firmware identity, not the transient zone index.
            # It carries a power/protection value rather than physical heat.
            acpi_path = _read(device / "device/path")
            if (acpi_path and acpi_path.endswith(".TZ07")) or (
                not acpi_path and ((device / "perf_limit").exists() or (device / "perf_mode").exists())
            ):
                continue
            value = _number(device / "temp", 1000)
            if value is not None and not -100 <= value <= 200:
                value = None
            name = acpi_path.rsplit(".", 1)[-1] if acpi_path else str(number + 1)
            result.append({"name": f"温区 {name}", "celsius": value, "source": str(device / "temp")})
        return result

    def _fans(self) -> list[dict[str, Any]]:
        paths = []
        for device in _sorted_paths(self.sysfs / "class/hwmon", "hwmon*"):
            for path in _sorted_paths(device, "fan*_input"):
                try:
                    identity = str(path.resolve())
                except OSError:
                    identity = str(path)
                paths.append((identity, path))
        result = []
        for index, (_, path) in enumerate(sorted(paths)):
            rpm = _nonnegative(_number(path))
            result.append({"name": f"风扇 {index}", "rpm": round(rpm) if rpm is not None else None, "source": str(path)})
        return result

    def _network(self) -> dict[str, Any]:
        """Return physical-interface network rates in bytes per second.

        Linux exposes cumulative counters.  We keep a baseline between samples,
        use the real elapsed time, and leave a rate missing while an interface
        is new or its counter has reset.  Only active physical interfaces are
        included in the aggregate; this avoids double-counting tun/docker/lo
        traffic on top of the underlying Wi-Fi or Ethernet device.
        """
        now = time.monotonic()
        interval = (now - self._network_previous_monotonic
                    if self._network_previous_monotonic is not None else None)
        self._network_previous_monotonic = now
        # Keep raw counters so a driver reset is visible as a negative delta;
        # psutil's nowrap compensation would turn that reset into a false spike.
        counters = psutil.net_io_counters(pernic=True, nowrap=False) or {}
        stats = psutil.net_if_stats()
        current: dict[str, tuple[int, int]] = {}
        for name, value in counters.items():
            try:
                current[name] = (int(value.bytes_recv), int(value.bytes_sent))
            except (AttributeError, TypeError, ValueError, OverflowError):
                continue
        previous = self._network_previous
        self._network_previous = current

        physical_up = []
        active_non_loopback = []
        for name in sorted(current):
            if name == "lo":
                continue
            stat = stats.get(name)
            is_up = bool(stat and stat.isup)
            physical = (self.sysfs / "class/net" / name / "device").exists()
            if is_up:
                active_non_loopback.append(name)
                if physical:
                    physical_up.append(name)
        # Do not silently fall back to VPN/container interfaces: their bytes
        # are often already present on the underlying physical NIC.
        included = physical_up
        interfaces = []
        for name in sorted(current):
            stat = stats.get(name)
            is_up = bool(stat and stat.isup)
            physical = (self.sysfs / "class/net" / name / "device").exists()
            rx_bps = tx_bps = None
            old = previous.get(name)
            if interval is not None and interval > 0 and old is not None:
                rx_delta = current[name][0] - old[0]
                tx_delta = current[name][1] - old[1]
                if rx_delta >= 0 and tx_delta >= 0:
                    rx_bps = round(rx_delta / interval, 2)
                    tx_bps = round(tx_delta / interval, 2)
            interfaces.append({
                "name": name,
                "is_up": is_up,
                "physical": physical,
                "included": name in included,
                "rx_bytes_per_sec": rx_bps,
                "tx_bytes_per_sec": tx_bps,
                "speed_mbps": getattr(stat, "speed", 0) if stat else 0,
            })
        selected = [item for item in interfaces if item["included"]]
        ready = bool(selected) and all(
            item["rx_bytes_per_sec"] is not None and item["tx_bytes_per_sec"] is not None
            for item in selected
        )
        aggregate = {
            "rx_bytes_per_sec": round(sum(item["rx_bytes_per_sec"] for item in selected), 2) if ready else None,
            "tx_bytes_per_sec": round(sum(item["tx_bytes_per_sec"] for item in selected), 2) if ready else None,
            "interface_count": len(selected),
            "interfaces": [item["name"] for item in selected],
        }
        return {
            "aggregate": aggregate,
            "active_interface": selected[0]["name"] if len(selected) == 1 else None,
            "interfaces": interfaces,
            "sample_interval_s": round(interval, 3) if interval is not None and interval > 0 else None,
            "ready": ready,
            "physical_available": bool(physical_up),
            "source": "psutil.net_io_counters(pernic=True)",
        }

    def sample(self) -> dict[str, Any]:
        """Return one JSON-compatible snapshot; does not invoke subprocesses."""
        started = time.monotonic()
        result: dict[str, Any] = {
            "timestamp": time.time(),
            "iso_time": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
            "errors": [],
        }
        try:
            result["cpu"] = self._cpu()
        except (OSError, ValueError, RuntimeError):
            result["cpu"] = {"percent": None, "cores": [], "count": psutil.cpu_count(), "freq_mhz": None}
            result["errors"].append("CPU 数据暂不可用")
        for key, fetcher in (("memory", psutil.virtual_memory), ("swap", psutil.swap_memory)):
            try:
                value = fetcher()
                # Consistent with Linux available memory: includes reclaimable cache.
                used = value.total - value.available if key == "memory" else value.used
                result[key] = {"used_bytes": used, "total_bytes": value.total, "percent": value.percent}
            except (OSError, ValueError, RuntimeError):
                result[key] = {"used_bytes": None, "total_bytes": None, "percent": None}
                result["errors"].append(f"{key} 数据暂不可用")
        try:
            result["network"] = self._network()
        except (OSError, ValueError, RuntimeError, TypeError):
            result["network"] = {
                "aggregate": {"rx_bytes_per_sec": None, "tx_bytes_per_sec": None,
                               "interface_count": 0, "interfaces": []},
                "active_interface": None, "interfaces": [], "sample_interval_s": None,
                "ready": False, "physical_available": False,
                "source": "psutil.net_io_counters(pernic=True)",
                "error": "网络数据暂不可用",
            }
            result["errors"].append("网络数据暂不可用")
        vendor = self._vendor_snapshot()
        result["gpu"] = {"percent": vendor["percent"], "name": vendor["name"], "age_s": vendor["age_s"], "error": vendor["error"], "source": "mthreads-smi"}
        result["battery"] = battery = self._battery()
        result["power"] = power = self._rails()
        power["whole_w"] = None
        if battery["ac_online"] is False and battery["status"] == "Discharging" and battery["system_battery_count"] == 1 and battery["power_w"] is not None:
            power["whole_w"] = battery["power_w"]
            power["whole_note"] = "电池供电 · 电池侧整机耗电估算"
        elif battery["ac_online"] is True:
            power["whole_note"] = "插电时暂无可靠的整机功率接口"
        elif battery["ac_online"] is None:
            power["whole_note"] = "外部供电状态未知，暂不估算整机功耗"
        else:
            power["whole_note"] = "电池未确认放电或读数不全，暂不估算整机功耗"
        result["temperatures"] = self._temperatures(vendor)
        result["fans"] = self._fans()
        result["sample_ms"] = round((time.monotonic() - started) * 1000, 2)
        return result

    def close(self) -> None:
        self._stop.set()

    def reset_network_baseline(self) -> None:
        """Discard the interval spanning a paused dashboard."""
        self._network_previous = {}
        self._network_previous_monotonic = None

    def __enter__(self) -> "Collector":
        return self

    def __exit__(self, *_args: Any) -> None:
        self.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="只读采样本机硬件指标")
    parser.add_argument("--sample", action="store_true", help="输出 JSON 采样（默认）")
    parser.add_argument("--count", type=int, default=1)
    parser.add_argument("--interval", type=float, default=1.0)
    args = parser.parse_args()
    with Collector() as collector:
        # Allow a full first CPU interval and the first background GPU query.
        time.sleep(max(1.0, args.interval))
        for index in range(max(1, args.count)):
            print(json.dumps(collector.sample(), ensure_ascii=False, indent=2), flush=True)
            if index < args.count - 1:
                time.sleep(max(0.1, args.interval))


if __name__ == "__main__":
    main()
