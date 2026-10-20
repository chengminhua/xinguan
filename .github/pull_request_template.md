## 这个 PR 做了什么

<!-- 简要说明动机和改动范围 -->

## 数据来源与失效行为

<!-- 新增或修改指标时必填：读取路径、单位、读不到时显示什么 -->

## 验证

- [ ] `python3 -m py_compile src/app.py src/metrics.py src/check_runtime.py scripts/build_release.py`
- [ ] `python3 -m unittest discover -s tests -v`
- [ ] 界面改动已附截图
- [ ] 打包内容改动已执行 `python3 scripts/build_release.py`

## 边界检查

- [ ] 没有伪造插电整机功耗，也没有把三路功率相加
- [ ] 没有添加未实机验证的风扇控制或 sysfs 写入
- [ ] 缺失数据仍显示“—”而不是 0
- [ ] 没有提交个人路径、日志、凭证或诊断数据
