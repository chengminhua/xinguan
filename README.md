# 芯观 · Xinguan

一个面向 Linux 笔记本的中文只读硬件监控面板，界面参考 Mission Center。它使用 GTK 4 和 libadwaita，在 Ubuntu 24.04 ARM64 的摩尔线程 AIBOOK / M1000 上完成编写和实测。

[![Release](https://img.shields.io/github/v/release/chengminhua/xinguan?display_name=tag&sort=semver)](https://github.com/chengminhua/xinguan/releases)
[![License: GPL-3.0-or-later](https://img.shields.io/badge/license-GPL--3.0--or--later-blue.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/platform-Ubuntu%2024.04%20ARM64-lightgrey.svg)](#运行要求)

![芯观总览](assets/screenshot-overview.png)

## 功能

- **总览**：把主要指标集中在一屏，其他页面可以看各项细节。
- **处理器**：CPU 总占用与 12 个逻辑核心的占用，另有平均频率和 GPU 占用。
- **内存**：物理内存和可用内存，交换空间单独列出。
- **网络**：活动物理网卡的下载与上传速率，保留最近 60 次采样的曲线。
- **功率**：CPU 对应 PM01，GPU 对应 PM02，Other 对应 PM00，三路分别显示。
- **温度**：CPU 和 GPU 的命名温度，加上系统温区；功率保护字段不当作温度。
- **风扇**：两路风扇的实时 RPM。
- **电池**：电量与充放电状态，以及电压、电流和供电来源。
- 界面每秒刷新，可以暂停和恢复，也能切换浅色或深色。窗口标题与应用名都是“芯观”。

![网络趋势](assets/screenshot-network.png)

## 数据边界

读不到的数据显示“—”，不做推测。

- **插电时不显示整机总功耗。** 本机没有可靠的整机功率接口，界面会明确显示“插电时不可读”。
- **三路功率不能相加。** CPU 读 PM01，GPU 读 PM02，Other 读 PM00。它们代表不同部件的功率；Other 只指厂商定义的其他部件功率，不能理解成电脑其余部分的全部耗电。
- **电池侧估算有前提。** 只有确认所有已知外部供电都已断开，并且机器只有一块系统电池且正在放电，同时电压、电流或 `power_now` 的读数有效，才会用电压 × 电流显示电池侧整机估算。电池充满后的残余电流不算整机功耗。
- **网络只统计物理网卡。** `lo`、VPN 隧道和 Docker 这类虚拟接口不与底层物理网卡重复合计。第一次采样只建立基线，计数器重置时显示“—”。
- **风扇只读。** 本机没有 `pwm`、`pwm_enable` 或目标转速接口，`mthreads-smi` 也没有调速命令。界面不提供风扇滑块，也不会写 `/sys` 风扇接口。
- **缺失不等于零。** 读不到的指标显示“—”，不补 0。
- **只读。** 不修改功率策略，不写 sysfs，也不设置开机自启或上传数据。关掉窗口就停止采集。

完整说明见 [docs/使用说明.md](docs/使用说明.md)。

## 运行要求

| 项目 | 要求 |
| --- | --- |
| 系统 | Ubuntu 24.04 ARM64（aarch64），已在 AIBOOK / M1000 实测 |
| 桌面 | GTK 4.14+、libadwaita 1.5+ |
| Python | 3.10+，含 PyGObject、pycairo 与 psutil |
| GPU 数据 | 可选，依赖设备自带的 `mthreads-smi` |

其他 ARM64 Linux 发行版理论上能用，但没有验证过。在 x86_64 上，界面和通用指标可以运行，GPU、功率这类厂商数据不可用。

## 从源码运行

```bash
sudo apt update
sudo apt install python3-gi python3-gi-cairo python3-cairo python3-psutil \
                 gir1.2-gtk-4.0 gir1.2-adw-1
git clone https://github.com/chengminhua/xinguan.git
cd xinguan
./scripts/run.sh
```

也可以直接运行 `python3 src/app.py`。程序固定用 Cairo 渲染（`GSK_RENDERER=cairo`），适配本机图形环境。

把入口安装到当前用户（写入 `~/.local/share/applications`，并把 `~/.local/bin/xinguan` 链接到源码启动脚本）：

```bash
./scripts/install-user.sh
./scripts/uninstall-user.sh   # 撤销
```

## 安装发布包

从 [Releases](https://github.com/chengminhua/xinguan/releases) 下载
`芯观-<版本>-Ubuntu24.04-ARM64.zip`，解压后执行：

```bash
cd 芯观-*-Ubuntu24.04-ARM64
bash 安装芯观.sh
```

安装脚本会校验 SHA256、确认系统，再通过 `apt` 安装 deb 和缺失的依赖。也可以手动安装：

```bash
sha256sum -c SHA256SUMS.txt
sudo apt install ./xinguan_*_arm64.deb
```

卸载用 `sudo apt remove xinguan`。发布包不带驱动、厂商工具或运行库。

## 测试

```bash
python3 -m unittest discover -s tests -v
```

- `tests/test_metrics.py`：27 项数据边界测试，覆盖供电、温度与风扇的读取规则，以及各种缺失数据。
- `tests/test_network.py`：4 项测试，覆盖网络基线、虚拟接口过滤和计数器重置。

测试只用临时 sysfs 目录和模拟计数器，不碰真实硬件。

## 构建发布包

需要 `dpkg-deb`，建议再装上 `desktop-file-utils`：

```bash
python3 scripts/build_release.py
```

`dist/` 里是 ZIP 包，里面有 ARM64 deb 和安装脚本，还带着中文说明与 `SHA256SUMS.txt`；旁边会生成同名的 `.sha256` 校验文件。版本号只写在 `VERSION` 里。

## 项目结构

```
src/app.py            GTK 4 / libadwaita 界面与图表
src/metrics.py        只读数据采集层（proc / sysfs / psutil / mthreads-smi）
src/check_runtime.py  发布包运行依赖检查
tests/                边界与回归测试
scripts/run.sh        从源码启动
scripts/install-user.sh / uninstall-user.sh
scripts/build_release.py
packaging/            deb 内容模板、启动器、桌面入口
assets/               图标与截图
docs/使用说明.md      面向使用者的完整说明
```

界面从下面这些本机接口取数。

| 指标 | 来源 |
| --- | --- |
| CPU 和内存、交换与网络 | `/proc/stat`、`psutil` |
| GPU 占用、CPU / GPU 温度 | `mthreads-smi -q cpu gpu`（后台线程，约 3 秒一次） |
| 部件功率 | `/sys/bus/acpi/devices/ACPI000D:*/power1_average` |
| 系统温区 | `/sys/class/thermal/thermal_zone*/temp` |
| 风扇 | `/sys/class/hwmon/hwmon*/fan*_input` |
| 电池与外部供电 | `/sys/class/power_supply/*` |

## 已知限制

- 只在 AIBOOK / M1000 上验证过，其他机型的传感器名称和功率映射可能不一样。
- 插电整机功耗读不到，原因是接口没有这项数据，界面没有漏做。
- 风扇只能读转速，没有可用的调速接口。
- 应用 ID 仍然是 `local.ahua.HardwarePanel`，用于兼容早期的本机安装；装到别的系统不影响使用。
- 三分钟左右的短时测试不等于长期稳定性；实测单核 CPU 占用约 1.8%，RSS 约 200–220 MiB。

## 参与贡献

欢迎提交 Issue 和 PR。动手前先看 [CONTRIBUTING.md](CONTRIBUTING.md) 的“数据边界”一节。不要为了界面好看去伪造整机功耗或风扇控制，也不要拿 0 填补读不到的数据。

## 许可证

[GPL-3.0-or-later](LICENSE)。GTK 与 libadwaita、PyGObject 和 psutil 等第三方依赖遵循各自的许可证，本项目不重新分发它们。

## 致谢

- 界面布局参考了 [Mission Center](https://missioncenter.io/) 的侧栏和卡片。
- 功率测量范围参考[摩尔线程官方功率说明](https://docs.mthreads.com/e300/version-1.5.0/e300-doc-online/boot_system_config/power_capping/)。
