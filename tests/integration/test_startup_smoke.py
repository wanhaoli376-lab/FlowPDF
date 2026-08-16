from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def test_python_module_starts_event_loop_and_exits_cleanly(tmp_path) -> None:
    environment = os.environ.copy()
    environment["QT_QPA_PLATFORM"] = "offscreen"
    environment["FLOWPDF_DATA_DIR"] = str(tmp_path / "app-data")
    project_root = Path(__file__).resolve().parents[2]

    completed = subprocess.run(
        [sys.executable, "-m", "flowpdf", "--smoke-test"],
        cwd=project_root,
        env=environment,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
