# 下一开发会话交接（云端优先，不要求用户本地编码）

当前代码 v0.0.2，166 项测试通过。先读 STATUS.md、reports/IMPLEMENTATION_R2.md、AGENTS.md、docs/adr/0006-explicit-recovery-and-agent-gateway.md，再复跑测试。不要重问已知项目目标，也不要让非技术用户配置环境。

## 已有代码

- runtime.py：固定四阶段；显式 resume；已完成阶段复用，输入/计划/oracle/执行器绑定。
- journal.py：SQLite v2 状态/事件事务、checkpoint、publication prepared，run.json 仅派生缓存。
- locking.py：进程锁；POSIX 已测，Windows 未测；不通过删锁文件解除阻塞。
- gateway.py：八个工具、所有者注册合成输入、request_id 去重、取消、产物引用与事件分页。
- diagnostics.py：基于允许列表的无内容诊断。
- CLI：demo/run/baseline/schema 保留，增加 resume/init-demo/tools/tool/diagnose。

## 先做什么

1. 复跑 `PYTHONPATH=src python -m pytest -q -W error::ResourceWarning`，核对打包证据。不要假设环境能持续保存，优先解压最近交付包，不要退回 v0.0.1。
2. 优先取得可用的官方 MCP SDK（核对当前主版本并固定依赖），对 gateway 做薄适配，不重写任务执行。真实 stdio client/server 初始化、tools/list、调用、错误、关闭和重连均要测试。当前网络不可下载，未安装 SDK，不能把 JSON CLI 称 MCP。
3. 浏览器沙箱在本轮环境启动失败，保持门槛，不用关闭 sandbox 换取“通过”。可在有支持的执行环境再做本地模拟网页试验，不能接私人 Cookie 或外部发送。
4. 接一个真实 Agent 客户端时保留其会话、Skills、上下文、模型状态；显式配置预算和授权。没有真实模型调用就标未测，不能用脚本客户端测试冒充 Agent 能力回归。
5. 后续的界面/安装/实机验收版要让用户只需启动样例、看结果和导出诊断。当前不要要求用户运行开发命令。

## 已知限制与踩坑

- v0.0.1 日志缺指纹，拒绝自动迁移；保留原交付包。
- 正在写入的 SQLite 不可用“普通不可变文件内容哈希/mtime”检查；会误报并发修改。只作类型/大小/路径检查，一致性由事务保证。初始化 DDL 也要原子。
- `with sqlite3.connect(...)` 只管事务，不负责 close。使用 contextlib.closing 或 finally。
- 恢复只补安全的缺失本地副本；截断/不同文件保留并阻断，不删除后重来。
- 已核验产物存在不等于已获准执行新动作；每动作读当前策略/取消。
- 每 attempt 超时是协作式，初始+最多三次恢复。elapsed 不包含丢失的崩溃时间，不可用作完整性能比较。
- request_id 相同但参数不同必须拒绝，不能静默创建；ok=true 工具响应也可能包含 FAILED 任务。
- 只单所有者 home；不透明编号不是多租户授权，不承诺恶意主机保护。
- 核心业务仍只有合成固定四阶段。GOV-006 和真实 A/B/C 未决，不扩大为通用 OS。

## 交付要求

记录实际命令、JUnit、失败/修复过程、环境阻塞、未测项、源码压缩包及哈希。每轮完成当前任务，不承诺离线后台自动工作，不需要用户启动另一个本地聊天。
