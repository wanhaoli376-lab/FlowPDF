from __future__ import annotations

from dataclasses import dataclass, field

from flowpdf.document_mode.models import FlowDocument


class ProjectError(RuntimeError):
    """A FlowPDF project could not be safely stored or opened."""


@dataclass(frozen=True, slots=True)
class ProjectState:
    cursor_position: int = 0
    selection_anchor: int = 0
    scroll_y: int = 0
    zoom_factor: float = 1.0
    current_page: int = 0

    def __post_init__(self) -> None:
        if min(self.cursor_position, self.selection_anchor, self.scroll_y, self.current_page) < 0:
            raise ValueError("工程视图状态不能包含负值")
        if not 0.1 <= self.zoom_factor <= 8.0:
            raise ValueError("工程缩放比例超出允许范围")


@dataclass(frozen=True, slots=True)
class ProjectManifest:
    format: str = "FlowPDF Project"
    format_version: int = 1
    created_with: str = "FlowPDF"
    source_pdf_path: str = ""
    source_pdf_sha256: str = ""
    document_file: str = "document.json"
    assets_directory: str = "assets"
    state: ProjectState = field(default_factory=ProjectState)


@dataclass(frozen=True, slots=True)
class ProjectBundle:
    document: FlowDocument
    state: ProjectState
    manifest: ProjectManifest
