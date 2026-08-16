# FlowPDF

FlowPDF is a local-first PDF viewer and editing project for Windows 10/11. The default
interface is Simplified Chinese. Documents are processed locally: there is no cloud upload,
account, telemetry, or advertising.

The current version is an early MVP under active development. See
[README.zh-CN.md](README.zh-CN.md) for the detailed status and usage instructions.

## Start from a clean environment

```powershell
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -U pip
pip install -e ".[dev]"
python -m flowpdf
```

## Licensing notice

No license is currently granted for FlowPDF's own source code. Dependency license review is
documented in [LICENSES/THIRD_PARTY.md](LICENSES/THIRD_PARTY.md). In particular, PyMuPDF is
offered under AGPL or a commercial license; redistribution decisions must account for that.

