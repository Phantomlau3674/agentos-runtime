# ADR 0011：观察出处、显式陈旧状态与冲突审计

状态：已实施（REV-010）。对应设计 docs/reviews/2026-09-11/03_CODE_AND_COMPILATION.md 观察与状态一节。

## 决定

- `task_inspect` 所有返回路径带 `observation` 块：`artifact_check`（`full_revalidation_at_this_call` / `not_performed`）、`result_binding`（历史结果绑定记录的输入版本 / 无记录 / 未创建）、`stale`。
- `stale`：SUCCEEDED 任务重算绑定数据集的当前输入哈希，与快照回执比对——输入已变为 `true`，依据不可用为 `'unknown'`，非成功状态为 `'not_applicable'`。SUCCEEDED 是历史结果，输入漂移必须显式可见。
- 冲突与撤销进入审计事件：幂等冲突写 `audit.idempotent_conflict` 到原任务 journal；计划版本漂移写 `audit.plan_changed` 再抛 `PLAN_CHANGED`；`task_cancel` 原有 `cancel.requested` 事件不变。
- 审计是尽力而为：RESERVED 任务尚无 journal 时不产生事件（命名空间不存在，无处可记）。

## 理由与边界

不确定的恢复不伪装成功（RUNNING/INTERRUPTED + needs_recovery 语义不变）；已交付产物不默认信任（inspect 仍全量核验）；观察的"何时核验、绑定何版本、是否仍新鲜"对调用方可见。`stale` 只比较输入哈希，不比较输出——产物本身的篡改已由 `full_revalidation_at_this_call` 覆盖。
