# REV-001 / REV-002 复现记录

日期：2026-09-11。基线：分支 `rev-001-002-measurements`，测量脚本提交 `f225555`。
环境明细见 [environment.json](environment.json)（Windows、Python 3.12.14、pydantic 2.13.4、pytest 9.0.2，源码逐文件 SHA-256 与 engine_fingerprint 已记录）。

本轮重建了原报告提到、但原始材料（probe.py、原始 JSON、候选源码）已丢失的四类局部测量。**全部使用合成输入，无真实账号、无付费模型调用。**

## 实跑命令

```powershell
.venv\Scripts\python.exe benchmarks\environment.py
.venv\Scripts\python.exe benchmarks\probe_logical_reads.py --out docs\reviews\2026-09-11\reproduction\logical-reads.json
.venv\Scripts\python.exe benchmarks\counterexample_duplicate_id.py --out docs\reviews\2026-09-11\reproduction\duplicate-id-counterexample.json
.venv\Scripts\python.exe benchmarks\probe_plan_freeze.py --out docs\reviews\2026-09-11\reproduction\plan-freeze.json
.venv\Scripts\python.exe benchmarks\kernel_benchmark.py --out docs\reviews\2026-09-11\reproduction\kernel-benchmark.json
.venv\Scripts\python.exe -m pytest tests\test_benchmarks.py -q
```

## 重建结果

| 测量 | 本轮观测 | 与历史报告的关系 |
|---|---|---|
| 单次 run 输入读取 | `Runtime._read_sources` 共 7 次完整遍历，700 个文件、251,020 字节 | 与历史"7 次 / 700 次 / 251,020 字节"一致 |
| `artifact_read` 读 1 字符 | 5 次 `read_bounded`、84,554 字节（其中 4 次是 `task_inspect` 全量核验，1 次是目标文件全读） | 与历史"5 次 / 84,554 字节"一致 |
| `task_inspect` 单独调用 | 4 次读取、43,551 字节 | 新增拆分，历史未单列 |
| 跨文件重复 ID | 单遍执行：10.00 CNY + 1 个 DUPLICATE_ID；分文件汇总再相加：30.00 CNY 且异常丢失 | 与历史反例一致 |
| 深层冻结 | `plan.nodes` 可 append，`plan_hash` 随之变化；`model_validate_json` 与 `_preflight` 均拒绝 | 与历史观察一致；是设计气味而非已证实越权 |
| 内核等价 | 62 例语料（含前导零、占位 ID、文件排序、单行超 int64 分、累计超 int64、行预算、坏表头、坏 UTF-8、BOM），lazy_groups 与 int_cents 对参考实现零差异 | 历史称 62 组一致，本轮重建语料为 62 例 |
| 内核计时（本机，20,000 有效行 / 200 文件 / 7 轮 / 种子 7） | 中位数：reference 59.43ms、lazy 57.15ms、int_cents 47.20ms | 历史 59.89/55.61/39.22ms 为另一环境，不作阈值；lazy 在本机无显著收益，int_cents 本机约 -20.6%，需消融与端到端证据后才能定性 |

原始样本见 [kernel-benchmark.json](kernel-benchmark.json)（每核每轮毫秒值、预热方式、随机顺序种子）。

## REV-005 采纳记录（同分支后续提交）

依据上述 62 例零差异与本机计时，`src/agentos_runtime/tabular.py` 的 `aggregate` 已切换为延迟分组 + 整数分实现；原 Decimal 实现原样保留在 `benchmarks/kernels.py::reference_decimal`，作为差分回归 oracle。采纳后复测：62 例零差异；本机中位数 adopted 45.17ms / reference 61.25ms / lazy-decimal 59.19ms（[kernel-adoption-rev005.json](kernel-adoption-rev005.json)），内核级约 -26%，仅本机探索性数字，不构成端到端或模型侧提效。lazy 单独版本无收益，未采纳。tabular.py 属 engine_fingerprint 组成，旧工作区回执按既有 ENGINE_CHANGED 规则失效。

## 明确不做的事

- 全部是**逻辑读取**（受信读取原语调用计数），不是物理磁盘 I/O。
- 本机计时只覆盖计算内核，不能推出运行时、端到端或模型侧提效。
- 未做冷/热缓存对照、置信区间、CPU 隔离或跨机器复测。
- 原 probe.py / 原始 JSON / 候选源码仍缺失，未伪造；历史报告原文仍以字节级保存于 evidence/。
- `plan_hash` 变化后重校验拒绝说明现有防线有效，不是漏洞利用证明。

## 测试证据

`pytest tests/test_benchmarks.py`：8 项通过。同一环境完整套件 `pytest -q --basetemp=.local\tmp\pytest`：189 通过、5 跳过（既有 Windows 链接/权限用例）。沙箱外 `Temp\pytest-of-*` 在本会话被拒，故使用工作区内 basetemp；CI 环境不受影响。

## REV-004 会话读取证据（同分支后续提交）

`logical-reads.json` 已按新接口重测：`artifact_open` 只核验目标产物（1 次读取 / 41,003 字节），三次 `artifact_session_read` 加 `artifact_session_close` 全程 0 次文件读取；对照旧 `artifact_read` 单字符路径仍为 5 次 / 84,554 字节。`task_inspect` 全量核验语义未变。

## 下一步可执行任务

REV-002 已具备基础设施，仍需：物理 I/O 对照（可选）、更多轮次与冷/热条件、把等价语料接入未来任何内核变更的回归门槛。随后按依赖序推进 REV-003/004/005/007 的小切片；int_cents 本机有收益迹象，REV-005 的"是否采纳"仍以差分 + 消融证据为准。
