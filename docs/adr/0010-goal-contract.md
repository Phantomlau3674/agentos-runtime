# ADR 0010：目标合同与验收证据绑定

状态：已实施（REV-009）。对应设计 docs/reviews/2026-09-11/02_SCIENTIFIC_DESIGN.md 目标合同一节。

## 决定

`PlanSpec` 新增可选 `goal_contract`（`GoalContract`）：goal、invariants、allowed_operations、acceptance、unresolved、human_judgment，全部 tuple 字段，深度不可变。

- `canonical_bytes` 改用 `model_dump(exclude_none=True)`：无合同的计划字节与 plan_hash 不变，向后兼容。
- 合同只能收窄授权：preflight 逐节点比对 `allowed_operations` 与 owner policy，越界即 `CONTRACT_DENIED`；合同不能放宽所有者策略。
- `acceptance` 绑定核验器版本：发布前 `report['validator']` 必须等于合同声明，否则 `ACCEPTANCE_MISMATCH`，任务 FAILED、不交付。
- 成功记录新增 `acceptance` 块：合同 sha256、`engine_fingerprint`、核验器版本、输入版本摘要、未决歧义与人工判断边界。
- 核验报告新增 `unchecked`：明示未被检查的事项（持久化、语义外正确性、宿主隔离、真实模型接入）。

## 理由与边界

错误结果即使工具执行成功也不能交付（既有 verify 门槛）；模型可在计划里附带合同，但验收器名称由代码决定、oracle 由所有者提供——模型不能改 oracle 自证，合同只能约束自己。哈希匹配（fixture_input_match/source_unchanged）与业务正确性（summary_exact 等）分列；未检查项显式列出而非默认成立。

## 未改变

无合同任务的行为、plan_hash、恢复语义与工具签名不变。合同字段为声明式约束，invariants/unresolved 目前记录而非逐项机器检查。
