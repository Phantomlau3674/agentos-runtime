# 动作与任务契约

协议草案：`aor.task.v0`。本文件描述待实现接口，不是现有 API 文档。

## TaskSpec

| 字段 | 含义与限制 |
|---|---|
| schema_version | 精确协议版本；不认识的版本拒绝，不猜测兼容 |
| task_id / plan_revision | 服务端分配任务 ID，计划不可变；修订保留前版 |
| goal / acceptance | 用户目标及注册验收器列表；自由文本不能替代验收器 |
| inputs | 服务端认可的输入清单、版本/哈希、数据分级 |
| nodes | 有向无环图；节点数、扇出、参数大小有上限 |
| requested_capabilities | 请求范围，不是最终授权 |
| budget | 时限、内存/进程上限、产物大小、最多模型调用等 |
| failure_policy | 默认停止受影响下游，保留其他已核验结果 |
| output_policy | 只写新副本，禁止覆盖原稿 |

权限取交集：系统策略 ∩ 所有者授权 ∩ 项目权限 ∩ 任务范围 ∩ 适配器许可。模型在计划里填写 `allow` 不具有授权作用。

## ActionSpec

每个节点含 `id`、`operation`、`adapter_version`、`depends_on`、`arguments`、`preconditions`、`expected_outputs`、`timeout`、`retry_policy` 和 `resource_keys`。

参数支持三种来源：字面量、导入产物句柄、前序节点声明的输出句柄。不允许任意模板执行、对象反射、宿主路径注入或未经声明的全局状态。

效果分类由受信注册表提供，不由模型决定：

| 效果 | v0 行为 | 恢复 |
|---|---|---|
| pure_compute | 可执行 | 输入版本相同可重试 |
| scoped_read | 仅授权快照/目录 | 校验版本后读取 |
| staged_write | 仅项目新产物 | 用幂等 key 和哈希对账 |
| mock_external_write | 仅本地测试草稿站 | 测试服务提供 key 查询与结果证明 |
| external_write | 默认拒绝 | 后续需服务端幂等/对账/人工决策 |
| destructive | 默认拒绝 | 不承诺通用补偿或恢复 |

批量动作必须声明最大项数、项级校验与局部失败结果，不能用“大批处理”绕过策略。任何一步的真实对象或参数扩展出已批准边界，就停止重新授权。

## 输出契约

`ActionResult` 至少含：status、operation_id、output_artifact_ids、summary、verification、error、observed_versions、timing、metrics。大的原始结果不会自动包含在 summary 中。

`verification` 含验收器 ID/版本、检查项与结果、证据产物、输入哈希。无法验证标记 unverified，不能归入成功。

错误包括稳定 `code`、是否可重试、是否存在已知/未知副作用、已保存成果、建议的人类决策。错误消息不能输出凭据、Cookie 或未授权路径内容。

## 版本与幂等

计划规范化后产生 `plan_hash`。幂等 key 由 task_id、node_id、plan_revision 与输入摘要计算；同一意图重试沿用 key，不加入 attempt_number。内容/目标发生变化是新意图，不能冒用旧 key。

“生成了幂等 key”不代表外部服务接受它。适配器必须声明是否支持按 key 查询及重复调用；不支持时保持 unknown_effect，不默认重发。

## 产物与修改

模型拿到的是不透明 artifact_id，不是可任意拼接的文件路径。每次读取都检查任务/主体权限和数据分级。物理 digest 用于一致性与去重，不充当授权凭据。导入可变文件时先快照；必须实时访问的资源用显式版本预条件。

## Agent 接口与人类接口分离

计划中的 MCP 工具：`capabilities.list`、`tasks.submit`、`tasks.status`、`tasks.resume`、`tasks.cancel`、`artifacts.inspect`。`artifacts.inspect` 分页并有字段/大小限制。

**不提供 Agent 可调用的 `tasks.approve`。** 人类控制面在独立授权渠道上处理批准/拒绝；模型最多看到 awaiting_approval 状态。批准绑定已解析参数、目标、效果、plan_hash、资源版本、主体与失效时间。

## 非目标

不发明取代 MCP 的新网络标准。MCP 是调用接口，TaskSpec 是项目内部执行契约，两者不能混为安全隔离或操作系统 ABI。参考版本见调研 S14。
