# Xinguan (芯观)

A Chinese, read-only hardware dashboard for Linux laptops, inspired by Mission Center.
Built with GTK 4 + libadwaita and validated on Ubuntu 24.04 ARM64 with a Moore Threads
AIBOOK / M1000.

![Xinguan overview](assets/screenshot-overview.png)

**Highlights**

- CPU total and per-core load, GPU utilization, memory and swap.
- Network download / upload rates for active physical NICs only.
- Separate PM01 / PM02 / PM00 power rails shown as CPU / GPU / Other.
- CPU / GPU temperatures, ACPI thermal zones, two fan tachometers, battery state.
- 60-sample live graphs, pause/resume, light/dark switch.

**Honest data boundaries**

- Whole-system power on AC is **not available** and is shown as unreadable; the three
  rails are never summed into a fake total.
- A whole-machine estimate appears only when exactly one system battery is discharging
  and every known external supply is confirmed off.
- Virtual interfaces (loopback, VPN, Docker) are excluded from network totals.
- Fans are read-only: no PWM interface or vendor fan command is available on the
  validated machine, so there is no fan slider.
- Missing readings are shown as “—”, never as zero. The app is read-only and sends
  no telemetry.

**Run from source**

```bash
sudo apt install python3-gi python3-gi-cairo python3-cairo python3-psutil \
                 gir1.2-gtk-4.0 gir1.2-adw-1
git clone https://github.com/chengminhua/xinguan.git
cd xinguan
./scripts/run.sh
```

**Test and build**

```bash
python3 -m unittest discover -s tests -v
python3 scripts/build_release.py
```

See [README.md](README.md) (Chinese) and [docs/使用说明.md](docs/使用说明.md) for details.

Licensed under GPL-3.0-or-later.
