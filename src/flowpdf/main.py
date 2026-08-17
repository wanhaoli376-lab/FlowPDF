from __future__ import annotations

import logging
import sys
from pathlib import Path

from PySide6.QtCore import QElapsedTimer, QTimer

from flowpdf.application import create_application
from flowpdf.utils.logging import configure_logging, get_logger


def main() -> int:
    """Start FlowPDF and return the Qt event-loop exit code."""
    logger = None
    try:
        smoke_test = "--smoke-test" in sys.argv
        document_smoke = "--smoke-document-mode" in sys.argv
        smoke_output = _option_path(sys.argv, "--smoke-save")
        smoke_project = _option_path(sys.argv, "--smoke-project")
        smoke_document_export = _option_path(sys.argv, "--smoke-document-export")
        arguments = _without_internal_options(sys.argv)
        app, window = create_application(arguments)
        configure_logging()
        logger = get_logger(__name__)
        window.show()
        if smoke_test:
            window.lifecycle_controller.mode_selector = lambda _report: (
                "document" if document_smoke else "layout"
            )
            failures: list[str] = []
            window.show_error = lambda title, message: failures.append(f"{title}: {message}")
            input_pdf = len(arguments) > 1 and Path(arguments[1]).suffix.casefold() == ".pdf"
            if input_pdf:
                elapsed = QElapsedTimer()
                elapsed.start()
                state = {
                    "save_started": False,
                    "edited": False,
                    "project_started": False,
                    "export_started": False,
                }

                def check_smoke_result() -> None:
                    if failures:
                        logger.error("Smoke test failure: %s", "; ".join(failures))
                        window.close()
                        app.exit(2)
                        return
                    if document_smoke:
                        controller = window.document_mode_controller
                        if controller.document is not None:
                            if not state["edited"]:
                                state["edited"] = True
                                window.document_editor_view.editor.insertPlainText(
                                    "FlowPDF document mode packaged smoke 中文。"
                                )
                            if smoke_project is not None and not state["project_started"]:
                                state["project_started"] = True
                                controller.save_project_to(smoke_project)
                            elif smoke_project is None or (
                                smoke_project.exists() and controller.tasks.active_count == 0
                            ):
                                if (
                                    smoke_document_export is not None
                                    and not state["export_started"]
                                ):
                                    state["export_started"] = True
                                    controller.export_pdf_to(smoke_document_export)
                                elif smoke_document_export is None or (
                                    smoke_document_export.exists()
                                    and controller.tasks.active_count == 0
                                ):
                                    controller.close_document(discard=True)
                                    window.close()
                                    return
                        if elapsed.elapsed() >= 25_000:
                            failures.append("打包态文档模式工程或导出超时")
                            logger.error("Smoke test failure: %s", failures[-1])
                            window.close()
                            app.exit(2)
                            return
                        QTimer.singleShot(50, check_smoke_result)
                        return
                    if window.controller.session is not None:
                        if smoke_output is None:
                            window.close()
                            return
                        if not state["save_started"]:
                            state["save_started"] = True
                            window.controller.save_to(smoke_output)
                        elif (
                            smoke_output.exists()
                            and window.controller.tasks.active_count == 0
                            and not window.controller.session.is_dirty
                        ):
                            window.close()
                            return
                    if elapsed.elapsed() >= 15_000:
                        failures.append("打包态打开或保存超时")
                        logger.error("Smoke test failure: %s", failures[-1])
                        window.close()
                        app.exit(2)
                        return
                    QTimer.singleShot(50, check_smoke_result)

                QTimer.singleShot(50, check_smoke_result)
            else:
                QTimer.singleShot(750, window.close)
        else:
            QTimer.singleShot(0, window.lifecycle_controller.offer_recovery)
        result = app.exec()
        return 2 if smoke_test and failures else result
    except Exception:
        if logger is not None:
            logger.exception("FlowPDF failed to start")
        else:
            logging.exception("FlowPDF failed to start before logging was configured")
        return 1


def _option_path(arguments: list[str], option: str) -> Path | None:
    try:
        index = arguments.index(option)
    except ValueError:
        return None
    if index + 1 >= len(arguments):
        raise ValueError(f"{option} 缺少路径")
    return Path(arguments[index + 1])


def _without_internal_options(arguments: list[str]) -> list[str]:
    output: list[str] = []
    skip_next = False
    for argument in arguments:
        if skip_next:
            skip_next = False
            continue
        if argument in {"--smoke-test", "--smoke-document-mode"}:
            continue
        if argument in {"--smoke-save", "--smoke-project", "--smoke-document-export"}:
            skip_next = True
            continue
        output.append(argument)
    return output


if __name__ == "__main__":
    raise SystemExit(main())
