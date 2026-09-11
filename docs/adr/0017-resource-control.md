# ADR 0017：资源键、冲突控制与预算传递

状态：已实施（REV-015；机制已存在于 workspace_lock/ToolLanes/limits，本 ADR 固化并补测试）。

## 资源键与冲突矩阵

| 资源键 | 冲突域 | 机制 |
|---|---|---|
| task workspace | 同一任务命名空间 | `workspace_lock` 字节范围锁，第二执行者 `WORKSPACE_BUSY` |
| dataset | 多任务并发 | 不互斥——各自独立工作区与快照，允许并行 |
| MCP 通道 | 进程级并发 | `ToolLanes`：执行 2 槽+4 排队、控制 8 槽+32 排队，溢出 `QUEUE_FULL` |

## 预算传递

- 单次尝试时长 `limits.max_seconds` 由计划传入 `_execute` 的 `check_budget`，贯穿每个动作边界。
- 恢复次数由 `journal.begin_resume` 的 `MAX_ATTEMPTS=4` 计数，超限 `RECOVERY_BUDGET`，保留结果待人工检查。
- 错误统一 `automatic_retry:false`：Agent、运行时、适配器之间不存在重试倍增；取消只打标记，不伪装外部回滚。

## 边界

资源声明粒度当前到"任务工作区"级；同文档/同会话的 finer 键留待浏览器/文档类适配器出现（RESEARCH 范围）。饱和表现：锁忙→WORKSPACE_BUSY、通道满→QUEUE_FULL、尝试耗尽→RECOVERY_BUDGET，全部显式可解释。
