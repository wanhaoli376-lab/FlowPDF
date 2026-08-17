from __future__ import annotations

from flowpdf.document_mode.importing.extracted import ExtractedPage
from flowpdf.document_mode.importing.reading_order import detect_columns
from flowpdf.document_mode.importing.report import ImportReport
from flowpdf.document_mode.models import Paragraph, SemanticRole


def score_import(pages: list[ExtractedPage], paragraphs: list[Paragraph]) -> ImportReport:
    total_area = sum(page.width_pt * page.height_pt for page in pages) or 1.0
    text_area = sum(_area(line.bbox) for page in pages for line in page.lines)
    image_area = sum(_area(image.bbox) for page in pages for image in page.images)
    text_coverage = min(1.0, text_area / total_area)
    image_coverage = min(1.0, image_area / total_area)
    columns = detect_columns(pages)
    warnings: list[str] = []
    score = 100
    if columns > 1:
        score -= 45
        warnings.append("检测到双栏或多栏内容，文档模式可能改变阅读顺序。")
    if text_coverage < 0.002:
        score -= 50
        warnings.append("页面文字层很少，文档可能主要由扫描图片组成。")
    if image_coverage > 0.65:
        score -= 20
        warnings.append("页面图片覆盖率较高。")
    page_sizes = {(round(page.width_pt, 1), round(page.height_pt, 1)) for page in pages}
    if len(page_sizes) > 1:
        score -= 10
        warnings.append("检测到混合页面尺寸，导入后将使用统一页面设置。")
    if sum(page.drawing_count for page in pages) > max(100, len(pages) * 30):
        score -= 15
        warnings.append("页面包含大量矢量绘图，复杂区域可能降级为固定内容。")
    score = max(0, min(100, score))
    if score >= 80:
        recommended = "document"
    elif score >= 60:
        recommended = "document_with_warning"
    else:
        recommended = "layout"
    return ImportReport(
        score=score,
        recommended_mode=recommended,
        detected_columns=columns,
        text_coverage=text_coverage,
        image_coverage=image_coverage,
        paragraph_count=len(paragraphs),
        heading_count=sum(
            paragraph.semantic_role
            in {
                SemanticRole.TITLE,
                SemanticRole.HEADING1,
                SemanticRole.HEADING2,
                SemanticRole.HEADING3,
            }
            for paragraph in paragraphs
        ),
        warnings=warnings,
    )


def _area(bbox: tuple[float, float, float, float]) -> float:
    return max(0.0, bbox[2] - bbox[0]) * max(0.0, bbox[3] - bbox[1])
