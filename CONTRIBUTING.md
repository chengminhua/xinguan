# 参与贡献

感谢你愿意改进芯观。提交之前，请先确认改动符合下面这些边界。这个项目的可信度来自“不猜数据”。

## 数据边界（硬性要求）

1. **不要伪造整机功耗。** 插电时没有可靠的整机总功率接口，界面必须继续显示“插电时不可读”。三路 PM 功率不能相加当作整机功耗。
2. **不要添加没在实机上验证过的风扇控制。** 现在只有 RPM 读取；没有 `pwm`、`pwm_enable` 或目标转速接口，`mthreads-smi` 也没有调速命令。不要写 `/sys` 风扇接口。
3. **缺失数据保持 `None` / “—”。** 不要用 0、估算值或上一次读数来填。未知温区和未知 PM 标签不要猜含义。
4. **默认只读。** 不修改 governor 或功率上限，也不动 Boost 和风扇策略；不启动后台常驻服务，不上传遥测。
5. **网络只统计物理网卡。** 虚拟接口的流量通常已经算在物理网卡里，不要再加一遍。
6. **新增数据源要说明来源和失效行为。** 在 PR 里写清 sysfs / proc 路径、单位，以及异常或缺失时显示什么。

如果需求与这些边界冲突，请先开 Issue 讨论。

## 开发环境

Ubuntu 24.04 上这样装依赖：

```bash
sudo apt install python3-gi python3-gi-cairo python3-cairo python3-psutil \
                 gir1.2-gtk-4.0 gir1.2-adw-1
```

建议再装上 `desktop-file-utils`，构建发布包时会用它校验桌面入口。

## 运行与测试

```bash
./scripts/run.sh                              # 从源码启动
python3 -m unittest discover -s tests -v      # 全部测试
```

测试只使用临时目录和模拟计数器，不会读写真实 sysfs。

提交前至少跑一遍：

```bash
python3 -m py_compile src/app.py src/metrics.py src/check_runtime.py \
                        scripts/build_release.py
python3 -m unittest discover -s tests -v
```

如果改动影响打包内容，再执行 `python3 scripts/build_release.py`，并检查 `dist/`。

## 代码风格

- Python 3.10+，缩进用 4 个空格；沿用现有文件结构，不引入大型框架。
- 采集逻辑放在 `src/metrics.py`，界面逻辑放在 `src/app.py`；`sample()` 内不调用子进程。
- 新指标用 `None` 表示不可读，返回值要保持 JSON 兼容（`json.dumps(..., allow_nan=False)` 必须能通过）。
- 中文界面文案保持简洁。技术名词保留原文，比如 CPU 与 GPU，以及 RPM 和 MiB。
- 不要提交个人路径、日志或凭证，也不要带上诊断数据和截图里的账号信息。

## 提交与 PR

- 一个 PR 只做一件事，说明动机、数据来源和验证方式。
- 提交信息建议写成 `模块: 简述`，比如 `metrics: 排除虚拟网卡重复计数`。
- PR 描述里附上测试命令和结果；改了界面就附截图。
- 新增传感器或机型支持时，说明实际硬件、系统版本，以及读不到时的表现。

## 许可证

提交即表示你同意以 [GPL-3.0-or-later](LICENSE) 授权你的贡献。
