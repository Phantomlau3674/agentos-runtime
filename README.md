# AgentOS Runtime

**A bounded execution layer for existing agents — cloud development snapshot v0.0.2.**

让原 Agent 保留观察、判断、会话和 Skills，把确定执行交给可核验、可恢复的本地运行时。当前为合成任务技术切片，不是完整操作系统或成熟产品。

## 本版新增

**中断对账 → 复用已核验阶段 → 继续未完成工作。**

提供八个 Agent 工具的 JSON CLI 入口，包括持久任务编号、重复提交去重、显式恢复、取消、事件分页和不透明产物读取。诊断导出不包含源数据、主机路径或环境凭据。仍不接真实模型、MCP、浏览器账号、Office 或 Blender。

[实际状态](STATUS.md) · [本轮报告](reports/IMPLEMENTATION_R2.md) · [工具契约](docs/TOOL_GATEWAY.md) · [恢复决策](docs/adr/0006-explicit-recovery-and-agent-gateway.md)

## 开发方式

云端优先：在当前可执行环境里实现、测试、修复、保存证据，然后交付用户实机验收。普通使用者不承担框架选择、源码修改和日常调试。本包仍是开发快照，不是 Windows 一键安装版。旧本地会话启动器作为可选开发入口保留，非必做步骤。

## 开发者运行

当前只实测 Linux + Python 3.13.5。以下需要已安装 pyproject.toml 所列依赖；全新环境下载依赖尚未验收，不能把预装环境测试当干净安装成功。

```bash
PYTHONPATH=src python -m pytest -q
PYTHONPATH=src python -m agentos_runtime init-demo --home .agentos/demo-a --files 100 --rows 10
PYTHONPATH=src python -m agentos_runtime tools --home .agentos/demo-a
```

向 `python -m agentos_runtime tool --home .agentos/demo-a` 的标准输入提交单个 JSON 并关闭输入：

```json
{"tool":"task_submit","arguments":{"dataset_id":"demo","request_id":"demo-001"}}
```

这是 JSON CLI，不是 MCP stdio 协议。重复请求沿用 request_id，不会新建第二份任务；接入现成 Agent 时保持其原有会话。详见工具文档。

原离线命令仍可使用：

```bash
python -m agentos_runtime demo --workspace .agentos/offline-a --files 100 --rows 10
python -m agentos_runtime resume --fixture .agentos/offline-a/fixture --workspace .agentos/offline-a/run
python -m agentos_runtime baseline --fixture .agentos/offline-a/fixture --output .agentos/reference-a
```

resume 只对符合条件的本版任务核对/恢复；旧版、失败、取消、版本变化、损坏和不明副作用不盲目重放。离线参考执行不是实测 Agent 强基线。

## 范围与证据

166 项测试通过；包含原有 71 项、真实杀进程、并发提交、跨进程工具往返和诊断负例。新增并发压力检查 20 组 / 100 个请求，每组只创建一个任务。完整证据保存在 reports/，不能据此宣传模型提效倍率或生产级安全。

固定计划 `aor.fixture-plan.v0.1` 不变；run record 升至 v0.2，SQLite schema 升至 v2。通用 `aor.task.v0`、动态 DAG、MCP、真实客户端能力保留、Windows 与浏览器仍需验收。

## 项目文档

[立项](PROJECT_PLAN.zh-CN.md) · [同类项目](docs/research/LANDSCAPE.md) · [任务清单](planning/BACKLOG.md) · [Agent 能力保留](docs/AGENT_INTEGRATION.md) · [开发交接](LOCAL_SESSION_START.md)

## 安全与许可

只使用合成数据，不连接私人账号，不调用付费模型，不执行任意模型生成代码。所有者配置与模型计划分离，不暴露自我批准工具。当前仅保护通过本运行时执行的受控动作，不约束原 Agent 的外部 Shell。

原创代码与文档使用 [MIT](LICENSE)；没有复制未确认许可的上游代码。公开仓库：`https://github.com/Phantomlau3674/agentos-runtime`。当前远端发布的是经过 166 项测试复核的 v0.0.2 可恢复快照；原有依赖版本快照不等于跨平台带哈希锁文件。
