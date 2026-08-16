$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "未找到 .venv，请先按 README 创建并安装开发环境。"
}
& $python -m pytest
if ($LASTEXITCODE -ne 0) { throw "测试失败。" }
