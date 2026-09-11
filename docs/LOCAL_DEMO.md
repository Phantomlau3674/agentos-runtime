# AgentOS 离线合成数据演示指南 (Windows 本地所有者试用)

本指南对应任务 **OPS-001 / INT-004** 狭窄切片：让 Windows 非技术所有者能够便捷启动现有的合成 CSV 批处理演示，并在本地直接查看包含任务状态、聚合汇总、校验异常和防篡改核验的自包含 HTML 报告。

---

## 1. 运行声明与安全边界

- **纯本地离线运行**：演示全程在本地受控环境中运行，**未调用任何在线大语言模型 (No Live LLM)**，亦不发起任何外部网络请求。
- **合成测试数据**：所有输入数据均为确定性算法生成的合成 CSV 文件（100 个文件，共 1000 行），不含任何真实个人、账户或企业商业记录。
- **确定性契约核验**：执行前后自动对比 Oracle 标准答案与文件 SHA-256 哈希，核验证据链完整性。
- **非 MCP 服务**：本演示为传输无关的本地确定性运行时，不启动后台 HTTP 服务或 stdio 常驻服务。

---

## 2. 真实前置环境要求

> **注意**：在干净环境首次部署前，请勿使用“一键全自动”等非事实宣传。请确保以下标准环境已就绪：

1. **操作系统**：Windows 10 / 11（支持 Windows PowerShell 5.1 及 PowerShell 7+）。
2. **Python 版本**：Python 3.12（或兼任 3.12+ 运行时）。
3. **项目虚拟环境**：项目根目录下存在已安装依赖的 `.venv`。

若尚未创建项目虚拟环境，请由技术人员在项目根目录下执行以下标准初始化命令：

```powershell
python -m venv .venv
.\.venv\Scripts\pip install -e .
```

---

## 3. 快速启动指南

### 方式一：使用 PowerShell 启动脚本（推荐）

在项目根目录下打开 PowerShell 执行：

```powershell
# 运行演示并生成 HTML 报告
.\scripts\start-demo.ps1

# 运行演示并在生成后自动在默认浏览器中打开 HTML 报告
.\scripts\start-demo.ps1 -Open
```

- **默认存储空间**：`.agentos\local-demo`
- **默认报告输出**：`.local\demo_report\index.html`

如需指定自定义路径，可使用 `-Home` 和 `-Output` 参数：

```powershell
.\scripts\start-demo.ps1 -Home .agentos\my-demo -Output .local\my-report -Open
```

### 方式二：使用 Python 模块命令行

```powershell
.\.venv\Scripts\python -m agentos_runtime.demo_app --home .agentos\local-demo --output .local\demo_report --open
```

---

## 4. 报告内容与审阅要点

生成的本地报告为完全自包含的单一 HTML 文件，无任何外部 CSS、JS 或字体 CDN 引用，双击即可安全在离线浏览器中审阅：

1. **离线声明横幅**：顶部醒目标注未调用在线模型及无网络连接状态。
2. **状态指标卡**：
   - **任务状态**：显示 `SUCCEEDED`（已成功）及全部核验项通过状态。
   - **记录统计**：直观对比总输入行数、格式合法记录行数与被拦截异常行数。
3. **不可变与防篡改核验 (Security Verification)**：
   - **Oracle Match**：与离线标准答案比对完全一致。
   - **Input Hashes**：原始输入文件哈希核验全部通过。
   - **Untouched Inputs**：执行完成后输入文件哈希未发生任何改变。
   - **Artifacts Validated**：产物完整性与尺寸约束均符合规范。
4. **币种与品类分组汇总 (Grouped Totals)**：
   - 按币种（CNY/USD/EUR/SGD）和商品类别展示数量与金额的高精度汇总结算表。
5. **异常记录明细 (Validation Errors)**：
   - 详细记录因字段格式、重复 ID 或非法金额被过滤的错误行号及原因代码。
6. **产物清单 (Artifacts)**：
   - 列出生成的 `summary.json`、`errors.json`、`summary.csv`、`verification.json` 及其 SHA-256 哈希值。

---

## 5. 安全防御与幂等性保证 (Fail-Closed)

- **安全幂等重用**：在相同的 `--home` 路径下重复运行演示，系统会自动识别已注册的任务请求，在毫秒级内复用已核验结果，绝不会向数据库注入重复或冲突的任务记录。
- **保护用户现有文件**：
  - 若指定的 `--output` 目录中已存在非 Demo 生成的普通用户文件，程序将**立即失败阻断 (Fail Closed)** 并退出（错误码 `OUTPUT_CONFLICT`），绝不覆盖、修改或删除用户文件。
  - 若指定的 `--home` 目录已存在但不是合规的 AgentOS Demo 空间，程序将立即拒绝执行（错误码 `MISMATCHED_HOME`）。
  - 若 `--home` 与 `--output` 路径相互重叠，程序将立即拦截（错误码 `OVERLAPPING_PATHS`）。
