param(
    [string]$BuildEnvironment = ".venv-build"
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$environmentPath = Join-Path $projectRoot $BuildEnvironment
$buildPython = Join-Path $environmentPath "Scripts\python.exe"

if (-not (Test-Path -LiteralPath $buildPython -PathType Leaf)) {
    py -3.14 -m venv $environmentPath
}

$pythonVersion = & $buildPython -c "import platform; print(platform.python_version())"
if ($LASTEXITCODE -ne 0 -or $pythonVersion.Trim() -ne "3.14.5") {
    throw "正式构建固定使用 Python 3.14.5 x64；当前构建环境为 $pythonVersion。"
}

& $buildPython -m pip install --requirement requirements-build.txt
if ($LASTEXITCODE -ne 0) { throw "安装固定构建依赖失败。" }

& $buildPython scripts\generate_icon.py build\generated\flowpdf.ico
if ($LASTEXITCODE -ne 0) { throw "生成 Windows 图标失败。" }

& $buildPython -m PyInstaller --clean --noconfirm FlowPDF.spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller 构建失败。" }

$distribution = Join-Path $projectRoot "dist\FlowPDF"
Copy-Item -LiteralPath (Join-Path $projectRoot "README.md") -Destination $distribution
Copy-Item -LiteralPath (Join-Path $projectRoot "README.zh-CN.md") -Destination $distribution
Copy-Item -LiteralPath (Join-Path $projectRoot "BUILD_REPORT.md") -Destination $distribution
Copy-Item -LiteralPath (Join-Path $projectRoot "LICENSES") -Destination $distribution -Recurse

Write-Host "构建完成：$projectRoot\dist\FlowPDF\FlowPDF.exe"
Write-Host "该测试构建未进行代码签名，Windows 可能显示未知发布者提示。"
