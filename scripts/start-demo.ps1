<#
.SYNOPSIS
    AgentOS 离线合成数据演示启动脚本 (Windows PowerShell).

.DESCRIPTION
    面向所有者的演示启动器。优先选择项目内置 .venv 虚拟环境中的 Python，
    使用项目本地 .agentos 空间与 .local 输出目录执行离线批处理并生成 HTML 报告。
    若缺少虚拟环境，提供唯一的官方支持指引，绝不静默下载外部代码或修改全局环境。
#>
[CmdletBinding()]
param(
    [Parameter(HelpMessage = "AgentOS 运行时 home 目录，默认为项目根目录下 .agentos/local-demo")]
    [Alias("Home")]
    [string]$HomeDir = "",

    [Parameter(HelpMessage = "HTML 报告及元数据输出目录，默认为项目根目录下 .local/demo_report")]
    [Alias("Output")]
    [string]$OutputDir = "",

    [Parameter(HelpMessage = "在默认浏览器中自动打开生成的 HTML 报告")]
    [switch]$Open
)

$ErrorActionPreference = "Stop"

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

# 确定 .venv 中的 Python 解释器
$PythonCandidates = @(
    (Join-Path $ProjectRoot ".venv\Scripts\python.exe"),
    (Join-Path $ProjectRoot ".venv\bin\python")
)

$PythonExe = $null
foreach ($candidate in $PythonCandidates) {
    if (Test-Path -LiteralPath $candidate) {
        $PythonExe = $candidate
        break
    }
}

if (-not $PythonExe) {
    Write-Host "[错误] 未检测到项目独立的虚拟环境 (.venv)。" -ForegroundColor Red
    Write-Host ""
    Write-Host "[环境初始化指引] 请在支持的环境中执行以下标准步骤以就绪环境：" -ForegroundColor Yellow
    Write-Host "  1. 确保已安装 Python 3.12 运行时" -ForegroundColor Gray
    Write-Host "  2. 在项目根目录执行: python -m venv .venv" -ForegroundColor Gray
    Write-Host "  3. 安装固定依赖:     .\.venv\Scripts\pip install -e ." -ForegroundColor Gray
    Write-Host "依赖安装完成后，重新运行 .\scripts\start-demo.ps1 即可。" -ForegroundColor Yellow
    exit 1
}

# 设定目标目录
$TargetHome = if ($HomeDir) { $HomeDir } else { Join-Path $ProjectRoot ".agentos\local-demo" }
$TargetOutput = if ($OutputDir) { $OutputDir } else { Join-Path $ProjectRoot ".local\demo_report" }

Write-Host "=================================================" -ForegroundColor Cyan
Write-Host "  AgentOS 离线合成数据演示 (Windows 确定性执行)   " -ForegroundColor Cyan
Write-Host "=================================================" -ForegroundColor Cyan
Write-Host "[配置] Python 解释器: $PythonExe" -ForegroundColor Gray
Write-Host "[配置] 任务存储空间: $TargetHome" -ForegroundColor Gray
Write-Host "[配置] 报告输出目录: $TargetOutput" -ForegroundColor Gray
if ($Open) {
    Write-Host "[配置] 浏览器动作:   完成后自动打开报告" -ForegroundColor Gray
}
Write-Host ""
Write-Host "[状态] 正在启动离线合成批处理并生成检查结果..." -ForegroundColor Yellow

$demoArgs = @("-m", "agentos_runtime.demo_app", "--home", $TargetHome, "--output", $TargetOutput)
if ($Open) {
    $demoArgs += "--open"
}

& $PythonExe @demoArgs
$runExitCode = $LASTEXITCODE

if ($runExitCode -eq 0) {
    Write-Host ""
    Write-Host "[成功] 离线演示与检查结果生成完成！" -ForegroundColor Green
    $ReportPath = Join-Path $TargetOutput "index.html"
    if (Test-Path -LiteralPath $ReportPath) {
        Write-Host "[报告] 本地 HTML 报告已就绪: $ReportPath" -ForegroundColor Green
    }
    exit 0
} else {
    Write-Host ""
    Write-Host "[失败] 演示未成功执行或触发安全阻断，退出码: $runExitCode" -ForegroundColor Red
    exit $runExitCode
}
