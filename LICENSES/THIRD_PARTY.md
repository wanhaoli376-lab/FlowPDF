# Third-party license review

This file is an initial engineering review, not legal advice. Before redistribution, generate
an inventory from the exact locked build environment and include the corresponding license
texts.

| Dependency | Typical license model | FlowPDF use | Distribution note |
|---|---|---|---|
| Python | PSF License | Runtime | Include Python notices when bundling. |
| PySide6 / Qt for Python | LGPLv3/GPLv3/commercial | GUI | A bundled LGPL build must preserve user relinking and required notices. Confirm Qt modules used. |
| PyMuPDF | AGPLv3/commercial | PDF engine | AGPL obligations can apply to the complete distributed application; obtain commercial terms if AGPL is unsuitable. |
| pytest | MIT | Development only | Not normally bundled. |
| ruff | MIT | Development only | Not normally bundled. |
| PyInstaller | GPLv2 with bootloader exception | Packaging | The exception permits distributing bundled applications; include required notices. |
| Pillow | HPND | Optional image/testing support | Include its license when bundled. |

FlowPDF's own source currently has **no license grant**. Do not label the whole project MIT.

