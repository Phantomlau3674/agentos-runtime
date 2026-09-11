# REV-020：状态机测试、单项消融与继续/停止结论

日期：2026-09-11。分支 `rev-001-002-measurements`。环境见 `docs/reviews/2026-09-11/reproduction/environment.json`。

## 状态化操作序列（已实施）

`tests/test_stateful.py`：4 个确定性种子 × 80 步随机操作流（submit/inspect/cancel/events/read/open/session_read/session_close/explain/产物篡改/非法工具）。每步断言包络完整性；篡改注入按"已定义行为"校验（`ARTIFACT_CHANGED` 而非假成功）。

本测试实际抓住并记录了的行为（非缺陷，符合安全语义）：**产物被篡改后重放 submit 会因完整性核验返回 `ARTIFACT_CHANGED`**——重放不掩盖篡改。

## 单项消融证据（每条防线都有可移除即失败的测试）

| 防线 | 消融方式（去掉它会失败的测试） |
|---|---|
| 计划校验/规范字节 | tests/test_compile.py（非规范字节 PLAN_NONCANONICAL、变异不可入已编译计划） |
| 恢复绑定 | tests/test_recovery.py（PLAN/ORACLE/ENGINE/INPUT 四类漂移阻断） |
| 产物完整性 | tests/test_gateway.py::test_changed_public_artifact_no_success_claim；test_observation.py |
| 合同收窄 | tests/test_goal_contract.py（CONTRACT_DENIED / ACCEPTANCE_MISMATCH） |
| 会话快照语义 | tests/test_artifact_sessions.py（篡改后仍服务已验证快照、过期/预算） |
| 通道隔离 | tests/test_mcp_lanes.py（执行占满时控制仍响应、QUEUE_FULL） |
| 恢复预算 | tests/test_resources.py（RECOVERY_BUDGET / WORKSPACE_BUSY / TERMINAL_RUN） |
| 内核等价 | tests/test_benchmarks.py（62 例差分，含超 int64 累计） |

## 假成功 / 正确停止 / 覆盖率

- 假成功：错误结果不能交付——`test_wrong_result_never_delivered_even_if_tools_succeed`、artifact_state 门控、verify 前置核验。
- 正确停止：FAILED/CANCELLED 终态不自动重试（TERMINAL_RUN）；不确定恢复走 needs_recovery 而非伪装成功。
- 覆盖率（本机）：229+ 测试涵盖契约、崩溃窗口、版本冲突、恢复预算、会话生命周期、状态化序列；未覆盖项显式列出（Windows 权限用例 5 项跳过、真实模型集成、物理 I/O 统计）。

## A/B/C 结论

端到端 A/B/C 实验**未运行**（需第二任务族与模型侧基线，超出本分支范围）。唯一的对比数据是内核级差分基准（REV-002/005），已在 reproduction/ 中如实标注为本机探索性数字。

## 继续/停止结论

**继续。**理由：建议起批的 13 个任务全部完成且各有测试证据；测量基础设施已就位，安全性质有消融测试支撑。但同时明确：离线合成验证的边界已到——再往前（真实 Agent 验收、浏览器/第二任务族、A/B/C 端到端）需要新的输入与预算，不是本分支内能诚实完成的任务。
