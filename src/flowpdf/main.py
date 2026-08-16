from __future__ import annotations

import sys

from flowpdf.application import create_application
from flowpdf.utils.logging import configure_logging, get_logger


def main() -> int:
    """Start FlowPDF and return the Qt event-loop exit code."""
    configure_logging()
    logger = get_logger(__name__)
    try:
        app, window = create_application(sys.argv)
        window.show()
        return app.exec()
    except Exception:
        logger.exception("FlowPDF failed to start")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
