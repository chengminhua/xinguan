#!/usr/bin/python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 chengminhua
"""A small native, read-only hardware dashboard for this AIBOOK."""
import argparse
from collections import deque
from datetime import datetime
import json
import math
import os
from pathlib import Path
import sys
import time

os.environ.setdefault("GSK_RENDERER", "cairo")
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk
from metrics import Collector

COLORS = {"cpu": "#9562cf", "gpu": "#448fe3", "memory": "#35a77b",
          "other": "#d49a32", "temp": "#dc7656", "fan": "#8174c4", "battery": "#42ad76",
          "network_rx": "#35a77b", "network_tx": "#9562cf"}
CSS = """
@define-color accent_color #9562cf;
@define-color accent_bg_color #9562cf;
@define-color accent_fg_color #ffffff;
.app-root { background: @window_bg_color; color: @window_fg_color; }
.sidebar { background: alpha(@window_fg_color, 0.035); border-right: 1px solid alpha(@window_fg_color, 0.08); }
.sidebar list { background: transparent; }
.sidebar row { border-radius: 12px; margin: 3px 10px; padding: 12px; }
.sidebar row:selected { background: alpha(@accent_color, 0.13); color: @window_fg_color; }
.sidebar-title { font-size: 17px; font-weight: 700; }
.nav-title { font-weight: 600; font-size: 14px; }
.nav-value { font-size: 12px; opacity: 0.62; margin-top: 4px; }
.page-title { font-size: 27px; font-weight: 800; }
.subtitle { opacity: 0.60; font-size: 12px; }
.metric-card { background: @card_bg_color; border: 1px solid alpha(@window_fg_color, 0.09); border-radius: 16px; padding: 17px; }
.card-title { font-size: 15px; font-weight: 700; }
.metric { font-size: 29px; font-weight: 700; font-feature-settings: "tnum"; }
.metric-small { font-size: 23px; font-weight: 700; font-feature-settings: "tnum"; }
.hint { font-size: 11px; opacity: 0.62; }
.note { font-size: 12px; opacity: 0.75; }
.core-caption { font-size: 10px; opacity: 0.65; }
.pill { border-radius: 20px; padding: 5px 10px; background: alpha(@accent_color, 0.10); font-size: 12px; }
.section-gap { margin-top: 7px; }
.statusbar { font-size: 11px; opacity: 0.62; padding: 8px 22px; border-top: 1px solid alpha(@window_fg_color, 0.07); }
progressbar trough { min-height: 5px; min-width: 0; border-radius: 5px; }
progressbar progress { min-height: 5px; border-radius: 5px; }
"""

def label(text="", cls=None, xalign=0):
    w = Gtk.Label(label=text, xalign=xalign)
    if cls:
        for c in cls.split():
            w.add_css_class(c)
    return w

def box(orientation=Gtk.Orientation.VERTICAL, spacing=6):
    return Gtk.Box(orientation=orientation, spacing=spacing)

def pretty(value, unit="", digits=1):
    if value is None:
        return "—"
    return f"{value:,.{digits}f}{unit}"

def gib(value):
    return "—" if value is None else f"{value / 1024**3:.1f} GiB"

def rate(value):
    """Format a byte-per-second value without confusing B/s and bit/s."""
    if value is None:
        return "—"
    value = float(value)
    if value >= 1024 ** 2:
        return f"{value / 1024 ** 2:.1f} MiB/s"
    if value >= 1024:
        return f"{value / 1024:.1f} KiB/s"
    return f"{value:.0f} B/s"

def rgb(h):
    return tuple(int(h[i:i+2], 16) / 255 for i in (1, 3, 5))

class Graph(Gtk.DrawingArea):
    """One cairo draw per sample, with missing readings left as gaps."""
    def __init__(self, series, colors, fixed_max=None, height=64):
        super().__init__()
        self.series = series
        self.colors = colors
        self.fixed_max = fixed_max
        self.set_content_height(height)
        self.set_hexpand(True)
        self.set_draw_func(self.draw)

    def draw(self, area, cr, width, height):
        top, bottom = 4, height - 6
        h = max(1, bottom - top)
        values = [v for s in self.series for v in s if v is not None]
        maximum = self.fixed_max or max(1, max(values, default=0) * 1.18)
        dark = Adw.StyleManager.get_default().get_dark()
        ink = 1 if dark else 0
        cr.set_source_rgba(ink, ink, ink, 0.075)
        cr.set_line_width(1)
        for i in range(5):
            y = top + h * i / 4
            cr.move_to(0, y); cr.line_to(width, y)
        for i in range(7):
            x = width * i / 6
            cr.move_to(x, top); cr.line_to(x, bottom)
        cr.stroke()
        for series, color in zip(self.series, self.colors):
            chunks, chunk = [], []
            n = len(series)
            for i, v in enumerate(series):
                if v is None:
                    if chunk: chunks.append(chunk)
                    chunk = []
                    continue
                x = width * (60 - n + i) / 59
                y = bottom - min(1, max(0, v / maximum)) * h
                chunk.append((x, y))
            if chunk: chunks.append(chunk)
            for points in chunks:
                if len(points) < 2: continue
                cr.move_to(points[0][0], bottom)
                for x,y in points: cr.line_to(x,y)
                cr.line_to(points[-1][0], bottom); cr.close_path()
                cr.set_source_rgba(*rgb(color), 0.11); cr.fill()
                cr.move_to(*points[0])
                for x,y in points[1:]: cr.line_to(x,y)
                cr.set_source_rgb(*rgb(color)); cr.set_line_width(1.8); cr.stroke()

class Card(Gtk.Box):
    def __init__(self, title, color, detail=False):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=7)
        self.add_css_class("metric-card")
        self.set_hexpand(True)
        self.title = label(title, "card-title")
        self.append(self.title)
        self.fields = {}
        self.graphs = []
        self.detail = detail
        self.color = color

    def field(self, key, text="—", cls="metric", parent=None):
        w = label(text, cls)
        w.set_selectable(True)
        self.fields[key] = w
        (parent or self).append(w)
        return w

    def text(self, text, cls="hint"):
        w = label(text, cls)
        w.set_wrap(True)
        self.append(w)
        return w

    def graph(self, series, colors, maximum=None):
        g = Graph(series, colors, maximum, 165 if self.detail else 58)
        self.append(g); self.graphs.append(g)

    def set(self, key, value):
        if key in self.fields: self.fields[key].set_text(value)

class Window(Adw.ApplicationWindow):
    PAGES = [("overview", "总览", "view-grid-symbolic"),
             ("cpu", "处理器", "computer-chip-symbolic"),
             ("memory", "内存", "drive-harddisk-symbolic"),
             ("network", "网络", "network-wired-symbolic"),
             ("power", "功率", "power-profile-performance-symbolic"),
             ("temp", "温度", "weather-clear-symbolic"),
             ("fan", "风扇", "emblem-system-symbolic"),
             ("battery", "电池", "battery-symbolic")]

    def __init__(self, app, options):
        super().__init__(application=app, title="芯观")
        self.options = options
        self.set_default_size(1160, 900)
        self.set_size_request(760, 620)
        self.collector = Collector()
        self.history = {k:deque(maxlen=60) for k in ["cpu", "gpu", "memory", "net_rx", "net_tx", "cpu_w", "gpu_w", "other_w", "temp0", "temp1", "fan0", "fan1", "battery"]}
        self.paused = False
        self.last_data = None
        self.sample_count = 0
        self.started = time.monotonic()
        self.cards = []
        self.nav_values = {}
        self.live_labels = []
        self.closed = False
        self.connect("close-request", self.on_close)

        root = box(spacing=0)
        root.add_css_class("app-root")
        header = Adw.HeaderBar()
        header.set_title_widget(Adw.WindowTitle(title="芯观", subtitle="硬件状态 · 实时掌握"))
        self.pause_button = Gtk.Button(icon_name="media-playback-pause-symbolic", tooltip_text="暂停刷新")
        self.pause_button.connect("clicked", self.toggle_pause)
        header.pack_end(self.pause_button)
        theme = Gtk.Button(icon_name="display-brightness-symbolic", tooltip_text="切换浅色 / 深色")
        theme.connect("clicked", self.toggle_theme)
        header.pack_end(theme)
        root.append(header)

        body = box(Gtk.Orientation.HORIZONTAL, 0)
        body.set_vexpand(True)
        side = box(spacing=6); side.add_css_class("sidebar"); side.set_size_request(185, -1)
        side_title = label("设备", "sidebar-title"); side_title.set_margin_start(23); side_title.set_margin_top(20); side_title.set_margin_bottom(12)
        side.append(side_title)
        self.nav = Gtk.ListBox(); self.nav.set_selection_mode(Gtk.SelectionMode.SINGLE)
        for key, title, icon in self.PAGES:
            row = Gtk.ListBoxRow(); row.key = key
            content = box(Gtk.Orientation.HORIZONTAL, 11)
            im = Gtk.Image.new_from_icon_name(icon); im.set_pixel_size(21)
            content.append(im)
            texts = box(spacing=1); texts.append(label(title, "nav-title"))
            value = label("所有指标" if key == "overview" else "读取中…", "nav-value")
            texts.append(value); self.nav_values[key] = value
            content.append(texts); row.set_child(content); self.nav.append(row)
        side.append(self.nav)
        spacer = box(); spacer.set_vexpand(True); side.append(spacer)
        side_bottom = label("每秒刷新 · 最近 60 次采样", "hint")
        side_bottom.set_margin_bottom(20); side_bottom.set_margin_start(20); side_bottom.set_margin_end(14)
        side.append(side_bottom); body.append(side)

        self.stack = Gtk.Stack(); self.stack.set_hexpand(True); self.stack.set_vexpand(True)
        self.stack.set_hhomogeneous(False)
        self.stack.set_vhomogeneous(False)
        self.stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.stack.set_transition_duration(140)
        for key,title,_ in self.PAGES:
            page = box(spacing=16)
            for method in [page.set_margin_start,page.set_margin_end]: method(22)
            page.set_margin_top(18); page.set_margin_bottom(20)
            heading = box(Gtk.Orientation.HORIZONTAL, 12)
            htexts = box(spacing=4); htexts.set_hexpand(True)
            htexts.append(label("性能总览" if key == "overview" else title, "page-title"))
            subtitles = {"overview":"主要指标集中查看，图表保留最近 60 次采样", "cpu":"CPU 整体与各核心占用 · GPU 使用情况", "memory":"物理内存与交换空间", "network":"活动物理网卡的下载 / 上传趋势 · 最近 60 次采样", "power":"CPU、GPU 与 Other 独立显示", "temp":"系统传感器与芯片温度", "fan":"两路风扇实时转速", "battery":"电池状态与供电来源"}
            htexts.append(label(subtitles[key], "subtitle")); heading.append(htexts)
            live = label("● 实时", "pill"); live.set_valign(Gtk.Align.CENTER); heading.append(live)
            self.live_labels.append(live)
            page.append(heading)
            if key == "overview":
                grid = Gtk.Grid(column_spacing=14, row_spacing=14)
                grid.set_column_homogeneous(True)
                for i, kind in enumerate(["cpu", "memory", "network", "power", "temp", "fan", "battery"]):
                    card = self.make_card(kind, False)
                    grid.attach(card, i % 2, i // 2, 1, 1)
                page.append(grid)
            else:
                page.append(self.make_card(key, True))
            scroller = Gtk.ScrolledWindow(); scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
            scroller.set_child(page); self.stack.add_named(scroller,key)
        body.append(self.stack); root.append(body)
        self.status = label("正在读取本机传感器…", "statusbar"); root.append(self.status)
        self.set_content(root)
        self.paintable = Gtk.WidgetPaintable.new(root)
        self.nav.connect("row-selected", self.select_page)
        self.nav.select_row(self.nav.get_row_at_index(0))
        GLib.idle_add(self.first_tick)
        self.timer = GLib.timeout_add_seconds(1, self.tick)
        if options.diagnostics:
            Path(options.diagnostics).mkdir(parents=True, exist_ok=True)
            GLib.timeout_add_seconds(6, self.capture)
        if options.duration:
            GLib.timeout_add_seconds(options.duration, self.finish_diagnostics)

    def make_card(self, kind, detail):
        names = {"cpu":"处理器", "memory":"内存与交换空间", "network":"网络", "power":"部件功率", "temp":"温度", "fan":"风扇", "battery":"电池与供电"}
        c = Card(names[kind], COLORS.get(kind, COLORS["cpu"]), detail)
        c.kind = kind
        self.cards.append(c)
        if kind == "cpu":
            line = box(Gtk.Orientation.HORIZONTAL, 15)
            c.field("cpu",parent=line); c.field("gpu", "GPU —", "note", line).set_valign(Gtk.Align.END)
            c.append(line)
            c.graph([self.history["cpu"],self.history["gpu"]], [COLORS["cpu"],COLORS["gpu"]],100)
            c.field("summary", "读取中…", "hint")
            c.core_grid = Gtk.Grid(column_spacing=10,row_spacing=8)
            c.core_grid.set_column_homogeneous(True); c.core_widgets=[]; c.append(c.core_grid)
            if detail: c.text("紫色：CPU 总占用　蓝色：GPU 占用。GPU 数据约每 3 秒更新。")
        elif kind == "memory":
            c.field("memory")
            c.field("used", "— / —", "note")
            c.graph([self.history["memory"]],[COLORS["memory"]],100)
            c.field("swap", "交换空间 —", "note")
            c.swap_bar = Gtk.ProgressBar(); c.append(c.swap_bar)
            c.field("available", "", "hint")
        elif kind == "network":
            row = box(Gtk.Orientation.HORIZONTAL, 16); row.set_homogeneous(True)
            for key, title in [("net_rx", "下载"), ("net_tx", "上传")]:
                group = box(spacing=2); group.append(label(title, "hint"))
                c.field(key, cls="metric-small", parent=group); row.append(group)
            c.append(row)
            c.graph([self.history["net_rx"], self.history["net_tx"]],
                    [COLORS["network_rx"], COLORS["network_tx"]])
            c.field("interface", "正在等待第二次采样…", "note").set_wrap(True)
            c.field("interfaces", "", "hint").set_wrap(True)
            c.text("绿色下载 · 紫色上传 · 单位为 KiB/s 或 MiB/s", "hint")
            if detail:
                c.text("趋势只统计活动的真实物理网卡；lo、VPN 隧道和 Docker 等虚拟接口不与物理网卡重复合计。首次采样用于建立基线。", "note")
        elif kind == "power":
            row = box(Gtk.Orientation.HORIZONTAL, 16); row.set_homogeneous(True)
            for key,title in [("cpu_w","CPU"),("gpu_w","GPU"),("other_w","Other")]:
                group=box(spacing=2); group.append(label(title,"hint")); c.field(key,cls="metric-small",parent=group); row.append(group)
            c.append(row)
            c.graph([self.history[k] for k in ["cpu_w","gpu_w","other_w"]],[COLORS[k] for k in ["cpu","gpu","other"]])
            c.field("whole", "整机功耗：读取中…", "note").set_wrap(True)
            c.text("紫 CPU · 蓝 GPU · 黄 Other｜三路不合计为整机功耗")
            if detail:
                c.text("来源：PM01 / PM02 / PM00。Other 是厂商定义的其他部件功率，不能视为电脑其余全部耗电。", "note")
                c.text("插电时没有可靠的整机功率接口。纯电池供电并确认正在放电时，才按电压 × 电流显示电池侧整机估算。", "note")
        elif kind == "temp":
            c.field("main", "读取中…", "metric-small")
            c.field("secondary", "", "note")
            c.graph([self.history["temp0"],self.history["temp1"]],[COLORS["temp"],COLORS["gpu"]])
            c.field("zones", "", "hint").set_wrap(True)
            if detail: c.text("已确认名称的 CPU / GPU 温度单独标注；其余保留传感器名称。功率保护字段不作为摄氏温度显示。", "note")
        elif kind == "fan":
            row=box(Gtk.Orientation.HORIZONTAL,16); row.set_homogeneous(True)
            for i in range(2):
                group=box(spacing=2); group.append(label(f"风扇 {i+1}","hint")); c.field(f"fan{i}",cls="metric-small",parent=group); row.append(group)
            c.append(row)
            c.graph([self.history["fan0"],self.history["fan1"]],[COLORS["fan"],COLORS["gpu"]])
            c.text("RPM · 每分钟转数")
        elif kind == "battery":
            row=box(Gtk.Orientation.HORIZONTAL,16)
            c.field("percent",parent=row); c.field("state", "读取中…", "note", row).set_valign(Gtk.Align.CENTER)
            c.append(row)
            c.battery_bar=Gtk.ProgressBar(); c.append(c.battery_bar)
            c.field("electrical", "", "note")
            c.field("flow", "", "note")
            c.field("estimate", "", "hint").set_wrap(True)
            if detail: c.text("电池功率只描述电池端充放电。外部供电期间不能用它代表整机耗电；充满时传感器也可能保留非零电流。", "note")
        return c

    def select_page(self, nav, row):
        if row: self.stack.set_visible_child_name(row.key)

    def toggle_pause(self, button):
        self.paused = not self.paused
        button.set_icon_name("media-playback-start-symbolic" if self.paused else "media-playback-pause-symbolic")
        button.set_tooltip_text("继续刷新" if self.paused else "暂停刷新")
        for live in self.live_labels:
            live.set_text("Ⅱ 已暂停" if self.paused else "● 实时")
        self.status.set_text("已暂停刷新；当前显示最后一次采样" if self.paused else "恢复实时采样…")
        if not self.paused:
            self.collector.reset_network_baseline()
            self.tick()

    def toggle_theme(self, _button):
        style=Adw.StyleManager.get_default()
        style.set_color_scheme(Adw.ColorScheme.FORCE_LIGHT if style.get_dark() else Adw.ColorScheme.FORCE_DARK)
        for c in self.cards:
            for g in c.graphs:g.queue_draw()

    def tick(self):
        if self.closed: return GLib.SOURCE_REMOVE
        if self.paused: return GLib.SOURCE_CONTINUE
        try:
            data=self.collector.sample()
            self.last_data=data; self.sample_count+=1
            self.update_values(data)
            self.status.set_text(f"已更新 {datetime.now():%H:%M:%S}　·　只读监测　·　— 表示当前无法读取")
            if self.options.diagnostics:
                p=Path(self.options.diagnostics)
                payload={"sample_count":self.sample_count,"elapsed_s":round(time.monotonic()-self.started,2),"data":data}
                pending=p/"latest.tmp"
                pending.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding="utf-8")
                pending.replace(p/"latest.json")
        except Exception as exc:
            self.status.set_text("本次读取失败，下一秒重试")
            print(f"sample error: {type(exc).__name__}: {exc}",file=sys.stderr,flush=True)
        return GLib.SOURCE_CONTINUE

    def first_tick(self):
        self.tick()
        return GLib.SOURCE_REMOVE

    def update_values(self,d):
        cpu=d.get("cpu",{}); gpu=d.get("gpu",{}); mem=d.get("memory",{}); swap=d.get("swap",{})
        network=d.get("network",{}); aggregate=network.get("aggregate",{})
        power=d.get("power",{}); temps=d.get("temperatures",[]); fans=d.get("fans",[]); bat=d.get("battery",{})
        preferred=sorted(temps,key=lambda t:0 if "CPU" in t.get("name","").upper() else 1 if "GPU" in t.get("name","").upper() else 2)
        # Keep each temperature curve attached to its named sensor even when a
        # query is temporarily missing; never splice an ACPI zone into CPU/GPU.
        ts=preferred
        reading={"cpu":cpu.get("percent"),"gpu":gpu.get("percent"),"memory":mem.get("percent"),"battery":bat.get("percent"),
                 "net_rx":aggregate.get("rx_bytes_per_sec"),"net_tx":aggregate.get("tx_bytes_per_sec")}
        reading.update({k:power.get(k) for k in ["cpu_w","gpu_w","other_w"]})
        for i in range(2):
            reading[f"temp{i}"]=ts[i].get("celsius") if len(ts)>i else None
            reading[f"fan{i}"]=fans[i].get("rpm") if len(fans)>i else None
        for k,v in reading.items():self.history[k].append(v)
        whole=power.get("whole_w")
        whole_text=f"整机估算：{pretty(whole,' W')} · 电池供电" if whole is not None else "整机功耗：插电时不可读" if bat.get("ac_online") is True else "整机功耗：当前不可读"
        self.nav_values["cpu"].set_text("CPU "+pretty(cpu.get("percent"),"%"))
        self.nav_values["memory"].set_text(gib(mem.get("used_bytes")))
        self.nav_values["network"].set_text("↓ "+rate(aggregate.get("rx_bytes_per_sec")))
        self.nav_values["power"].set_text("CPU "+pretty(power.get("cpu_w")," W"))
        self.nav_values["temp"].set_text(pretty(ts[0].get("celsius")," °C") if ts else "暂不可用")
        self.nav_values["fan"].set_text(pretty(reading["fan0"]," RPM",0))
        self.nav_values["battery"].set_text(pretty(bat.get("percent"),"%",0)+" · "+bat.get("status_label","未知"))
        for c in self.cards:
            if c.kind=="cpu":
                c.set("cpu",pretty(cpu.get("percent"),"%")); c.set("gpu","GPU "+pretty(gpu.get("percent"),"%"))
                c.set("summary",f"{cpu.get('count', '—')} 个逻辑核心　·　"+pretty(cpu.get("freq_mhz")," MHz",0))
                cores=cpu.get("cores",[])
                if len(c.core_widgets)!=len(cores):
                    child=c.core_grid.get_first_child()
                    while child:
                        nxt=child.get_next_sibling(); c.core_grid.remove(child); child=nxt
                    c.core_widgets=[]
                    columns=4 if c.detail else 6
                    for i in range(len(cores)):
                        group=box(spacing=2); caption=label(f"{i+1}","core-caption"); bar=Gtk.ProgressBar()
                        group.append(caption);group.append(bar);c.core_grid.attach(group,i%columns,i//columns,1,1)
                        c.core_widgets.append((caption,bar))
                for i,(value,(caption,bar)) in enumerate(zip(cores,c.core_widgets)):
                    caption.set_text(f"{i+1} · {pretty(value,'%',0)}");bar.set_fraction(max(0,min(1,(value or 0)/100)))
            elif c.kind=="memory":
                c.set("memory",pretty(mem.get("percent"),"%"));c.set("used",f"{gib(mem.get('used_bytes'))} / {gib(mem.get('total_bytes'))}")
                c.set("swap",f"交换空间　{gib(swap.get('used_bytes'))} / {gib(swap.get('total_bytes'))}")
                c.swap_bar.set_fraction(max(0,min(1,(swap.get("percent") or 0)/100)))
                available=mem.get("available_bytes")
                if available is None and mem.get("total_bytes") is not None and mem.get("used_bytes") is not None: available=mem["total_bytes"]-mem["used_bytes"]
                c.set("available","可用内存　"+gib(available))
            elif c.kind=="network":
                c.set("net_rx", rate(aggregate.get("rx_bytes_per_sec")))
                c.set("net_tx", rate(aggregate.get("tx_bytes_per_sec")))
                names=aggregate.get("interfaces") or []
                if not network.get("physical_available"):
                    c.set("interface", "没有检测到可确认的活动物理网卡")
                elif not network.get("ready"):
                    c.set("interface", "正在等待第二次采样…")
                else:
                    c.set("interface", "统计范围："+"、".join(names)+"（物理网卡合计）")
                excluded=[item["name"] for item in network.get("interfaces",[]) if not item.get("included")]
                c.set("interfaces", "已排除："+"、".join(excluded) if excluded else "")
            elif c.kind=="power":
                for k in ["cpu_w","gpu_w","other_w"]:c.set(k,pretty(power.get(k)," W"))
                c.set("whole",whole_text)
            elif c.kind=="temp":
                c.set("main",f"{ts[0]['name']}　{pretty(ts[0]['celsius'],' °C')}" if ts else "温度暂不可用")
                c.set("secondary",f"{ts[1]['name']}　{pretty(ts[1]['celsius'],' °C')}" if len(ts)>1 else "")
                c.set("zones","　".join(f"{t['name']} {pretty(t['celsius'],'°',0)}" for t in ts[2:]))
            elif c.kind=="fan":
                for i in range(2):c.set(f"fan{i}",pretty(reading[f"fan{i}"]," RPM",0))
            elif c.kind=="battery":
                c.set("percent",pretty(bat.get("percent"),"%",0))
                source="外部供电" if bat.get("ac_online") is True else "电池供电" if bat.get("ac_online") is False else "供电来源未知"
                c.set("state",source+" · "+bat.get("status_label","未知"))
                c.battery_bar.set_fraction(max(0,min(1,(bat.get("percent") or 0)/100)))
                c.set("electrical",pretty(bat.get("voltage_v")," V",2)+"　·　"+pretty(bat.get("current_a")," A",3))
                if bat.get("status")=="Full":flow="电池已充满 · 电流读数不代表整机耗电"
                else:flow="电池端功率　"+pretty(bat.get("power_w")," W")
                c.set("flow",flow); c.set("estimate",whole_text)
            for g in c.graphs:g.queue_draw()

    def capture(self):
        """Render this application's own widget tree, never another window."""
        try:
            widget=self.get_content()
            widget.allocate(widget.get_width(),widget.get_height(),-1,None)
            snap=Gtk.Snapshot.new()
            widget.get_parent().snapshot_child(widget,snap)
            node=snap.to_node()
            if node is None:
                raise RuntimeError(f"empty snapshot; mapped={widget.get_mapped()} size={widget.get_width()}x{widget.get_height()}")
            texture=self.get_renderer().render_texture(node,None)
            path=Path(self.options.diagnostics)/"panel.png"
            texture.save_to_png(str(path))
        except Exception as exc:print(f"capture error: {exc}",file=sys.stderr,flush=True)
        return GLib.SOURCE_REMOVE

    def finish_diagnostics(self):
        if self.options.diagnostics:self.capture()
        self.close()
        return GLib.SOURCE_REMOVE

    def on_close(self,*_):
        self.closed=True
        if hasattr(self,"timer"):GLib.source_remove(self.timer)
        if hasattr(self.collector,"close"):self.collector.close()
        return False

class Application(Adw.Application):
    def __init__(self,options):
        GLib.set_prgname("xinguan")
        GLib.set_application_name("芯观")
        super().__init__(application_id="local.ahua.HardwarePanel",flags=Gio.ApplicationFlags.DEFAULT_FLAGS)
        self.options=options

    def do_activate(self):
        win=self.get_active_window()
        if not win:
            css=Gtk.CssProvider();css.load_from_data(CSS.encode())
            Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(),css,Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
            Adw.StyleManager.get_default().set_color_scheme(Adw.ColorScheme.PREFER_LIGHT)
            Gtk.Window.set_default_icon_name("local.ahua.HardwarePanel")
            win=Window(self,self.options)
        win.present()

def main():
    parser=argparse.ArgumentParser(description="芯观 · AIBOOK 实时硬件监测")
    parser.add_argument("--diagnostics",help="将本应用的采样和渲染保存到指定目录")
    parser.add_argument("--duration",type=int,help="诊断运行秒数，之后自动退出")
    options=parser.parse_args()
    return Application(options).run([sys.argv[0]])

if __name__=="__main__":sys.exit(main())
