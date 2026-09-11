# ADR 0008：外部 wire 计划与内部不可变 CompiledPlan 分离

状态：已实施（rev-001-002-measurements 分支之后，REV-003）。对应设计 docs/reviews/2026-09-11/03_CODE_AND_COMPILATION.md 第 1 节。

## 决定

- 外部边界继续收 `PlanSpec`（Pydantic wire model），公开 API 形状不变。
- 受信入口 `compiler.compile_plan` 先对调用方对象做脱离式重校验，再产出递归不可变的 `CompiledPlan`（`tuple[CompiledNode]` + frozen `Limits` + `canonical_bytes` + `plan_hash`）。
- 规范字节与计划在冻结之后计算；不在可变模型上缓存哈希。
- `_preflight` 返回 CompiledPlan；`run` 与 `resume` 每次进入都重新编译，跨进程加载仍走完整重校验。
- `compiler.py` 计入 `engine_fingerprint`，实现变化使旧工作区回执按既有规则失效。

## 理由与边界

冻结探针（benchmarks/probe_plan_freeze.py）证实 `frozen=True` 只挡住属性赋值，`nodes` 列表仍可被追加并改变 `plan_hash`。CompiledPlan 让执行期迭代的结构在事实上不可变，但权限检查仍在执行前动态进行，不因此弱化。CompiledPlan 类型本身可被构造——防护不依赖"无法伪造类型"，而依赖公开入口只接受 wire 计划并总是重新编译。

## 未改变

计划 JSON 契约、plan_hash 内容、恢复语义、权限检查时机、`default_plan()` 与 gateway 工具签名均未变。循环/通用 DAG 仍不支持。
