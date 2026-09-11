# 2026-09-11：AgentOS Runtime 新设计与优化汇总

状态：设计提案及历史局部审阅归档，不是功能发布。

上传基线：`76d73de110436ed907fdb141e6f44d239ed137b5`。该基线已包含官方 MCP stdio 接入；不能再用旧版“只有 JSON CLI”的描述覆盖它。本轮不修改 src/、tests/、工作流、依赖或既有任务完成状态。

## 阅读顺序

| 文件 | 内容 |
|---|---|
| [01_SYSTEMS_OPTIMIZATION.md](01_SYSTEMS_OPTIMIZATION.md) | 计量、动作语义、数据通道、增量计算、反馈、调度、恢复和安全 |
| [02_SCIENTIFIC_DESIGN.md](02_SCIENTIFIC_DESIGN.md) | 未知状态、目标合同、证据、决策上下文、受限学习和可证伪实验 |
| [03_CODE_AND_COMPILATION.md](03_CODE_AND_COMPILATION.md) | 具体代码热点、不可变计划、任务 IR、编译优化和原生内核路线 |
| [04_IMPLEMENTATION_BACKLOG.md](04_IMPLEMENTATION_BACKLOG.md) | 20 项补充工作、依赖、交付与反例验收；尚未执行 |
| [05_EVIDENCE_AND_REPRODUCTION.md](05_EVIDENCE_AND_REPRODUCTION.md) | 两份报告的来源、历史测量、缺失原始材料与复现实验要求 |
| [证据清单](evidence/manifest.json) | 原报告字节数、SHA-256、Git blob SHA，以及缺失项 |
| [复现记录](reproduction/REPRODUCTION.md) | REV-001/002：测量脚本、实跑结果与边界（rev-001-002-measurements 分支） |

## 必须先分清的三件事

1. **已保存的材料**：两份原始报告全文，原样放在 evidence/ 下；使用 .md.txt 后缀避免把原文中的缺失附件引用伪装成有效链接。
2. **历史报告中的局部实验**：输入重复读取、跨文件重复 ID 反例、浅层冻结、分页读取成本、汇总内核变体。报告仍在，但原 probe.py、原始 JSON 和候选实现没有在当前附件或容器中找回。本轮没有复跑，不能称为完整、可复现的原始实验包。
3. **待实现的建议**：编译器、不可变 IR、读会话、优化后内核、控制面隔离、状态证据层等均属于提案，不因上传而完成。

## 方向

保留现有 Agent 的模型循环、Skills、上下文和重规划。运行时接收带类型、权限、版本、外部效果与验收条件的动作；在确定的区间批量执行，在条件变化或需要判断时返回 Agent。

优先减少重复读取、数据搬运、无效分配、重复计算和重跑。之后再依据端到端证据决定是否引入原生编译，而不是整体重写项目。

## 本地接管

从 [补充任务清单](04_IMPLEMENTATION_BACKLOG.md) 的 REV-001/002 开始：确认当前版本、重建并保存原始测量，再实施小型变更。每个实现 PR 单独给出参考路径、差分测试、未测项和回退方式；不要一次启用全部优化。

本轮没有完整回归、真实模型性能测试、Windows 验收或新的生产安全结论。具体边界见 [证据说明](05_EVIDENCE_AND_REPRODUCTION.md)。
