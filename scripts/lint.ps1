$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "未找到 .venv，请先按 README 创建并安装开发环境。"
}
& $python -m ruff check .
if ($LASTEXITCODE -ne 0) { throw "ruff 检查失败。" }
& $python -m ruff format --check .
if ($LASTEXITCODE -ne 0) { throw "ruff 格式检查失败。" }
