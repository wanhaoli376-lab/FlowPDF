# Third-party license review

This file is an initial engineering review, not legal advice. Before redistribution, generate
an inventory from the exact locked build environment and include the corresponding license
texts.

| Locked dependency | Typical license model | FlowPDF use | Distribution note |
|---|---|---|---|
| CPython 3.14.5 | PSF License | Bundled runtime | Include Python notices. |
| PySide6 / Qt for Python 6.11.1 | LGPLv3/GPLv3/commercial | GUI | A bundled LGPL build must meet notice, source/relinking and other applicable conditions; confirm every bundled Qt module. |
| shiboken6 6.11.1 | LGPLv3/GPLv3/commercial | PySide runtime | Review together with Qt for Python. |
| PyMuPDF 1.28.2 | AGPLv3/commercial | PDF engine | AGPL obligations can apply to the complete distributed application; obtain commercial terms if AGPL is unsuitable. |
| Pillow 12.2.0 | HPND | Image import and icon generation | Include its license. |
| PyInstaller 6.22.1 | GPLv2 with bootloader exception | Packaging | The bootloader exception permits bundled output subject to its terms; include notices. |
| setuptools 84.0.0 | MIT | Build dependency | Not bundled as an application feature; retain build-environment notice. |
| pytest 9.1.1 | MIT | Development only | Not bundled in the intended release directory. |
| ruff 0.16.2 | MIT | Development only | Not bundled. |

FlowPDF's own source currently has **no license grant**. Do not label the whole project MIT.

The repository currently contains an engineering inventory, not a complete redistribution
notice bundle. Public distribution is **not license-cleared** until exact upstream license texts,
copyright notices, Qt module inventory, and the chosen PyMuPDF licensing route are recorded.
