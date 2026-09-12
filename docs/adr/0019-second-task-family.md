# ADR 0019：第二个文件任务族——内容哈希去重清单

状态：已实施（ADP-006；路线图要求"复用同一动作与状态契约，不拷贝另一个独立 executor"）。

## 决定

新增 `files.dedup_manifest` 计算操作：按快照字节的内容哈希分组，产出 `dedup_report.json`（清单+重复组）与 `duplicates.csv`。

- 计划契约放宽但仍是四阶段线性管道：位置 1 固定 `inputs.snapshot`、位置 3 `artifacts.export`、位置 4 `verification.fixture`；只有位置 2 的计算操作在 `COMPUTE_OPERATIONS`（tabular.aggregate / files.dedup_manifest）中选择。
- 同一执行器、journal、回执与恢复语义：计算节点按族写各自检查点名（aggregate.json / dedup_manifest.json），崩溃窗口与 reconcile 语义不变。
- 产物集合族化：`FAMILY_ARTIFACTS` 决定 manifest 与目录白名单；`verification.json` 始终附加。
- 独立核验器分派：`run_verifier(compute_op, ...)`；dedup 校验器从 oracle 重建期望 CSV，不调用实现。验收器 id `fixture_dedup_manifest.v1`。
- oracle schema 绑定：数据集 oracle 的 `fixture_schema` 必须与计划任务族匹配，否则 `ORACLE_MISMATCH` 在任何节点执行前失败。
- 文件名规则族化：`INPUT_NAME_RULES`——tabular 仍限 `.csv`，dedup 限 `.dat/.bin/.txt`。
- `initialize_demo(..., dedup=True)` / `init-demo --with-dedup` 增加第二个合成数据集；数据集与旧 home 兼容（旧策略文件没有 dedup 授权则 `POLICY_DENIED`，失败关闭）。

## 边界

仍是合成 fixture：不处理真实文档、归档或业务数据。两个族共享输入快照/导出/核验骨架，不是通用 DAG 执行器。
