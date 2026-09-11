# benchmarks/：本地测量脚本（REV-001 / REV-002）

状态：测量基础设施，不是优化结果。这些脚本重建 `docs/reviews/2026-09-11/` 中
历史报告提到、但原始材料已丢失的四类局部测量。**不修改 `src/` 运行时代码。**

## 运行

```powershell
.venv\Scripts\python.exe benchmarks\environment.py
.venv\Scripts\python.exe benchmarks\probe_logical_reads.py --out <结果.json>
.venv\Scripts\python.exe benchmarks\counterexample_duplicate_id.py --out <结果.json>
.venv\Scripts\python.exe benchmarks\probe_plan_freeze.py --out <结果.json>
.venv\Scripts\python.exe benchmarks\kernel_benchmark.py --rows 20000 --files 200 --rounds 7 --seed 7 --out <结果.json>
```

测试：`python -m pytest tests/test_benchmarks.py`（要求 `pyproject.toml` 的
`pythonpath` 含 `benchmarks`）。

## 文件

| 文件 | 作用 |
|---|---|
| `environment.py` | REV-001：固定 commit、解释器、依赖、受测文件哈希、engine_fingerprint |
| `instrument.py` | 逻辑读取插桩：按调用点统计 `read_bounded` / `_read_sources` 次数与字节 |
| `probe_logical_reads.py` | run / resume / task_submit / artifact_read 各阶段的逻辑读取量 |
| `counterexample_duplicate_id.py` | 跨文件重复 ID 反例：分文件汇总再合并丢失异常且金额错误 |
| `probe_plan_freeze.py` | PlanSpec 浅冻结证据：嵌套 list 可变、hash 变化、重校验拒绝 |
| `kernels.py` | 汇总内核候选：延迟分配（lazy_groups）、整数分（int_cents） |
| `kernel_benchmark.py` | ≥62 例等价语料差分 + 种子化乱序计时，保存原始样本 |

## 边界

- 只统计**逻辑读取**（受信读取原语调用）；不是物理磁盘 I/O 或真实耗时结论。
- 内核计时是本机探索性数字；历史 59.89/55.61/39.22ms 不是必须达到的阈值。
- 合成输入；不接真实账号、不调用付费模型、不上传运行数据。
- 原始运行输出默认写 `.local/`（已 gitignore）；提交进仓库的只有
  `docs/reviews/2026-09-11/reproduction/` 下标注了环境的单次快照。
