# 实际状态

2026-09-11，本机开发。包版本仍为 0.0.2，尚未发布新的版本标签。

- 固定合成 CSV 流程、SQLite 状态与事件、显式恢复、request_id 去重、取消/撤销、分页产物和诊断已实现。
- Windows 兼容与 UTF-8 CLI 修复已合入 PR #1；GitHub Linux/Windows × Python 3.11/3.13 全部通过。
- 本机样例启动脚本和中文结果页已合入 PR #2；14 项专项测试通过，GitHub 跨平台 CI 通过。覆盖重复运行、外来输出拒绝、成功核验门槛、HTML 转义、中文路径与旧代码页。
- 官方 MCP 2.2.0 stdio 薄适配已实现，暴露原有 8 个工具；5 项真实子进程协议测试通过，与样例入口合并的 19 项专项测试通过。完整 CI 安装 mcp extra，避免跳过新协议测试。真实 Agent 联调正在验收，不能用脚本客户端冒充模型联调完成。
- 本地模拟草稿站在隔离分支开发；其 HTTP 夹具不等于已接入运行时，也不等于浏览器验收完成。
- rev-001-002-measurements 分支：REV-001 环境固定脚本与 REV-002 四类局部测量已重建并保存原始结果（docs/reviews/2026-09-11/reproduction/）；8 项测量测试通过。内核候选仅在 benchmarks/ 评估。
- 同分支：REV-003 外部 wire 计划与内部不可变 CompiledPlan 分离已实施（ADR 0008）；公开 API 与恢复语义未变，compiler.py 计入 engine_fingerprint。6 项编译边界测试通过，本机完整套件 195 通过、5 跳过。

## 仍未完成

MCP 真实 Agent 能力回归、受控浏览器/草稿任务的运行时集成、第二独立文件任务族、通用依赖失效与有限并行、完整 A/B/C 实验、全新环境包装验收。Office、Blender、多用户/跨设备和隔离代码后端仍为有条件扩展。

## 证据与边界

参见 docs/WINDOWS_VALIDATION.md、docs/WINDOWS_CI.md、docs/LOCAL_DEMO.md、docs/MCP.md。原云端 reports/ 未随快照交付，不声称已恢复。中间失败记录保存在本机 .local，未混入公开源码。原 planning/backlog.json 的 planned_only 为初始规划状态，不能直接当成当前实现进度。

五项既有 Windows 链接/权限测试仍跳过；通过的有限用例不构成恶意同用户进程隔离或生产安全认证。RPC 取消可能留下继续执行的线程；业务取消使用 task_cancel，先核对状态再恢复。不存在对话结束后自动接续所有开发的服务承诺。
