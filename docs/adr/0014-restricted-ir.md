# ADR 0014：受限 IR 与参考解释器

状态：已实施（REV-012；IR 由 REV-003 的 CompiledPlan 落地，本 ADR 补齐显式版本与语义说明）。

## 决定

`CompiledPlan` 即受限 IR：`ir_version='aor.ir.v0.1'`、`schema_version`、规范化字节、`plan_hash`、节点为 `tuple[CompiledNode]`（id + operation + depends_on 元组）。

- 值域：operation 限定在 OPERATIONS 四个字面量；limits 有上下界；节点数恰为 4；depends_on 必须是前驱链。
- 引用：节点间只用 id 引用，不携带宿主路径或可执行内容。
- 参考解释器：`Runtime._execute` 是数据驱动的分派——对每个已编译节点按其 operation 查动作注册表（ADR 0012）再执行；没有 eval、没有任意节点、不能装载新动作。
- 事件映射：operation_intent/completed/audit 事件的 `node` 字段指回 IR 节点 id，审计轨迹与 IR 结构一一对应。
- 版本失效：IR/解释器/核验器任一变化由 `engine_fingerprint` 使旧回执失效；计划结构变化由 `plan_hash`/`PLAN_NONCANONICAL`/`PLAN_CHANGED` 门禁。

## 边界

当前 IR 只有线性四阶段链；通用 DAG/循环/条件分支不是本版目标（RESEARCH 里列为后续）。CompiledPlan 不是沙箱——宿主进程内恶意代码仍在其防护边界之外。
