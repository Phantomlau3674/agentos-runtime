# ADR 0006 — 显式文件恢复与可传输 Agent 工具边界

日期：2026-09-11。状态：已在 v0.0.2 的合成任务切片实施，非完整平台批准。

## 决策

继续保留现成 Agent 的模型、对话、Skills、观察和重规划。执行层只承接固定合成任务。本轮首先完成显式恢复和传输无关工具网关；CLI 是已测试传输，MCP 不在已实现列表中。

### 恢复单位和事实来源

SQLite schema v2 存储动作 intent、阶段 receipt、publication prepared 和任务结果。阶段完成及其事件在同一数据库事务提交；任务终态与其事件、结果也在同一事务提交。`run.json` 是派生缓存，不作为恢复事实来源。数据库事务不涵盖文件 rename；使用 prepared → rename → complete 对账。

输入与快照分别绑定内容哈希；任务绑定计划哈希、核验预期哈希、输入根标识和执行器/核验器代码指纹。任一绑定变化则拒绝旧任务恢复。成功后的 resume 会重新核验历史产物并返回相同任务，不执行新的批量动作。

恢复按阶段顺序核对已有 receipt。完整 receipt 的产物缺失/不同即阻断，不静默重写；未完成的受控副本阶段，已存在文件须逐字节匹配预期，才允许补齐缺失文件。遇到截断文件、未知文件、冲突目录或未知交付效果保留现场。没有通用“删除 staging 后重跑”机制。

### 并发与限额

工作区使用内核释放的协作式文件锁。杀进程会释放锁，锁文件不删除，避免不同 inode 造成双主。Windows 锁分支有代码但未实机测试。范围是合作 worker，不是恶意同用户进程隔离。

初始执行加最多三次显式恢复；每次执行的协作时间限制来自原计划。记录的 elapsed_seconds 仅对应当前 attempt，崩溃进程未持久化的时间不伪造。不是精确的全程硬时限或性能报告。

### 工具网关

所有者先通过 `init-demo` 注册合成数据与策略。模型只传 dataset_id、request_id、task_id、artifact_id 和有界参数，不传主机目录、核验 oracle、审批或执行代码。

请求编号唯一，绑定 dataset/核验版本/计划。注册表先记录 reservation，再启动 Runtime；重复请求只返回原任务，相同编号不同参数拒绝。reservation 后崩溃但尚未创建执行目录可显式继续；初始化不完整但已有目录不猜测修复。

每个 Runtime 动作从所有者策略和任务取消记录重新读取当前权限。取消接口只能停止后续动作，不能撤回已发生效果；不存在 Agent 自我批准接口。

`ok=true` 表示工具已返回有效响应，不表示任务成功；必须检查 `data.status` 和核验结果。任务成功前不交付暂存产物。产物引用绑定任务、文件名、内容摘要，读取前重新核验，文本按字符分页并标明是不可信数据。当前是单所有者 home 范围授权，不是多租户认证。

### 为什么不用普通文件哈希去检查数据库

并发测试发现将 `read_bounded` 用于 SQLite 活跃文件会把正常的 mtime 变化误报为输入变更。改为检查数据库路径类型/硬链接/大小，由 SQLite 事务负责一致性；不可变输入与产物仍作内容检查。初始化 DDL 使用单一事务，读取端区分正在初始化和已完成任务。

## 不承诺

不保证任意应用回滚、真实网络操作 exactly-once、硬断电后任何平台可恢复、整机沙箱、跨设备 fencing、自动后台持续运行或模型效果提升。v0.0.1 日志缺必要绑定，拒绝自动迁移；旧交付包保持原样。

## 证据

见 `tests/test_recovery.py`、`tests/test_gateway.py`、`tests/test_diagnostics.py`、`reports/r2-tests.xml` 与 `reports/r2-concurrency-stress.json`。真实模型、MCP 与 Windows 兼容不以这些测试替代。

## 上游核对（2026-09-11）

- SQLite 原子提交边界：https://www.sqlite.org/atomiccommit.html
- Python 文件操作：https://docs.python.org/3/library/os.html
- MCP 工具契约（设计参考）：https://modelcontextprotocol.io/specification/2025-11-25/server/tools
- 官方 Python SDK 主分支：https://github.com/modelcontextprotocol/python-sdk

本轮不复制上游代码。SDK 当前说明已切换 v2；没有安装 SDK，不能套用旧 FastMCP 示例后声称接入完成。下一轮应先取得可安装依赖、固定版本，再做真实协议握手。
