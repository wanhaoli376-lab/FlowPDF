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
    throw "Release builds require Python 3.14.5 x64; found $pythonVersion."
}

& $buildPython -m pip install --requirement requirements-build.txt
if ($LASTEXITCODE -ne 0) { throw "Installing pinned build dependencies failed." }

& $buildPython scripts\generate_icon.py build\generated\flowpdf.ico
if ($LASTEXITCODE -ne 0) { throw "Generating the Windows icon failed." }

& $buildPython -m PyInstaller --clean --noconfirm FlowPDF.spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed." }

$distribution = Join-Path $projectRoot "dist\FlowPDF"
Copy-Item -LiteralPath (Join-Path $projectRoot "README.md") -Destination $distribution
Copy-Item -LiteralPath (Join-Path $projectRoot "README.zh-CN.md") -Destination $distribution
Copy-Item -LiteralPath (Join-Path $projectRoot "BUILD_REPORT.md") -Destination $distribution
Copy-Item -LiteralPath (Join-Path $projectRoot "MANUAL_DOCUMENT_MODE_TEST.md") -Destination $distribution
Copy-Item -LiteralPath (Join-Path $projectRoot "LICENSES") -Destination $distribution -Recurse

Write-Host "Build complete: $projectRoot\dist\FlowPDF\FlowPDF.exe"
Write-Host "This test build is unsigned; Windows may show an unknown publisher warning."
