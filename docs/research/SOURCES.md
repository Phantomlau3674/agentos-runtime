# 来源登记

核验日期：2026-09-11。只有一手项目仓库、官方文档与论文。以下文字是研究摘要，不是复制的上游文档。未执行上游安装、测试或安全审计。

## S01 · Microsoft UFO

来源：<https://github.com/microsoft/UFO>

支持：README：Windows UIA/Win32/COM、GUI/API 混合执行、批量动作及 Galaxy DAG。51% 是上游报告，不是本项目实验。

边界：README 与指定文档；动作 schema 静态抽查，未运行。

## S01a · UFO multi-action documentation

来源：<https://github.com/microsoft/UFO/blob/364eb7969d392e857299ceaf14bd6057e5b00078/documents/docs/ufo2/core_features/multi_action.md>

支持：批量预测动作、执行时核对状态和失败降级。

边界：固定 commit 用于本次抽查，不声称是当日最新 HEAD。

## S01b · UFO action structures

来源：<https://github.com/microsoft/UFO/blob/364eb7969d392e857299ceaf14bd6057e5b00078/ufo/agents/processors/schemas/actions.py>

支持：ActionCommandInfo 与 ListActionCommandInfo 的定义；源码头标注 MIT。

边界：只抽查前 180 行。数据结构存在不证明全局事务或回滚可靠。

## S02 · AIOS

来源：<https://github.com/agiresearch/AIOS>

支持：Agent 调度、上下文、存储、工具与内核抽象。

边界：仅文档评估；不采用仓库级许可未澄清的代码。

## S02a · AIOS root LICENSE

来源：<https://github.com/agiresearch/AIOS/blob/main/LICENSE>

支持：本轮读取返回单个换行符；blob SHA 8b137891791fe96927ad78e64b0aad7bded08bdc。

边界：只证明此根文件内容不足；不推断全部历史、子目录或其他授权均不存在。

## S02b · LiteCUA paper abstract

来源：<https://arxiv.org/abs/2505.18829>

支持：把电脑能力以 MCP 方式提供给 Agent 的路线。

边界：论文摘要参考，不把旧测评分数与当前系统直接排名。

## S03 · Cua

来源：<https://github.com/trycua/cua>

支持：跨平台电脑驱动、隔离环境、SDK 与评测工具。

边界：功能按平台/应用区分；未安装验证。

## S03a · Cua driver design

来源：<https://github.com/trycua/cua/blob/main/libs/cua-driver/README.md>

支持：契约、权限模式与驱动接口。

边界：部分历史记录能力属特定平台预览；不能外推到全部操作系统。

## S04 · Rivet agentOS

来源：<https://github.com/rivet-dev/agentos>

支持：嵌入式虚拟 OS：V8/WASM、虚拟文件与进程、受控外部能力、可持续工作流。

边界：README 标注 preview/API 可变；冷启动对比不代表电脑任务端到端提效。

## S05 · OpenFang

来源：<https://github.com/RightNow-AI/openfang>

支持：自主 Agent 运行时、任务包、渠道、MCP 和权限/审计声明。

边界：README 层级信息，不把安全层数或营销性能表当作审计证明。

## S06 · BrowserOS

来源：<https://github.com/browseros-ai/BrowserOS>

支持：Agent 专用浏览器、MCP、观察与并行浏览任务。

边界：浏览器边界不等同于整台电脑；根许可与 Chromium/依赖许可分别核对。

## S07 · Vercel agent-browser

来源：<https://github.com/vercel-labs/agent-browser>

支持：原生 CLI、语义定位与 batch 模式；现成强浏览器基线候选。

边界：批量命令不自动提供业务级事务或正确性证明。

## S08 · Bytebot

来源：<https://github.com/bytebot-ai/bytebot>

支持：容器化 Linux 桌面 Agent、可视观察/接管。

边界：页面显示于 2026-03-07 归档；只作历史架构参考。

## S09 · Agent S

来源：<https://github.com/simular-ai/Agent-S>

支持：GUI 操作研究框架与跨平台桌面任务路线。

边界：区分公开代码、托管产品与不同模型的结果；未进行运行对照。

## S10 · Agno

来源：<https://github.com/agno-agi/agno>

支持：Agent 服务框架、持久状态、控制面、审批与可观测性。

边界：服务端 Agent 平台，不等于桌面应用语义层。

## S11 · LangGraph

来源：<https://github.com/langchain-ai/langgraph>

支持：有状态 Agent 编排与持久化基础。

边界：可复用上层编排；不据此推断外部动作具备原子性。

## S11a · LangGraph persistence

来源：<https://docs.langchain.com/oss/python/langgraph/persistence>

支持：Checkpointer 与 Store 区别；内存 checkpointer 重启不保留。

边界：当前 durable-execution 链接重定向至此页；实现时应核对具体 checkpointer 版本。

## S12 · Cloudflare Code Mode

来源：<https://blog.cloudflare.com/code-mode/>

支持：将工具组合放在代码执行中，让中间数据不反复经过模型。

边界：2025-09-26 的架构文章，不当作 2026 年产品定价/可用性说明。

## S13 · Playwright actionability

来源：<https://playwright.dev/docs/actionability>

支持：动作前可操作性检查与自动等待。

边界：不能替代业务结果验证。

## S14 · MCP tools specification

来源：<https://modelcontextprotocol.io/specification/2025-11-25/server/tools>

支持：工具结构、结构化结果与调用约束的版本化参考。

边界：固定 2025-11-25 版本作设计参考；SDK 实现时重新确认兼容版本。

## S15 · MIT license text

来源：<https://spdx.org/licenses/MIT.html>

支持：本项目原创材料采用的许可文本。

边界：不改变第三方依赖许可。

## 证据分级

- **D**：读取 README 或文档，确认项目声明了该能力，不代表独立验证实现效果。
- **C**：有限源码抽查，本轮仅用于 UFO 动作结构，不能外推整仓库安全性。
- **R**：实际执行并留存环境和日志；本轮没有任何上游或本项目 R 级证据。

除明确固定的 UFO commit 和 AIOS LICENSE blob，其他链接可能随上游更新。正式采用依赖前需固定 commit/release 并记录许可文件哈希。本轮没有按 Stars、下载量或未经核验的 X 热度排序。
