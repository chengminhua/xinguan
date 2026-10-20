#!/usr/bin/python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 chengminhua
"""Check runtime dependencies before starting the packaged application."""
import sys

try:
    if sys.version_info < (3, 10):
        raise RuntimeError("需要 Python 3.10 或更高版本")
    import gi

    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    gi.require_foreign("cairo")
    from gi.repository import Gtk, Adw
    import cairo  # noqa: F401  (import check only)
    import psutil  # noqa: F401  (import check only)

    if (Gtk.get_major_version(), Gtk.get_minor_version()) < (4, 14):
        raise RuntimeError("需要 GTK 4.14 或更高版本")
    if (Adw.get_major_version(), Adw.get_minor_version()) < (1, 5):
        raise RuntimeError("需要 libadwaita 1.5 或更高版本")
except (ImportError, ValueError, RuntimeError) as exc:
    print(f"芯观运行环境不完整：{exc}", file=sys.stderr)
    print("请在 Ubuntu 24.04 ARM64 上通过 apt 安装本软件包以补全依赖。", file=sys.stderr)
    sys.exit(1)

if "--check" in sys.argv:
    print("芯观运行依赖检查通过")
