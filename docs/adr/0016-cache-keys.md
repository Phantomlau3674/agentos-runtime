# ADR 0016：编译键与结果键分离及失效规则

状态：已实施（REV-014；键本已分离，本 ADR 固化规则并补矩阵测试）。

## 键的分层

| 键 | 内容 | 失效于 |
|---|---|---|
| 编译键 `plan_hash` | 规范化计划字节 sha256（含 goal_contract） | 计划字段任何变化；非规范字节 `PLAN_NONCANONICAL` |
| 结果键 `request_hash` | dataset_id + oracle_hash + plan_hash | 同 request_id 异参数 → `IDEMPOTENCY_CONFLICT` |
| 数据版本 `oracle_hash` | 所有者 oracle（含 input_hashes、expected） | `ORACLE_CHANGED` |
| 输入绑定 `input_binding` | 输入根路径摘要 | `INPUT_BINDING_CHANGED` |
| 输入内容 | 快照回执 input_hashes | `INPUT_CHANGED` / `stale` |
| 实现版本 `engine` | engine_fingerprint（runtime/compiler/actions/storage/journal/locking/tabular/verification） | `ENGINE_CHANGED` |

## 规则

- 命中（replayed 请求/恢复回执）不改变授权链：重放只返回旧任务，不重新执行；恢复仍过全部绑定检查。
- 无关变化不重算全部：artifact_read 会话、task_inspect 的 stale 比较只重读相关对象。
- 内存释放不删恢复产物：artifact_session_close 只释放进程内快照；snapshots/outputs/journal 不受影响。
- 缓存即回执：checkpoints 以 operation_id + receipt 记账；崩溃后 reconcile 依赖 intent 存在性，未知效果不重复执行。
