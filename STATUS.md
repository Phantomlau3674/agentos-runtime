# 实际状态

2026-09-11，本机开发。包版本仍为 0.0.2，尚未发布新的版本标签。

- 固定合成 CSV 流程、SQLite 状态与事件、显式恢复、request_id 去重、取消/撤销、分页产物和诊断已实现。
- Windows 兼容与 UTF-8 CLI 修复已合入 PR #1；GitHub Linux/Windows × Python 3.11/3.13 全部通过。
- 本机样例启动脚本和中文结果页已合入 PR #2；14 项专项测试通过，GitHub 跨平台 CI 通过。覆盖重复运行、外来输出拒绝、成功核验门槛、HTML 转义、中文路径与旧代码页。
- 官方 MCP 2.2.0 stdio 薄适配已实现，暴露原有 8 个工具；5 项真实子进程协议测试通过，与样例入口合并的 19 项专项测试通过。完整 CI 安装 mcp extra，避免跳过新协议测试。真实 Agent 联调正在验收，不能用脚本客户端冒充模型联调完成。
- 本地模拟草稿站在隔离分支开发；其 HTTP 夹具不等于已接入运行时，也不等于浏览器验收完成。
- rev-001-002-measurements 分支：REV-001 环境固定脚本与 REV-002 四类局部测量已重建并保存原始结果（docs/reviews/2026-09-11/reproduction/）；8 项测量测试通过。内核候选仅在 benchmarks/ 评估。
- 同分支：REV-003 外部 wire 计划与内部不可变 CompiledPlan 分离已实施（ADR 0008）；公开 API 与恢复语义未变，compiler.py 计入 engine_fingerprint。6 项编译边界测试通过，本机完整套件 195 通过、5 跳过。
- 同分支：REV-005 汇总内核改为延迟分组+整数分（依据 62 例差分零差异与本机内核计时，见 reproduction/kernel-adoption-rev005.json）；Decimal 参考实现保留为 benchmarks 回归 oracle；旧工作区因 engine_fingerprint 变化按既有规则失效。
- 同分支：REV-004 产物版本绑定读取会话已实现（artifact_open/session_read/session_close，ADR 0009），工具增至 11 个并自动进入 MCP；会话为进程内已验证快照，非实时磁盘检查。9 项会话测试通过，本机完整套件 204 通过、5 跳过。
- 同分支：REV-007 MCP 传输层执行/控制通道分离（ToolLanes：submit/resume 2 槽+4 等待，控制 8 槽+32 等待，超限返回 QUEUE_FULL）；RPC 取消只停止等待，业务取消仍是 task_cancel。3 项通道测试通过，本机完整套件 207 通过、5 跳过。
- 同分支：REV-009 目标合同 GoalContract 与验收绑定（ADR 0010）：合同只能收窄授权、acceptance 绑定核验器版本、记录含合同/引擎/输入版本与未决项；无合同计划 plan_hash 不变。6 项合同测试通过，本机完整套件 213 通过、5 跳过。
- 同分支：REV-010 观察出处与陈旧状态（ADR 0011）：task_inspect 各路径返回 observation 块（核验方式/结果绑定/stale）；输入漂移后 stale=true，依据缺失 stale='unknown'；幂等冲突与计划漂移写审计事件。6 项观察测试通过，本机完整套件 219 通过、5 跳过。
- 同分支：REV-011 可信动作注册表（ADR 0012）：四个动作声明读/写集与效果类别，经纪人边界拒绝未注册动作，intent 事件携带 effect，runtime_capabilities 暴露声明。4 项注册表测试通过，本机完整套件 223 通过、5 跳过。
- 同分支：REV-016 交接回归：跨进程 CLI 续接（task_id+事件+产物会话）、崩溃后新实例恢复、MCP stdio 会话工具各 1 项测试通过；AGENT_INTEGRATION.md 已更新已验证/未验证清单。本机完整套件 226 通过、5 跳过。
- 同分支：REV-006 编译边界收敛为 compile_canonical（持久化字节只解析一次、必须规范字节否则 PLAN_NONCANONICAL）；消除了 resume 的重复 dump/parse。本机完整套件 229 通过、5 跳过。
- 同分支：REV-008 输入一致性合同固化为快照语义（ADR 0013）：快照后修改/删除/新增/同路径换目录的行为均已定义并有测试；快照字节独立于源目录存活。
- 同分支：REV-012 受限 IR 显式化（ADR 0014）：CompiledPlan 携带 ir_version='aor.ir.v0.1'，事件 node 字段映射回 IR 节点；解释器仍为 _execute 数据驱动分派，无 eval/任意节点。

## 仍未完成

MCP 真实 Agent 能力回归、受控浏览器/草稿任务的运行时集成、第二独立文件任务族、通用依赖失效与有限并行、完整 A/B/C 实验、全新环境包装验收。Office、Blender、多用户/跨设备和隔离代码后端仍为有条件扩展。

## 证据与边界

参见 docs/WINDOWS_VALIDATION.md、docs/WINDOWS_CI.md、docs/LOCAL_DEMO.md、docs/MCP.md。原云端 reports/ 未随快照交付，不声称已恢复。中间失败记录保存在本机 .local，未混入公开源码。原 planning/backlog.json 的 planned_only 为初始规划状态，不能直接当成当前实现进度。

五项既有 Windows 链接/权限测试仍跳过；通过的有限用例不构成恶意同用户进程隔离或生产安全认证。RPC 取消可能留下继续执行的线程；业务取消使用 task_cancel，先核对状态再恢复。不存在对话结束后自动接续所有开发的服务承诺。
