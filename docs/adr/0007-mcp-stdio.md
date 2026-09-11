# ADR 0007 — 官方 MCP stdio 瘦适配层

日期：2026-09-11。状态：已在工作树实施并通过真实子进程 stdio 测试（tests/test_mcp.py）。

## 决策

新增 `agentos_runtime.mcp_server`：固定 `mcp==2.2.0`（PyPI 当前稳定，v2 API）的低层 `mcp.server.Server`，以 `on_list_tools`/`on_call_tool` 构造参数注册处理器，经 `mcp.server.stdio.stdio_server` 提供唯一传输。入口 `python -m agentos_runtime.mcp_server --home PATH` 与可选 `agentos-mcp` script；工厂 `create_server(home)`。

### 映射

- `tools/list` 直接转 `gateway.tools()` 的 8 项（名称、描述、inputSchema 逐字相同，保留 `additionalProperties:false` 等有界约束）。
- `tools/call` 把 `{name, arguments}` 交给 `gateway.call`，完整信封 `{ok, data|error}` 同时放入 `TextContent.text`（JSON 字符串）与 `structuredContent`。`ok=false` → `isError=true`，错误码原样保留；不声明 outputSchema，客户端无结构化校验负担。未知工具不另走协议错误，统一走信封（`UNKNOWN_TOOL`），与 CLI `tool` 子命令语义完全一致。

### 并发与取消

网关调用经 `anyio.to_thread.run_sync(..., abandon_on_cancel=True)` 进 worker 线程，同步执行（含 `task_submit` 全链）不阻塞 JSON-RPC 循环。RPC 取消会停止等待，线程可能继续执行；业务取消须调用 `task_cancel`。断连后先用 `task_inspect` 核对活跃执行或终态，再决定是否显式 `task_resume`。RPC 取消本身不表示任务已中止或效果已回滚。

### 边界与启动

`AgentGateway(home)` 在 serve 前完成 home 校验；未初始化以 `HOME_MISSING` 退出 2，绝不代建 fixture。stdout 仅 UTF-8 JSON-RPC（SDK 在 Windows 下重绑定标准句柄），诊断全部走 stderr。无 listener、无 approve/exec 工具、无模型调用。Owner 初始化仍只属于 CLI。

## 不承诺

不声称多租户认证、网络传输、任务完成唤醒、恶意主机隔离或模型能力保留；stderr 诊断文本不属于协议契约。

## 证据

`tests/test_mcp.py` 5 例（真实 SDK v2 客户端 + 子进程：initialize、8 工具 schema 逐字比对、submit/inspect/artifact_read、重连幂等、未知工具/非法参数、stdin EOF 退出、未初始化 home 拒绝）；全套 166 passed / 5 skipped（含既有用例不变）。

## 上游核对（2026-09-11）

- mcp 2.2.0 dist-info METADATA 与本 venv 源码（`mcp/server/lowlevel/server.py`、`mcp/server/stdio.py`、`mcp/client/session.py`、`mcp_types`）。
- 官方文档：https://py.sdk.modelcontextprotocol.io/
