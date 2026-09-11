# ADR 0015：plan_explain 与优化 pass 的适用边界

状态：已实施（REV-013）。对应设计 docs/reviews/2026-09-11/03_CODE_AND_COMPILATION.md 编译 pass 一节。

## 决定

新增 `plan_explain` 工具：编译 wire 计划为 IR，逐节点返回动作声明（reads/writes/effect）、限额、目标合同与 owner policy 预判。**纯分析，零副作用**——不创建任务、不触碰文件、不写 journal。

## 优化 pass 现状（诚实记录）

当前 IR 是固定四节点异构链：每个节点效果类别不同且都被契约要求存在。CSE 无可合并（无重复表达式），DCE 无可删除（无死节点），融合无边界可跨越（节点间横着持久化/验收边界）。因此**未实现任何优化 pass**——在结构上它们当前没有合法对象。pass 框架的进入条件、失败退出映射留待 IR 泛化（RESEARCH 中的 DAG 化）时再引入，不提前写死代码。

若未来引入：每条 pass 需独立可关闭、单独测试、未知效果不得因 fallback 重复执行——沿用编译纪律，不把 explain 当执行。

## 接口变化

工具数 11→12；`plan_explain` 加入 CLI 与 MCP（通过 `gateway.tools()` 自动暴露）。
