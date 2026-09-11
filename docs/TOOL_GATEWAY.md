# Agent 工具入口 v0.1

状态：传输无关网关 + CLI 已实现；**不是 MCP server，不是模型客户端**。

## 所有者准备

开发者在支持的环境中运行：

```bash
python -m agentos_runtime init-demo --home .agentos/session-a --files 100 --rows 10
python -m agentos_runtime tools --home .agentos/session-a
```

init-demo 只能通过所有者 CLI 调用，创建新目录；不作为模型工具。这里的合成数据不是任何人的实际账户或业务资料。当前仍为开发包，不要求非技术用户搭环境。

## 现成 Agent 调用

现有 Agent 通过其受授权的进程工具调用 `python -m agentos_runtime tool --home <所有者提供的目录>`，将以下单个 JSON 通过标准输入传入：

```json
{"tool":"task_submit","arguments":{"dataset_id":"demo","request_id":"report-001"}}
```

CLI 读取到 EOF 才开始，最多 65536 字节，只接受一个请求，不是 JSON-RPC/stdio MCP 连接。输出一个 JSON，成功处理的工具响应退出 0，工具拒绝退出 1，输入/本机配置错误退出 2。`ok=true` 仍要检查任务 status；同步返回 FAILED 不是成功交付。

重试同一委托必须沿用 request_id。请求成功后继续用返回的 task_id 查询，不要在每个模型回合生成新 request_id。CLI 每次退出不代表任务记录消失。

## 十二个工具

| 工具 | 作用 | 限制 |
|---|---|---|
| runtime_capabilities | 查询契约、默认计划、已实现能力 | 声明合成任务范围和模型循环在外部 |
| datasets_list | 列出已注册数据版本和数量 | 不扫描主机、不接受目录 |
| task_submit | 同步执行或返回相同请求的旧任务 | 固定四阶段链；不能自我授权 |
| task_inspect | 查询状态、核验和产物引用 | 不返回原文/主机路径；核对产物完整性 |
| task_resume | 显式继续已中断任务 | 核对绑定、政策、次数与进程锁 |
| task_cancel | 持久化取消请求 | 动作边界生效；不撤回已有结果 |
| artifact_read | 分页读取已核验产物 | 单次最多 8000 字符；编号绑定任务 |
| artifact_open | 核验目标产物版本并建立读取会话 | 只核验目标产物；快照驻留内存，进程本地 |
| artifact_session_read | 在会话内按字符偏移读取已验证快照 | 不再触碰磁盘；偏移为 Unicode 字符 |
| artifact_session_close | 关闭会话并释放快照 | 重复关闭返回 SESSION_NOT_FOUND |
| plan_explain | 编译并解释计划（IR/声明/限额/权限预判） | 纯分析零副作用；不创建任务 |
| task_events | 分页读取执行事件 | 单页最多 100 条；不包含原始行数据 |

读取会话是**版本绑定的固定快照**：打开时核验 sha256，之后磁盘变化不影响会话内容；要看新版本需重新 open。会话有过期时间（默认 600 秒）、数量与总内存上限；进程重启后旧 session_id 失效，客户端重新打开。CLI `tool` 子命令每次进程退出后会话即不存在——长会话读取请走常驻网关或 MCP server。

原会话、Skills、长期记忆、动态规划、子 Agent 不由网关接管；真实客户端保留能力的回归尚未测试。这里验证的是工具输入输出和跨进程续接，不是模拟模型推理能力。

## 等待、恢复与状态

此版提交同步运行。运行期间另一个进程可查询或取消。查询 execution_active 为 true 时不能启动另一份恢复；底层锁仍会阻断。needs_recovery 表示当前没有合作执行进程且状态允许请求恢复，不表示所有校验必然通过。

RESERVED：请求记录存在但执行命名空间尚未创建。INITIALIZING：已有合作进程正在初始化。INITIALIZATION_INCOMPLETE：无合作进程，初始化未完成，需所有者诊断，不自动重建。SUCCEEDED 是特定输入版本的历史结果，不等同于源目录今后永不变化。

当前不提供自动调度、任务完成后主动唤醒模型或跨供应商迁移原生会话状态；未来应由宿主 Agent SDK 承担，而不是用 LLM 忙轮询。

## 诊断

```bash
python -m agentos_runtime diagnose --home .agentos/session-a --task <task_id> --output diagnosis.json
```

诊断输出必须在 home 外部且为新文件；不覆盖已有文件。不导出原始输入、oracle、事件原始 payload、环境变量、主机路径或凭据。当前仅限单所有者可信本地使用，不防恶意主机进程篡改 SQLite。
