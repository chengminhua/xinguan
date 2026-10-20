# 参与贡献

感谢你愿意改进芯观。提交前请先确认改动符合下面的边界；这个项目的可信度来自“不猜数据”。

## 数据边界（硬性要求）

1. **不要伪造整机功耗。** 插电时没有可靠的整机总功率接口，界面必须继续显示“插电时不可读”。三路 PM 功率不得相加冒充整机功耗。
2. **不要添加未经实机验证的风扇控制。** 当前只有 RPM 读取；没有 `pwm` / `pwm_enable` / 目标转速接口，`mthreads-smi` 也没有调速命令。不要写 `/sys` 风扇接口。
3. **缺失数据保持 `None` / “—”。** 不要用 0、估算值或上一次读数填补缺失；不要为未知温区、未知 PM 标签猜测含义。
4. **默认只读。** 不修改 governor、功率上限、Boost 或风扇策略；不启动后台常驻服务；不上传遥测。
5. **网络只统计物理网卡。** 虚拟接口的流量通常已包含在物理网卡计数里，不要重复合计。
6. **新增数据源必须给出来源与失效行为。** 在 PR 中说明 sysfs / proc 路径、单位、异常或缺失时的显示。

如果需求与以上边界冲突，请先开 Issue 讨论。

## 开发环境

Ubuntu 24.04：

```bash
sudo apt install python3-gi python3-gi-cairo python3-cairo python3-psutil \
                 gir1.2-gtk-4.0 gir1.2-adw-1
```

建议同时安装 `desktop-file-utils`（构建发布包时校验桌面入口）。

## 运行与测试

```bash
./scripts/run.sh                              # 从源码启动
python3 -m unittest discover -s tests -v      # 全部测试
```

测试只使用临时目录和模拟计数器，不会读写真实 sysfs。

提交前请至少执行：

```bash
python3 -m py_compile src/app.py src/metrics.py src/check_runtime.py \
                        scripts/build_release.py
python3 -m unittest discover -s tests -v
```

如果改动影响打包内容，再执行 `python3 scripts/build_release.py` 并检查 `dist/`。

## 代码风格

- Python 3.10+，4 空格缩进，遵循现有文件结构，不引入大型框架。
- 采集逻辑放在 `src/metrics.py`，界面逻辑放在 `src/app.py`；`sample()` 内不调用子进程。
- 新指标使用 `None` 表示不可读，保持返回值为 JSON 兼容类型（`json.dumps(..., allow_nan=False)` 必须通过）。
- 中文界面文案保持简洁；技术名词（CPU、GPU、RPM、MiB）保留原文。
- 不要提交个人路径、日志、诊断数据、截图中的账号信息或凭证。

## 提交与 PR

- 一次 PR 聚焦一件事，说明动机、数据来源和验证方式。
- 提交信息建议使用 `模块: 简述`，例如 `metrics: 排除虚拟网卡重复计数`。
- PR 描述里附上测试命令与结果；涉及界面的改动请附截图。
- 新传感器或新机型支持请说明实际硬件和系统版本，以及无法读取时的表现。

## 许可证

提交即表示你同意以 [GPL-3.0-or-later](LICENSE) 授权你的贡献。
