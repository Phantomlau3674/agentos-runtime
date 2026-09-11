# ADR 0009：产物读取会话与元数据/核验分离

状态：已实施（REV-004）。对应设计 docs/reviews/2026-09-11/03_CODE_AND_COMPILATION.md 第 2 节。

## 决定

新增三个工具：`artifact_open`（核验指定产物内容版本并建立读取会话）、`artifact_session_read`（在会话内按 Unicode 字符偏移读取快照）、`artifact_session_close`（关闭并释放内存）。原 `artifact_read` 一次性读取接口保留不变。

- `task_inspect` 语义不变：成功任务仍做全部产物完整性核验——这是既有安全测试钉死的属性，不拆。
- 会话是进程本地能力：保存打开时已验证的 UTF-8 文本快照、sha256、所属任务。分页读取不再触碰磁盘。
- 会话语义是**固定已验证快照**，不是实时磁盘检查；要看变化后的版本需重新 open。
- 有界：16 个会话、总计 32MiB 快照、600 秒过期；超限返回 SESSION_BUDGET，过期/未知/关闭后返回 SESSION_EXPIRED / SESSION_NOT_FOUND。
- CLI `tool` 单次进程退出即丢会话；MCP/常驻网关进程内有效。无会话持久化，断线后重新打开，不宣称恢复旧会话。

## 理由与边界

插桩证据（docs/reviews/2026-09-11/reproduction/logical-reads.json）：旧路径每读 1 字符触发 5 次逻辑读取、84,554 字节（task_inspect 全量核验 + 目标全读）。会话路径：open 1 次目标读取，之后每次分页 0 次文件读取。权限绑定不变：会话建立在任务已核验交付之后，产物编号仍绑定 task_id。大文件分块校验与索引按设计留作后续评估，不在本切片。
