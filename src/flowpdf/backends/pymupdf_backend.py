from __future__ import annotations

import hashlib
import io
import math
import os
import uuid
import warnings
from contextlib import suppress
from pathlib import Path
from threading import RLock
from typing import Protocol

import pymupdf
from PIL import Image, UnidentifiedImageError

from flowpdf.backends.base import (
    AnnotationInfo,
    AnnotationKind,
    AnnotationSpec,
    DocumentValidation,
    ImageInfo,
    InvalidPasswordError,
    PageInfo,
    PasswordRequiredError,
    PdfBackend,
    PdfEditError,
    PdfOpenError,
    PdfPermissionError,
    PdfResourceLimitError,
    PdfResourceLimits,
    PdfSaveError,
    RenderedPage,
    SearchHit,
    TextEditability,
    TextSpan,
    TextStyle,
)
from flowpdf.backends.pymupdf_runtime import serialized_pymupdf
from flowpdf.editing.text_editor import layout_text
from flowpdf.utils.coordinates import Point, Rect
from flowpdf.utils.fonts import FontResolver

_BASE14_FONTS = {
    "courier",
    "helvetica",
    "symbol",
    "times-roman",
    "zapfdingbats",
}

_ANNOTATION_TYPE_MAP = {
    "highlight": AnnotationKind.HIGHLIGHT,
    "underline": AnnotationKind.UNDERLINE,
    "strikeout": AnnotationKind.STRIKEOUT,
    "text": AnnotationKind.NOTE,
    "freetext": AnnotationKind.FREE_TEXT,
    "ink": AnnotationKind.INK,
    "line": AnnotationKind.LINE,
    "square": AnnotationKind.RECTANGLE,
    "circle": AnnotationKind.ELLIPSE,
}


class ArtifactRegistry(Protocol):
    def register(self, artifact: str | Path) -> None: ...

    def unregister(self, artifact: str | Path) -> None: ...


class PyMuPdfBackend(PdfBackend):
    """PyMuPDF adapter; no Qt types cross this engine seam."""

    def __init__(
        self,
        *,
        limits: PdfResourceLimits | None = None,
        font_resolver: FontResolver | None = None,
        artifact_registry: ArtifactRegistry | None = None,
    ) -> None:
        self._limits = limits or PdfResourceLimits()
        self._font_resolver = font_resolver or FontResolver()
        self._artifact_registry = artifact_registry
        self._document: pymupdf.Document | None = None
        self._source_path: Path | None = None
        self._document_id = ""
        self._revision = 0
        self._can_edit = True
        self._password: str | None = None
        self._owner_authenticated = False
        self._lock = RLock()

    @property
    def document_id(self) -> str:
        return self._document_id

    @property
    def revision(self) -> int:
        return self._revision

    @property
    def source_path(self) -> Path | None:
        return self._source_path

    @serialized_pymupdf
    def open_document(self, path: str | Path, password: str | None = None) -> None:
        source = Path(path)
        try:
            source = source.resolve(strict=True)
            size = source.stat().st_size
        except OSError as exc:
            raise PdfOpenError(f"无法打开 PDF：文件不存在或无法读取（{source}）") from exc
        if size <= 0 or size > self._limits.max_source_bytes:
            raise PdfResourceLimitError("PDF 文件为空或超过允许的大小")

        candidate: pymupdf.Document | None = None
        try:
            candidate = pymupdf.open(source)
            auth_result = 0
            if candidate.needs_pass:
                if password is None:
                    raise PasswordRequiredError("此 PDF 需要密码")
                auth_result = candidate.authenticate(password)
                if not auth_result:
                    raise InvalidPasswordError("PDF 密码不正确")
            self._validate_document(candidate)
            can_edit = (
                not auth_result
                or auth_result >= 4
                or bool(candidate.permissions & pymupdf.PDF_PERM_MODIFY)
            )
        except (PasswordRequiredError, InvalidPasswordError):
            if candidate is not None:
                candidate.close()
            raise
        except PdfResourceLimitError:
            if candidate is not None:
                candidate.close()
            raise
        except (OSError, RuntimeError, ValueError, pymupdf.FileDataError) as exc:
            if candidate is not None:
                candidate.close()
            message = f"无法打开 PDF：文件可能已损坏或格式不受支持（{source.name}）"
            raise PdfOpenError(message) from exc

        with self._lock:
            self.close_document()
            self._document = candidate
            self._source_path = source
            fingerprint = f"{source}|{size}|{source.stat().st_mtime_ns}".encode()
            self._document_id = hashlib.sha256(fingerprint).hexdigest()[:24]
            self._revision = 0
            self._can_edit = can_edit
            self._password = password if auth_result else None
            self._owner_authenticated = auth_result >= 4

    @serialized_pymupdf
    def create_document(self, *, width: float = 595, height: float = 842) -> None:
        if width <= 0 or height <= 0:
            raise PdfEditError("空白页面尺寸必须大于 0")
        if max(width, height) > self._limits.max_page_dimension:
            raise PdfResourceLimitError("空白页面尺寸超过安全上限")
        candidate = pymupdf.open()
        candidate.new_page(width=width, height=height)
        with self._lock:
            self.close_document()
            self._document = candidate
            self._source_path = None
            self._document_id = hashlib.sha256(candidate.tobytes()).hexdigest()[:24]
            self._revision = 0
            self._can_edit = True
            self._password = None
            self._owner_authenticated = False

    @serialized_pymupdf
    def close_document(self) -> None:
        with self._lock:
            if self._document is not None:
                with suppress(Exception):
                    self._document.close()
            self._document = None
            self._source_path = None
            self._document_id = ""
            self._revision = 0
            self._can_edit = True
            self._password = None
            self._owner_authenticated = False

    @serialized_pymupdf
    def page_count(self) -> int:
        with self._lock:
            return self._require_document().page_count

    @serialized_pymupdf
    def page_size(self, page_index: int) -> PageInfo:
        with self._lock:
            page = self._page(page_index)
            crop = page.cropbox
            media = page.mediabox
            shown = page.rect
            return PageInfo(
                width=shown.width,
                height=shown.height,
                rotation=page.rotation,
                cropbox=_rect(crop),
                mediabox=_rect(media),
            )

    @serialized_pymupdf
    def render_page(self, page_index: int, scale: float, clip: Rect | None = None) -> RenderedPage:
        if not math.isfinite(scale) or scale <= 0 or scale > 16:
            raise PdfResourceLimitError("渲染缩放比例超出安全范围")
        with self._lock:
            page = self._page(page_index)
            requested = _fitz_rect(clip) if clip is not None else page.rect
            requested &= page.rect
            if requested.is_empty:
                raise PdfEditError("渲染区域不在页面内")
            estimated_pixels = math.ceil(requested.width * scale) * math.ceil(
                requested.height * scale
            )
            if estimated_pixels > self._limits.max_render_pixels:
                raise PdfResourceLimitError("渲染区域过大，请降低缩放比例或使用分块渲染")
            pixmap = page.get_pixmap(
                matrix=pymupdf.Matrix(scale, scale),
                clip=requested,
                colorspace=pymupdf.csRGB,
                alpha=False,
                annots=True,
            )
            if pixmap.width * pixmap.height > self._limits.max_render_pixels:
                raise PdfResourceLimitError("渲染结果超过像素安全上限")
            return RenderedPage(
                width=pixmap.width,
                height=pixmap.height,
                stride=pixmap.stride,
                samples=bytes(pixmap.samples),
                clip=_rect(requested),
                scale=scale,
            )

    @serialized_pymupdf
    def extract_text_spans(self, page_index: int) -> list[TextSpan]:
        with self._lock:
            page = self._page(page_index)
            try:
                data = page.get_text("dict", sort=False)
            except (RuntimeError, ValueError) as exc:
                raise PdfOpenError("无法提取此页文字，页面结构可能异常") from exc
            spans: list[TextSpan] = []
            for block_index, block in enumerate(data.get("blocks", [])):
                if block.get("type") != 0:
                    continue
                for line_index, line in enumerate(block.get("lines", [])):
                    for span in line.get("spans", []):
                        text = str(span.get("text", ""))
                        if not text:
                            continue
                        font = str(span.get("font", ""))
                        spans.append(
                            TextSpan(
                                page_index=page_index,
                                text=text,
                                rect=_rect(pymupdf.Rect(span["bbox"])),
                                font_size=float(span.get("size", 11)),
                                color=int(span.get("color", 0)),
                                font_family=font,
                                flags=int(span.get("flags", 0)),
                                block_index=block_index,
                                line_index=line_index,
                                editability=self._text_editability(font, text),
                            )
                        )
            return spans

    @serialized_pymupdf
    def search_text(self, query: str) -> list[SearchHit]:
        needle = query.strip()
        if not needle:
            return []
        if len(needle) > 512:
            raise PdfResourceLimitError("搜索文字过长")
        with self._lock:
            document = self._require_document()
            hits: list[SearchHit] = []
            for page_index in range(document.page_count):
                page = document.load_page(page_index)
                hits.extend(
                    SearchHit(page_index, _rect(result)) for result in page.search_for(needle)
                )
                if len(hits) >= 10_000:
                    return hits[:10_000]
            return hits

    @serialized_pymupdf
    def add_text(self, page_index: int, rect: Rect, text: str, style: TextStyle) -> Rect:
        if not text:
            raise PdfEditError("文字内容不能为空")
        self._validate_opacity(style.opacity)
        with self._lock:
            self._require_editable()
            self._ensure_object_capacity(64)
            page = self._page(page_index)
            font = self._font_resolver.resolve(style.font_family, text=text)
            font_name = "helv"
            font_file: str | None = None
            if font.path is not None:
                digest = hashlib.sha1(str(font.path).encode()).hexdigest()[:10]
                font_name = f"FP{digest}"
                font_file = str(font.path)
                metric_font = pymupdf.Font(fontfile=font_file)
                measure = metric_font.text_length
            else:

                def measure(value: str, size: float) -> float:
                    return pymupdf.get_text_length(value, fontname=font_name, fontsize=size)

            layout = layout_text(
                text,
                rect,
                font_size=style.font_size,
                strategy=style.overflow,
                measure=measure,
            )
            target = _fitz_rect(layout.rect) & page.rect
            if target.is_empty:
                raise PdfEditError("文字框不在页面内")
            if style.background_color is not None:
                page.draw_rect(
                    target,
                    color=None,
                    fill=style.background_color,
                    fill_opacity=style.opacity,
                    overlay=True,
                )
            remaining = page.insert_textbox(
                target,
                "\n".join(layout.lines),
                fontsize=layout.font_size,
                fontname=font_name,
                fontfile=font_file,
                color=style.color,
                align=max(0, min(2, style.alignment)),
                lineheight=1.0,
                fill_opacity=style.opacity,
                stroke_opacity=style.opacity,
                overlay=True,
            )
            if remaining < -0.01:
                raise PdfEditError("文字仍超出文本框，请扩大区域或缩小字号")
            if style.underline:
                underline_y = min(target.y1 - 1, target.y0 + layout.font_size * 1.1)
                page.draw_line(
                    pymupdf.Point(target.x0, underline_y),
                    pymupdf.Point(target.x1, underline_y),
                    color=style.color,
                    width=max(0.5, layout.font_size / 14),
                    stroke_opacity=style.opacity,
                    overlay=True,
                )
            self._revision += 1
            return _rect(target)

    @serialized_pymupdf
    def replace_text(self, page_index: int, rect: Rect, text: str, style: TextStyle) -> Rect:
        with self._lock:
            self._require_editable()
            self._redact(page_index, rect, images=0, graphics=0, fill=False)
            result = self.add_text(page_index, rect, text, style)
            return result

    @serialized_pymupdf
    def add_image(self, page_index: int, rect: Rect, image_path: str | Path) -> None:
        source = Path(image_path)
        try:
            source = source.resolve(strict=True)
            size = source.stat().st_size
        except OSError as exc:
            raise PdfEditError("无法读取要插入的图片") from exc
        if source.suffix.casefold() not in {".png", ".jpg", ".jpeg", ".webp"}:
            raise PdfEditError("仅支持 PNG、JPEG 和 WEBP 图片")
        if size <= 0 or size > self._limits.max_image_bytes:
            raise PdfResourceLimitError("图片为空或超过大小限制")
        self._validate_image_file(source)
        with self._lock:
            self._require_editable()
            self._ensure_object_capacity(64)
            page = self._page(page_index)
            target = _fitz_rect(rect) & page.rect
            if target.is_empty:
                raise PdfEditError("图片区域不在页面内")
            try:
                if source.suffix.casefold() == ".webp":
                    image_stream = self._convert_webp(source)
                    page.insert_image(
                        target,
                        stream=image_stream,
                        keep_proportion=True,
                        overlay=True,
                    )
                else:
                    page.insert_image(
                        target,
                        filename=str(source),
                        keep_proportion=True,
                        overlay=True,
                    )
            except Exception as exc:
                raise PdfEditError("图片格式无效或无法插入") from exc
            self._revision += 1

    @serialized_pymupdf
    def list_images(self, page_index: int) -> list[ImageInfo]:
        with self._lock:
            page = self._page(page_index)
            output: list[ImageInfo] = []
            for image in page.get_image_info(hashes=False, xrefs=True):
                output.append(
                    ImageInfo(
                        page_index=page_index,
                        rect=_rect(pymupdf.Rect(image["bbox"])),
                        xref=int(image.get("xref", 0)),
                        width=int(image.get("width", 0)),
                        height=int(image.get("height", 0)),
                    )
                )
            return output

    @serialized_pymupdf
    def add_annotation(self, page_index: int, annotation: AnnotationSpec) -> None:
        self._validate_opacity(annotation.opacity)
        with self._lock:
            self._require_editable()
            self._ensure_object_capacity(16)
            page = self._page(page_index)
            target = _fitz_rect(annotation.rect) & page.rect
            if target.is_empty:
                raise PdfEditError("批注区域不在页面内")
            annot = self._create_annotation(page, target, annotation)
            if annot is None:
                raise PdfEditError("无法创建此类批注")
            with suppress(RuntimeError, ValueError):
                annot.set_colors(stroke=annotation.color, fill=annotation.fill_color)
            with suppress(RuntimeError, ValueError):
                annot.set_border(width=max(0.1, annotation.line_width))
            annot.set_opacity(annotation.opacity)
            annot.set_info(content=annotation.content, title=annotation.author)
            annot.update()
            self._revision += 1

    @serialized_pymupdf
    def list_annotations(self, page_index: int) -> list[AnnotationInfo]:
        with self._lock:
            page = self._page(page_index)
            annotations: list[AnnotationInfo] = []
            for annotation in page.annots() or ():
                kind = _ANNOTATION_TYPE_MAP.get(
                    str(annotation.type[1]).casefold(),
                    AnnotationKind.NOTE,
                )
                info = annotation.info or {}
                annotations.append(
                    AnnotationInfo(
                        page_index=page_index,
                        xref=annotation.xref,
                        kind=kind,
                        rect=_rect(annotation.rect),
                        content=str(info.get("content", "")),
                        author=str(info.get("title", "")),
                    )
                )
            return annotations

    @serialized_pymupdf
    def delete_annotation(self, page_index: int, xref: int) -> None:
        with self._lock:
            self._require_editable()
            page = self._page(page_index)
            for annotation in page.annots() or ():
                if annotation.xref == xref:
                    page.delete_annot(annotation)
                    self._revision += 1
                    return
            raise PdfEditError("要删除的批注已不存在")

    @serialized_pymupdf
    def delete_content(self, page_index: int, rect: Rect) -> None:
        with self._lock:
            self._require_editable()
            self._redact(page_index, rect, images=2, graphics=2, fill=True)

    @serialized_pymupdf
    def move_page(self, old_index: int, new_index: int) -> None:
        with self._lock:
            self._require_editable()
            document = self._require_document()
            self._validate_page_index(old_index)
            if not 0 <= new_index < document.page_count:
                raise PdfEditError("目标页码超出范围")
            if old_index == new_index:
                return
            order = list(range(document.page_count))
            moved = order.pop(old_index)
            order.insert(new_index, moved)
            document.select(order)
            self._revision += 1

    @serialized_pymupdf
    def delete_pages(self, page_indices: list[int]) -> None:
        with self._lock:
            self._require_editable()
            document = self._require_document()
            unique = sorted(set(page_indices))
            if not unique:
                return
            for index in unique:
                self._validate_page_index(index)
            if len(unique) >= document.page_count:
                raise PdfEditError("PDF 至少需要保留一页")
            document.delete_pages(unique)
            self._revision += 1

    @serialized_pymupdf
    def rotate_pages(self, page_indices: list[int], degrees: int = 90) -> None:
        if degrees % 90:
            raise PdfEditError("页面旋转角度必须是 90 度的倍数")
        with self._lock:
            self._require_editable()
            for index in sorted(set(page_indices)):
                page = self._page(index)
                page.set_rotation((page.rotation + degrees) % 360)
            if page_indices:
                self._revision += 1

    @serialized_pymupdf
    def insert_blank_page(
        self,
        insert_index: int,
        *,
        width: float = 595,
        height: float = 842,
    ) -> None:
        if width <= 0 or height <= 0 or max(width, height) > self._limits.max_page_dimension:
            raise PdfResourceLimitError("空白页面尺寸无效或超过安全上限")
        with self._lock:
            self._require_editable()
            document = self._require_document()
            if not 0 <= insert_index <= document.page_count:
                raise PdfEditError("插入页码超出范围")
            if document.page_count >= self._limits.max_pages:
                raise PdfResourceLimitError("PDF 页数已达到安全上限")
            self._ensure_object_capacity(8)
            document.new_page(pno=insert_index, width=width, height=height)
            self._revision += 1

    @serialized_pymupdf
    def duplicate_page(self, page_index: int, insert_index: int | None = None) -> None:
        with self._lock:
            self._require_editable()
            document = self._require_document()
            self._validate_page_index(page_index)
            target = page_index + 1 if insert_index is None else insert_index
            if not 0 <= target <= document.page_count:
                raise PdfEditError("复制页面的插入位置超出范围")
            if document.page_count >= self._limits.max_pages:
                raise PdfResourceLimitError("PDF 页数已达到安全上限")
            self._ensure_object_capacity(8)
            document.copy_page(page_index, to=target)
            self._revision += 1

    @serialized_pymupdf
    def insert_pages(
        self,
        source_path: str | Path,
        insert_index: int,
        *,
        password: str | None = None,
    ) -> None:
        source_file = Path(source_path)
        try:
            source_file = source_file.resolve(strict=True)
            source_size = source_file.stat().st_size
        except OSError as exc:
            raise PdfEditError("无法读取待插入的 PDF") from exc
        if source_size <= 0 or source_size > self._limits.max_source_bytes:
            raise PdfResourceLimitError("待插入的 PDF 为空或超过大小限制")
        with self._lock:
            self._require_editable()
            document = self._require_document()
            if not 0 <= insert_index <= document.page_count:
                raise PdfEditError("插入页码超出范围")
            source: pymupdf.Document | None = None
            try:
                source = pymupdf.open(source_file)
                if source.needs_pass and (password is None or not source.authenticate(password)):
                    raise PasswordRequiredError("待插入的 PDF 需要正确密码")
                self._validate_document(source)
                if document.page_count + source.page_count > self._limits.max_pages:
                    raise PdfResourceLimitError("合并后的页数超过安全上限")
                if (
                    document.xref_length() + source.xref_length() + 16
                    > self._limits.max_xref_objects
                ):
                    raise PdfResourceLimitError("合并后的内部对象数量超过安全上限")
                document.insert_pdf(source, start_at=insert_index, annots=True, widgets=True)
            except (PasswordRequiredError, PdfResourceLimitError):
                raise
            except PdfOpenError as exc:
                raise PdfEditError(f"无法插入此 PDF：{exc}") from exc
            except (OSError, RuntimeError, ValueError, pymupdf.FileDataError) as exc:
                raise PdfEditError("无法插入此 PDF，文件可能损坏或受限制") from exc
            finally:
                if source is not None:
                    source.close()
            self._revision += 1

    @serialized_pymupdf
    def export_pages(self, page_indices: list[int], output_path: str | Path) -> None:
        with self._lock:
            source = self._require_document()
            if self._password is not None and not self._owner_authenticated:
                raise PdfPermissionError("加密 PDF 需要使用所有者密码才能导出页面")
            unique = sorted(set(page_indices))
            if not unique:
                raise PdfEditError("没有选择要导出的页面")
            for index in unique:
                self._validate_page_index(index)
            destination = Path(output_path)
            if not destination.parent.is_dir():
                raise PdfSaveError("导出目录不存在")
            if destination.is_symlink():
                raise PdfSaveError("为保护数据，不能导出到符号链接目标")
            if self._source_path is not None and _same_path(destination, self._source_path):
                raise PdfSaveError("不能用页面导出覆盖当前源 PDF")
            temporary = destination.parent / f".flowpdf-export-{uuid.uuid4().hex}.tmp.pdf"
            output: pymupdf.Document | None = pymupdf.open()
            candidate: pymupdf.Document | None = None
            try:
                if self._artifact_registry is not None:
                    self._artifact_registry.register(temporary)
                for index in unique:
                    output.insert_pdf(source, from_page=index, to_page=index)
                save_options: dict[str, object] = {
                    "encryption": pymupdf.PDF_ENCRYPT_NONE,
                }
                if self._password is not None:
                    save_options = {
                        "encryption": pymupdf.PDF_ENCRYPT_AES_256,
                        "owner_pw": self._password,
                        "user_pw": self._password,
                        "permissions": source.permissions,
                    }
                output.ez_save(temporary, **save_options)
                output.close()
                output = None
                candidate = pymupdf.open(temporary)
                if candidate.needs_pass and (
                    self._password is None or not candidate.authenticate(self._password)
                ):
                    raise PdfSaveError("导出结果的密码保护验证失败")
                self._validate_document(candidate)
                if candidate.page_count != len(unique) or temporary.stat().st_size <= 0:
                    raise PdfSaveError("导出结果的页数或文件大小验证失败")
                candidate.close()
                candidate = None
                os.replace(temporary, destination)
            except PdfSaveError:
                raise
            except Exception as exc:
                raise PdfSaveError(f"无法安全导出所选页面：{destination.name}") from exc
            finally:
                if output is not None:
                    output.close()
                if candidate is not None:
                    candidate.close()
                if temporary.exists() and not temporary.is_symlink():
                    with suppress(OSError):
                        temporary.unlink()
                if self._artifact_registry is not None and not temporary.exists():
                    with suppress(OSError, ValueError):
                        self._artifact_registry.unregister(temporary)

    @serialized_pymupdf
    def save_document(self, output_path: str | Path) -> None:
        destination = Path(output_path)
        if not destination.parent.is_dir():
            raise PdfSaveError("保存目录不存在")
        with self._lock:
            document = self._require_document()
            try:
                document.ez_save(
                    destination,
                    encryption=pymupdf.PDF_ENCRYPT_KEEP,
                    permissions=document.permissions,
                )
            except (OSError, RuntimeError, ValueError) as exc:
                raise PdfSaveError(f"无法保存 PDF：{destination.name}") from exc

    @serialized_pymupdf
    def validate_saved_document(self, path: str | Path) -> DocumentValidation:
        candidate: pymupdf.Document | None = None
        source = Path(path)
        try:
            file_size = source.stat().st_size
            if file_size <= 0:
                raise PdfSaveError("保存结果为空")
            candidate = pymupdf.open(source)
            if candidate.needs_pass and (
                self._password is None or not candidate.authenticate(self._password)
            ):
                raise PdfSaveError("保存结果已加密，但无法使用当前会话密码验证")
            self._validate_document(candidate)
            return DocumentValidation(
                page_count=candidate.page_count,
                file_size=file_size,
                repaired=bool(candidate.is_repaired),
            )
        except PdfSaveError:
            raise
        except (OSError, RuntimeError, ValueError, pymupdf.FileDataError) as exc:
            raise PdfSaveError("保存结果无法重新打开验证") from exc
        finally:
            if candidate is not None:
                candidate.close()

    @serialized_pymupdf
    def document_bytes(self) -> bytes:
        with self._lock:
            document = self._require_document()
            try:
                return document.tobytes(
                    garbage=3,
                    deflate=True,
                    deflate_images=True,
                    deflate_fonts=True,
                    use_objstms=1,
                    encryption=pymupdf.PDF_ENCRYPT_KEEP,
                )
            except (RuntimeError, ValueError) as exc:
                raise PdfSaveError("无法创建文档工作快照") from exc

    @serialized_pymupdf
    def load_bytes(self, data: bytes) -> None:
        if not data or len(data) > self._limits.max_source_bytes:
            raise PdfResourceLimitError("文档快照为空或过大")
        try:
            candidate = pymupdf.open(stream=data, filetype="pdf")
            if candidate.needs_pass and (
                self._password is None or not candidate.authenticate(self._password)
            ):
                candidate.close()
                raise PdfOpenError("无法使用当前会话密码恢复加密快照")
            self._validate_document(candidate)
        except PdfOpenError:
            raise
        except (RuntimeError, ValueError, pymupdf.FileDataError) as exc:
            raise PdfOpenError("无法恢复文档工作快照") from exc
        with self._lock:
            source = self._source_path
            document_id = self._document_id
            revision = self._revision
            if self._document is not None:
                self._document.close()
            self._document = candidate
            self._source_path = source
            self._document_id = document_id
            self._revision = revision + 1
            self._can_edit = True

    @serialized_pymupdf
    def is_probably_scanned(self, page_index: int) -> bool:
        with self._lock:
            page = self._page(page_index)
            text = page.get_text("text").strip()
            if len(text) >= 5:
                return False
            page_area = max(1.0, page.rect.get_area())
            image_area = sum(
                (pymupdf.Rect(info["bbox"]) & page.rect).get_area()
                for info in page.get_image_info()
            )
            return image_area / page_area >= 0.4

    def _redact(
        self,
        page_index: int,
        rect: Rect,
        *,
        images: int,
        graphics: int,
        fill: bool,
    ) -> None:
        self._ensure_object_capacity(64)
        page = self._page(page_index)
        target = _fitz_rect(rect) & page.rect
        if target.is_empty:
            raise PdfEditError("永久擦除区域不在页面内")
        page.add_redact_annot(
            target,
            fill=(1.0, 1.0, 1.0) if fill else None,
            cross_out=False,
        )
        page.apply_redactions(images=images, graphics=graphics, text=0)
        self._revision += 1

    def _create_annotation(
        self,
        page: pymupdf.Page,
        target: pymupdf.Rect,
        spec: AnnotationSpec,
    ) -> pymupdf.Annot | None:
        if spec.kind is AnnotationKind.HIGHLIGHT:
            return page.add_highlight_annot(target)
        if spec.kind is AnnotationKind.UNDERLINE:
            return page.add_underline_annot(target)
        if spec.kind is AnnotationKind.STRIKEOUT:
            return page.add_strikeout_annot(target)
        if spec.kind is AnnotationKind.NOTE:
            return page.add_text_annot(target.top_left, spec.content)
        if spec.kind is AnnotationKind.FREE_TEXT:
            return page.add_freetext_annot(
                target,
                spec.content,
                text_color=spec.color,
                fill_color=spec.fill_color,
                opacity=spec.opacity,
            )
        if spec.kind is AnnotationKind.INK:
            points = [pymupdf.Point(point.x, point.y) for point in spec.points]
            if len(points) < 2:
                raise PdfEditError("手写批注至少需要两个点")
            return page.add_ink_annot([points])
        if spec.kind in {AnnotationKind.LINE, AnnotationKind.ARROW}:
            points = spec.points or (
                Point(target.x0, target.y0),
                Point(target.x1, target.y1),
            )
            if len(points) < 2:
                raise PdfEditError("直线批注至少需要两个点")
            annot = page.add_line_annot(
                pymupdf.Point(points[0].x, points[0].y),
                pymupdf.Point(points[-1].x, points[-1].y),
            )
            if spec.kind is AnnotationKind.ARROW:
                annot.set_line_ends(pymupdf.PDF_ANNOT_LE_NONE, pymupdf.PDF_ANNOT_LE_OPEN_ARROW)
            return annot
        if spec.kind is AnnotationKind.RECTANGLE:
            return page.add_rect_annot(target)
        if spec.kind is AnnotationKind.ELLIPSE:
            return page.add_circle_annot(target)
        return None

    def _convert_webp(self, source: Path) -> bytes:
        try:
            with Image.open(source) as image:
                if image.width * image.height > self._limits.max_render_pixels:
                    raise PdfResourceLimitError("图片像素数量超过安全上限")
                converted = image.convert("RGBA" if "A" in image.getbands() else "RGB")
                output = io.BytesIO()
                converted.save(output, format="PNG", optimize=True)
                return output.getvalue()
        except PdfResourceLimitError:
            raise
        except (OSError, UnidentifiedImageError, ValueError) as exc:
            raise PdfEditError("WEBP 图片损坏或无法解码") from exc

    def _validate_image_file(self, source: Path) -> None:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(source) as image:
                    if image.width * image.height > self._limits.max_render_pixels:
                        raise PdfResourceLimitError("图片像素数量超过安全上限")
                    image.verify()
        except PdfResourceLimitError:
            raise
        except (
            Image.DecompressionBombError,
            Image.DecompressionBombWarning,
            OSError,
            UnidentifiedImageError,
            ValueError,
        ) as exc:
            raise PdfEditError("图片损坏、尺寸异常或无法解码") from exc

    def _text_editability(self, font: str, text: str) -> TextEditability:
        base = font.casefold().replace("bold", "").replace("italic", "").strip(" -")
        if base in _BASE14_FONTS:
            return TextEditability.RELIABLE
        resolution = self._font_resolver.resolve(font, text=text)
        return (
            TextEditability.FONT_SUBSTITUTION if resolution.replaced else TextEditability.RELIABLE
        )

    def _validate_document(self, document: pymupdf.Document) -> None:
        if document.page_count <= 0:
            raise PdfOpenError("PDF 没有可显示的页面")
        if document.page_count > self._limits.max_pages:
            raise PdfResourceLimitError("PDF 页数超过安全上限")
        if document.xref_length() > self._limits.max_xref_objects:
            raise PdfResourceLimitError("PDF 内部对象数量超过安全上限")
        for page_index in range(document.page_count):
            rect = document.load_page(page_index).rect
            if max(rect.width, rect.height) > self._limits.max_page_dimension:
                raise PdfResourceLimitError(f"第 {page_index + 1} 页尺寸超过安全上限")

    def _validate_page_index(self, page_index: int) -> None:
        document = self._require_document()
        if not 0 <= page_index < document.page_count:
            raise PdfEditError("页码超出范围")

    def _ensure_object_capacity(self, additional: int) -> None:
        document = self._require_document()
        if document.xref_length() + additional > self._limits.max_xref_objects:
            raise PdfResourceLimitError("PDF 内部对象数量已接近安全上限")

    def _page(self, page_index: int) -> pymupdf.Page:
        self._validate_page_index(page_index)
        return self._require_document().load_page(page_index)

    def _require_document(self) -> pymupdf.Document:
        if self._document is None or self._document.is_closed:
            raise PdfOpenError("尚未打开 PDF")
        return self._document

    def _require_editable(self) -> None:
        self._require_document()
        if not self._can_edit:
            raise PdfPermissionError("此 PDF 的权限不允许修改")

    @staticmethod
    def _validate_opacity(opacity: float) -> None:
        if not 0 <= opacity <= 1:
            raise PdfEditError("透明度必须在 0 到 1 之间")


def _rect(rect: pymupdf.Rect) -> Rect:
    return Rect(float(rect.x0), float(rect.y0), float(rect.x1), float(rect.y1))


def _fitz_rect(rect: Rect) -> pymupdf.Rect:
    normalized = rect.normalized()
    return pymupdf.Rect(normalized.x0, normalized.y0, normalized.x1, normalized.y1)


def _same_path(left: Path, right: Path) -> bool:
    try:
        if left.exists() and right.exists():
            return os.path.samefile(left, right)
    except OSError:
        pass
    return str(left.resolve(strict=False)).casefold() == str(right.resolve(strict=False)).casefold()
