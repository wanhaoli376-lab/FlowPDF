# FlowPDF

FlowPDF is a local-first PDF viewer and editing MVP for Windows 10/11. The default UI is
Simplified Chinese. Files stay on the computer: there is no upload, account, telemetry, or
advertising.

The tested MVP includes asynchronous virtualized/tiled viewing, thumbnails, search, page
reordering and merge/split operations, text and image insertion, safe existing-text
replacement, common annotations, permanent content deletion, unified undo/redo, recovery
logs, and validated atomic saving to a protected copy.

Object manipulation after insertion, visual signatures, freehand annotation, OCR, and full
paragraph reflow are not implemented yet. See [README.zh-CN.md](README.zh-CN.md) for the exact
completed/partial/not-implemented status; no unfinished feature is presented as complete.

## Start from a clean environment

Python 3.14 is the development baseline; supported project metadata covers 3.12 through 3.14.

```powershell
py -3.14 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -U pip
pip install -e ".[dev]"
python -m flowpdf
```

Run quality checks with `scripts\lint.ps1` and `scripts\test.ps1`. Run the local 300-page
baseline with `scripts\benchmark.ps1`.

## Windows build

`scripts\build_windows.ps1` uses CPython 3.14.5 x64 and the exact versions in
`requirements-build.txt`, then produces `dist\FlowPDF\FlowPDF.exe`. See
[BUILD_REPORT.md](BUILD_REPORT.md) for verification and signing status.

## Licensing notice

No license is currently granted for FlowPDF's own source code. Dependency review is documented
in [LICENSES/THIRD_PARTY.md](LICENSES/THIRD_PARTY.md). In particular, PyMuPDF is offered under
AGPL or a commercial license, and PySide6/Qt redistribution has LGPL/GPL/commercial conditions.
Complete the final license inventory before any public distribution.
