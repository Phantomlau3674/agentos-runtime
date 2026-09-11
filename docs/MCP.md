# MCP stdio 传输 v0.1

状态：官方 `mcp==2.2.0` SDK 低层 `Server` 已实现并通过真实子进程 stdio 测试；仅 stdio，无网络监听。网关在 `src/agentos_runtime/mcp_server.py`，只是把 `tools/list` 与 `tools/call` 映射到既有 `AgentGateway`；全部校验、幂等、策略、journal 与锁仍在 gateway/runtime，语义与 TOOL_GATEWAY.md 一致。

## 前提

- 安装可选依赖：`pip install agentos-runtime[mcp]`（固定 `mcp==2.2.0`，v2 API，不是旧 FastMCP 示例）。
- 所有者先运行 `python -m agentos_runtime init-demo --home <dir>` 创建任务空间；MCP server 不代建 fixture，`--home` 未初始化时以 `HOME_MISSING` 退出 2。

## 启动

```bash
python -m agentos_runtime.mcp_server --home .agentos/session-a
# 或安装后：agentos-mcp --home .agentos/session-a
```

客户端配置示例（以 stdio command 方式接入）：

```json
{"command": "python", "args": ["-m", "agentos_runtime.mcp_server", "--home", ".agentos/session-a"]}
```

stdout 只承载 UTF-8 JSON-RPC 帧；启动与拒绝信息写入 stderr。

## 工具与语义

暴露的 12 个工具名称、inputSchema 与 `gateway.tools()` 完全一致：`runtime_capabilities`、`datasets_list`、`task_submit`、`task_inspect`、`task_resume`、`task_cancel`、`artifact_read`、`task_events`、`artifact_open`、`artifact_session_read`、`artifact_session_close`、`plan_explain`。没有 `init-demo`、approve 或任意执行工具。读取会话保存在 server 进程内存中，连接断开或重启后需重新 `artifact_open`。

- 每次 `tools/call` 返回一个 `TextContent`（完整网关 JSON 信封）加 `structuredContent`（同一信封对象）。`ok=false` 时 `isError=true`，信封保留 `error.code`（如 `UNKNOWN_TOOL`、`INVALID_ARGUMENT`、`IDEMPOTENCY_CONFLICT`）与 `automatic_retry:false`；不泄露异常文本或主机路径。
- `ok=true` 仅表示传输与工具执行返回有效响应；任务成败仍看 `data.status`（可能是 `FAILED`）。重试同一委托必须沿用 `request_id`；跨连接/跨进程重复提交只取回原任务（`replayed_request:true`）。
- 网关在 worker 线程执行，不阻塞并发请求。执行通道（`task_submit`/`task_resume`）与控制通道（查询、取消、事件、产物读取）使用**独立并发额度与有界排队**（`ToolLanes`：执行 2 槽+4 等待，控制 8 槽+32 等待），执行占满时控制仍可响应，超出排队上限立即返回 `QUEUE_FULL` 而非无限堆积。
- RPC 取消只停止等待（`abandon_on_cancel`），worker 线程可能继续执行；业务取消调用 `task_cancel` 持久化并在动作边界生效。断连后先检查任务状态，活跃任务不应直接恢复。正常空闲状态下的 stdin EOF 退出已由测试验证；这不代表取消会回滚已发生的效果。

## 边界

单所有者可信本地使用；不是多租户认证，也不替代主机隔离。仍属增强模式：Agent 自带的无限工具在本边界之外。无自动调度、无任务完成主动唤醒；真实客户端能力回归（AGENT_INTEGRATION.md）未由此证明。
