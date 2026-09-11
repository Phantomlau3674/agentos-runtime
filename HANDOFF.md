# 本地接管说明

日期：2026-09-11。公开仓库：`https://github.com/Phantomlau3674/agentos-runtime`。

## 你现在接管的版本

这是当前能够完整恢复并重新验证的 **v0.0.2** 源码快照。本次交接前在 Linux / Python 3.13.5 重新运行：

```text
166 passed in 13.35s
```

本地历史的最后一个可核验提交是 `2bf2a4dc9b7f241d128c309f674dd19291cdcda7`。GitHub 远端由空仓库重新发布，因此远端提交 SHA 不会与这个本地 SHA 相同；源码内容以本次快照为准。

## 已实现

- 固定合成 CSV 任务的受控执行与独立验证。
- 任务状态、事件和产物持久化。
- 中断对账与显式恢复；未知副作用阻断。
- request_id 去重与并发提交防重复。
- 8 个传输无关 Agent 工具及 JSON CLI。
- 取消、策略撤销、产物分页读取和脱敏诊断。
- 166 项自动测试。

## 尚未作为本次源码交付完成

- 官方 MCP 传输层。
- 真实 Codex / Claude Agent 端到端能力回归。
- Windows 实机一键安装与原生软件适配。
- Office、Blender、真实浏览器账号流程。
- 完整 A/B/C 效率实验和模型 Token / 成本结论。

之前云端曾继续探索 MCP、工作台和浏览器流程，但没有形成一个能够完整恢复、重新核验并安全合并到此仓库的源码快照。本次交接不把这些实验性状态伪装成已交付代码。

## 本地开始

```bash
git clone https://github.com/Phantomlau3674/agentos-runtime.git
cd agentos-runtime
python -m venv .venv
```

Windows PowerShell：

```powershell
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
pytest -q
```

macOS / Linux：

```bash
source .venv/bin/activate
pip install -e '.[dev]'
pytest -q
```

全新 Windows 环境的依赖安装与行为仍属于实机验收，不应因为云端 Linux 测试通过而视为已验证。

## 推荐接管顺序

1. 先让 `pytest -q` 在你的 Windows 机器通过，并记录失败项。
2. 跑 `python -m agentos_runtime init-demo --home .agentos/demo-a --files 100 --rows 10`。
3. 跑 JSON CLI 的 `task_submit` / `task_inspect` / `artifact_read`。
4. 再实现 MCP 薄传输层，不改核心执行语义。
5. MCP 通过后再接真实 Agent；最后做 Windows 原生软件适配。

架构和安全边界分别见 `docs/ARCHITECTURE.md`、`docs/AGENT_INTEGRATION.md`、`docs/SECURITY.md`、`docs/EXECUTION_AND_RECOVERY.md`。
