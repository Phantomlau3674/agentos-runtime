# 首轮编码：从可验证的最小闭环开始

本文件是下一阶段的执行指令，**不是声称以下代码已经存在**。初稿编写时仓库只有策划；当前窄切片进度以 ../STATUS.md 为准。无需非技术发起人替我们决定框架、数据库或函数名。

## 先后顺序

### 切片 0：工程与合成测试基础

对应 GOV-003、GOV-004、BEN-001、BEN-002。

建立最小 Python 工程、锁定依赖、基本测试配置、合成 CSV 生成器与独立 oracle，定义 RunRecord。首先不接模型、不接个人账号、不安装原生桌面驱动。

完成证明：空环境跑出合成数据和独立预期结果；非法行/币种边界用例正确；源码与日志中没有私密数据。只能称“测试基础完成”，不能称 Agent OS 能执行任务。

### 切片 1：A/B 基线与复用选择

对应 GOV-005、BEN-003、BEN-004、GOV-006。

用现有工具写受审查的离线参考流程与批处理基线，选一个浏览器方案，核对上游许可和版本。连接实际模型需要显式配置预算；没有调用就把 Token/模型往返记为 missing，不从模拟延迟推出真实提效。

完成证明：B 能处理这批任务，缺口清楚；保留“现成方案已足够”的退出选项。若无法做模型实测，可以完成离线工程验证，但 go/no-go 仍为未决，不能以假数据放行平台投入。

### 切片 2：动作契约与默认拒绝

对应 API-001～API-005、SEC-001、SEC-002、ADP-001。

只实现有限 TaskSpec/ActionSpec、效果注册、预算校验、状态模型与 mock 适配器。先写越权、循环、未知能力和超大参数测试，再接执行。

完成证明：有效计划可解析，非法计划在任何效果发生前被拒绝；模型不能在参数中自行授权。

### 切片 3：状态、产物与第一条执行路径

对应 DAT-001～DAT-003、ADP-002、ADP-003、EXE-001、EXE-002、EXE-005。

实现串行执行、operation intent、只读输入快照、项目输出副本、CSV 批处理与独立验收。所有受控动作走同一 broker。

完成证明：一条确定计划从合成输入到 summary/errors/verification 产物，源文件 hash 不变；结果不符时任务失败，不需要模型来“宣布完成”。

### 切片 4：一次真实中断恢复

从 REC-001、REC-002 开始，并按依赖补齐所需状态/取消基础。

实际终止进程，重启后检查 staging、journal 和输入版本。只有文件副本路径正确恢复后，才进入 mock 外部写/未知效果/并行。不能一开始就宣称全任务恢复或任意软件回滚。

## 未来代码目录建议

以下仅是待建立结构，不是已有文件链接：

```text
src/agentos_runtime/
  contracts/       # versioned types and validation
  policy/          # broker and scope rules
  state/           # SQLite journal and migrations
  artifacts/       # immutable blobs and manifests
  execution/       # bounded executor and recovery
  adapters/        # trusted mock/files/tabular/browser
  interfaces/      # CLI and MCP facade
  verification/    # independent output checks

tests/
  unit/
  contracts/
  integration/
  failure_injection/
  security/

benchmarks/
  fixtures/
  baselines/
  runners/
```

暂不创建大前端、Docker 集群、图数据库、万能插件接口或任意代码 sandbox。每个模块只有被一个验收场景需要时才实现。

## 每次提交的交接格式

写清任务 ID、行为变化、实际测试命令和结果、未测试环境、已知风险、下一条可执行任务。没有实际运行的命令不得出现在“测试已通过”列表里。

## 用户需要承担的部分

目前只有创建/授权 GitHub 远端这一账号动作无法由当前接口完成。后续需要接个人电脑或付费服务时，再由使用者决定是否授予明确范围；其他技术拆解与代码工作不要求用户理解。
