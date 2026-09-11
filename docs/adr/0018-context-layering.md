# ADR 0018：结构化约束与可检索上下文分层

状态：已实施（REV-017）。对应设计 docs/reviews/2026-09-11/02_SCIENTIFIC_DESIGN.md 上下文分层一节。

## 分层

| 层 | 内容 | 特性 |
|---|---|---|
| 结构化约束层 | `GoalContract`（goal/invariants/allowed_operations/acceptance/unresolved/human_judgment） | 进入 canonical bytes 与 plan_hash；编译进 CompiledPlan；不可静默丢弃 |
| 可检索证据层 | journal events、checkpoints、artifacts、acceptance 块 | 按 seq 分页，出处可追 |
| 模型上下文层 | 宿主 Agent 的会话/记忆 | 运行时不接管、不代写 |

## 规则（有测试）

- 合同任何字段变化 → plan_hash 变化 → 旧计划不能恢复（PLAN_CHANGED）。禁止条件不被压缩静默删除：invariants/allowed_operations/unresolved 都是合同字节的一部分。
- 旧目标被替代 → 新合同产生新 plan_hash，旧任务凭 request_hash/PLAN_CHANGED 失效。
- 未检查项与人工判断边界写入 record.acceptance 与 verification.unchecked——不推测、不默认成立。
- 决策证据可比较的是"决策保持率"（合同约束是否原样进入执行与记录），不只是 token 数。
