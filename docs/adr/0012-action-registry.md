# ADR 0012：可信动作注册表（读/写/效果声明）

状态：已实施（REV-011）。对应设计 docs/reviews/2026-09-11/03_CODE_AND_COMPILATION.md 可信动作一节。

## 决定

`src/agentos_runtime/actions.py` 建立 `ACTION_CONTRACTS`：每个受管动作声明 reads、writes、effect（`internal`/`published_artifact`/`attestation`）与摘要。

- `action_contract()` 是经纪人边界的一部分：未注册动作直接 `ACTION_UNREGISTERED`；`_preflight` 在 owner policy 之外逐一核对注册表。
- 每条 `operation_intent` 事件携带声明的 effect 类别，效果类型进入可审计轨迹。
- `runtime_capabilities` 向调用方暴露全部动作声明（读/写集与效果类别），可检查而非暗箱。
- `actions.py` 计入 `engine_fingerprint`，声明变化使旧回执失效。

## 理由与边界

四个动作恰好覆盖 OPERATIONS 且声明完整；声明是对运行时**允许做什么**的约束，不是对恶意宿主代码的沙箱证明（沿用 AGENTS.md 边界）。写集的物理执行仍由 runtime 的路径检查与不可变产物规则保证；声明让"哪类效果可能发生"成为可审计数据。
