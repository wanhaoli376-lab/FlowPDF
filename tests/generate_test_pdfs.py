from __future__ import annotations

import argparse
import io
from pathlib import Path

import pymupdf
from PIL import Image, ImageDraw


def generate_test_pdfs(output_dir: Path, *, include_stress: bool = True) -> dict[str, Path]:
    """Generate deterministic PDF fixtures without network access."""
    output_dir.mkdir(parents=True, exist_ok=True)
    outputs = {
        "normal": output_dir / "normal-text.pdf",
        "chinese": output_dir / "中文文字.pdf",
        "mixed": output_dir / "mixed-page-sizes.pdf",
        "landscape": output_dir / "landscape.pdf",
        "image": output_dir / "with-image.pdf",
        "scanned": output_dir / "scanned-simulation.pdf",
        "encrypted": output_dir / "encrypted.pdf",
        "corrupt": output_dir / "corrupt-truncated.pdf",
    }
    if include_stress:
        outputs["stress"] = output_dir / "stress-300-pages.pdf"

    _normal_pdf(outputs["normal"])
    _chinese_pdf(outputs["chinese"])
    _mixed_pdf(outputs["mixed"])
    _landscape_pdf(outputs["landscape"])
    _image_pdf(outputs["image"])
    _scanned_pdf(outputs["scanned"])
    _encrypted_pdf(outputs["encrypted"])
    _corrupt_pdf(outputs["normal"], outputs["corrupt"])
    if include_stress:
        _stress_pdf(outputs["stress"])
    return outputs


def _normal_pdf(path: Path) -> None:
    document = pymupdf.open()
    page = document.new_page(width=595, height=842)
    page.insert_text((72, 90), "FlowPDF normal text 2025", fontsize=14)
    page.insert_text((72, 125), "Searchable content", fontsize=11)
    page = document.new_page(width=595, height=842)
    page.insert_text((72, 90), "Second page", fontsize=14)
    document.ez_save(path)
    document.close()


def _chinese_pdf(path: Path) -> None:
    document = pymupdf.open()
    page = document.new_page(width=595, height=842)
    page.insert_text((72, 90), "FlowPDF 中文测试：本地编辑", fontname="china-s", fontsize=14)
    document.ez_save(path)
    document.close()


def _mixed_pdf(path: Path) -> None:
    document = pymupdf.open()
    for index, (width, height) in enumerate(((595, 842), (612, 792), (842, 595)), start=1):
        page = document.new_page(width=width, height=height)
        page.insert_text((36, 50), f"Mixed page {index}: {width} x {height}")
    document.ez_save(path)
    document.close()


def _landscape_pdf(path: Path) -> None:
    document = pymupdf.open()
    page = document.new_page(width=842, height=595)
    page.insert_text((72, 90), "Landscape page")
    document.ez_save(path)
    document.close()


def _sample_image() -> bytes:
    image = Image.new("RGB", (320, 180), "#3B82F6")
    drawing = ImageDraw.Draw(image)
    drawing.rectangle((20, 20, 300, 160), outline="white", width=5)
    drawing.text((90, 76), "FlowPDF image", fill="white")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _image_pdf(path: Path) -> None:
    document = pymupdf.open()
    page = document.new_page(width=595, height=842)
    page.insert_image(pymupdf.Rect(72, 100, 500, 341), stream=_sample_image())
    document.ez_save(path)
    document.close()


def _scanned_pdf(path: Path) -> None:
    image = Image.new("RGB", (900, 1200), "white")
    drawing = ImageDraw.Draw(image)
    drawing.text((120, 180), "SCANNED PAGE - NO TEXT LAYER", fill="black")
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=85)
    document = pymupdf.open()
    page = document.new_page(width=595, height=842)
    page.insert_image(page.rect, stream=buffer.getvalue())
    document.ez_save(path)
    document.close()


def _stress_pdf(path: Path) -> None:
    document = pymupdf.open()
    for index in range(300):
        page = document.new_page(width=595, height=842)
        page.insert_text((36, 50), f"Stress page {index + 1}")
    document.ez_save(path)
    document.close()


def _encrypted_pdf(path: Path) -> None:
    document = pymupdf.open()
    page = document.new_page(width=595, height=842)
    page.insert_text((72, 90), "Password protected FlowPDF fixture")
    document.save(
        path,
        encryption=pymupdf.PDF_ENCRYPT_AES_256,
        owner_pw="flowpdf-owner",
        user_pw="flowpdf-test",
        permissions=pymupdf.PDF_PERM_ACCESSIBILITY | pymupdf.PDF_PERM_PRINT,
    )
    document.close()


def _corrupt_pdf(source: Path, destination: Path) -> None:
    data = source.read_bytes()
    destination.write_bytes(data[: max(32, len(data) // 3)])


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate local FlowPDF test PDFs")
    parser.add_argument("output", nargs="?", type=Path, default=Path("tests/fixtures/generated"))
    args = parser.parse_args()
    generated = generate_test_pdfs(args.output)
    for name, path in generated.items():
        print(f"{name}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
