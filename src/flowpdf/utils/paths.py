from __future__ import annotations

from pathlib import Path


def suggest_edited_copy(source_path: str | Path) -> Path:
    """Suggest a non-destructive output path next to the source PDF."""
    source = Path(source_path)
    stem = source.stem
    candidate = source.with_name(f"{stem}_已修改.pdf")
    sequence = 2
    while candidate.exists() or _same_path(candidate, source):
        candidate = source.with_name(f"{stem}_已修改 ({sequence}).pdf")
        sequence += 1
    return candidate


def _same_path(left: Path, right: Path) -> bool:
    try:
        return left.resolve(strict=False) == right.resolve(strict=False)
    except OSError:
        return str(left.absolute()).casefold() == str(right.absolute()).casefold()
