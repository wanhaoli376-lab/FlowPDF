# FlowPDF

**English** | [简体中文](README.zh-CN.md)

FlowPDF is a local-first, dual-mode PDF editor for Windows 10/11. Its interface defaults to
Simplified Chinese, and documents stay on the local computer: there is no upload, mandatory
account, telemetry, or advertising. Version `0.1.0a1` retains a fixed-coordinate **Layout
Editing Mode** and adds a **Document Editing Mode** for single-column text PDFs. Document mode
reconstructs the source into reflowable content that can be edited like a word-processing
document, saved as a project, and exported as a newly laid-out PDF.

## Current feature status

### Completed and covered by automated tests

Document Editing Mode:

- PDF text, images, fonts, and source coordinates are extracted in the background. FlowPDF
  analyzes single-column reading order, paragraphs, headings, lists, repeated headers and
  footers, and document complexity, then shows a 0–100 import score and mode recommendation.
  Two-column and scanned pages receive substantially lower scores.
- Content is stored in an independent, serializable `FlowDocument` model. Neither
  `QTextDocument` nor the original PDF coordinates are the sole data source. Each imported
  paragraph retains its source page, bounding box, original text/font, and confidence score.
- The whole document uses one continuous `QTextDocument`: click to place the caret, type Chinese
  and English continuously, press Enter to create a paragraph, use Backspace to merge paragraphs,
  select with the mouse or Shift, copy/cut/paste across pages, undo/redo, and commit Chinese IME
  input.
- Text wraps automatically and pushes following paragraphs down. Overflow adds pages; deleting
  content reflows later paragraphs upward and removes an empty trailing page when no hard page
  break requires it. Automated tests cover insertion and removal of more than 200 Chinese
  characters.
- The continuous document is presented as separate white physical sheets with real margins,
  page gaps, shadows, and a current-page border. Later-page clicking, cross-page dragging,
  double-click word selection, Chinese IME candidate coordinates, and wheel scrolling share one
  page-coordinate mapping.
- Actual size, fit page, and fit width are supported. The document page list generates
  low-resolution thumbnails only near the visible range and refreshes them with a debounce after
  input instead of repainting the entire list on every keystroke.
- Character and paragraph controls include font, size, bold, italic, underline, strikeout, text
  and background color, superscript/subscript, clear formatting, four alignments, line spacing,
  first-line/left/right indentation, bullets, numbering, hard page breaks, and ordinary block
  images.
- `.flowpdfproj` is a restricted ZIP container that stores structure, formatting, images, and view
  state. It checks path traversal, symbolic links, zip bombs, format versions, and asset hashes,
  and saves through a temporary file followed by atomic replacement.
- Project saves and PDF exports are bound to a document revision. Edits made while a background
  operation is running remain unsaved, and mode switching does not discard late changes.
  Recovery checkpoints use session tokens so an in-flight task cannot recreate a record after a
  successful save.
- Document-mode export creates a newly laid-out PDF instead of covering original pages or
  rasterizing them. The result is reopened and validated for page count, dimensions, searchable
  Chinese/English text, and image count before it replaces the target.
- Document-mode recovery checkpoints store the compressed model and content-addressed images,
  never the PDF password. Saving a project clears its associated recovery record.
- Switching from document mode to layout mode first generates and validates a fixed-layout
  snapshot. The two modes do not pretend to share one internal object model.

Layout Editing Mode:

- Open PDFs from the file picker or drag and drop, use recent files, create a blank PDF, work with
  Chinese paths, and enter passwords for protected files.
- The source PDF is treated as read-only. The first save suggests
  `original_name_edited.pdf` (localized as `原文件名_已修改.pdf`) and never silently overwrites the
  source.
- Continuous-scroll and single-page views, page virtualization, thumbnails, page-number jumps,
  actual size, fit page, fit width, Ctrl+wheel zoom, mixed page sizes, and landscape pages.
- Progressive background rendering, high-zoom tiles, and a bounded 512 MB LRU cache whose limit
  can be configured. Obsolete queued jobs are cancelled. Results from obsolete MuPDF calls that
  already started are discarded, although a native call cannot be force-interrupted midway.
- Full-text search, previous/next result navigation, and page highlighting.
- Multi-page selection, drag reordering, deletion, duplication, rotation, blank-page insertion,
  PDF insertion/merge, split, and selected-page export.
- Add Chinese or English text with font, size, underline, text/background color, opacity,
  alignment, and four overflow strategies.
- Double-click an existing text span to remove the original content and write replacement text.
  The old text is no longer searchable or copyable. Missing fonts produce an explicit fallback
  notice, and scanned pages show the OCR status instead of failing silently.
- Insert PNG, JPEG, and WEBP images.
- Add highlight, underline, strikeout, note, line, arrow, rectangle, and ellipse annotations. The
  annotation list supports page navigation, deletion, and undo.
- **Permanent Erase** removes text, images, and original vector content in the selected region; it
  is not a black rectangle placed over the page.
- One command history covers the connected editing and page operations, with Ctrl+Z/Ctrl+Y undo
  and redo.
- Saving writes a temporary file, reopens it, validates page count and size, and atomically
  replaces the target. A failed save cannot corrupt an existing target.
- Compact command recovery logs never store PDF passwords. Startup offers Restore, Discard, and
  View Details options.
- Light/dark themes, high-DPI policy, offline test-PDF generation, and a Windows portable-directory
  build configuration.

### Partially completed

Document Editing Mode:

- The first version focuses on single-column text, headings, body paragraphs, lists, and ordinary
  images. Two-column layouts, complex tables, formulas, and vector graphics reduce the import
  score and trigger a layout-mode recommendation. Automatic image fallback for complex regions
  does not yet cover every PDF construction.
- Images can be inserted, deleted, resized proportionally, aligned left/center/right, and retained
  in projects and PDF exports. The current UI does not yet provide drag resize handles or a
  complete inline/block image property panel.
- Page setup supports A4, Letter, custom sizes, orientation, margins, and basic page numbers.
  Imported headers and footers can be retained, but there is no complete visual header/footer
  editor.
- Find and Replace All work. The search bar currently shows the total number of matches but not a
  precise “result N of M” cursor for document mode.
- The editor and PDF exporter use different text-layout engines. Export compares their page counts
  and reports a mismatch instead of silently changing margins; switching to layout mode then
  requires confirmation. Exact line breaks cannot yet be guaranteed for every font combination.
- Header, footer, page-number, and original-pagination options exist in the model, but the import
  dialog does not expose every retain/remove choice. Current defaults retain headers/footers and
  page numbers while allowing continuous reflow.

Layout Editing Mode:

- Added text and images are written correctly, but the first-version UI cannot reselect them for
  free movement, resizing, rotation, layer changes, or copy and paste.
- Text boxes support underline. Bold and italic controls are visibly disabled until reliable font
  variant resolution is available, avoiding output that claims a style it did not render.
- Existing images can be detected by the backend, but the UI has no selection and replacement
  entry point yet.
- Annotations can be added, listed, and deleted. Freehand drawing, erasing, annotation property
  editing, and Windows Ink optimization are not complete.
- Background rendering uses Qt's thread pool, but MuPDF calls are serialized process-wide because
  PyMuPDF documents that it is not safe for concurrent multithreaded use. Future parallel
  rendering must use isolated processes.

### Not implemented

- A visual-signature library, handwritten signature pad, and certificate-backed digital
  signatures.
- Clipboard images, object-layer move/resize handles, image opacity, and front/back layering.
- An OCR engine. The first version only provides the abstraction, scanned-page detection, and an
  “optional component not installed” message.
- Reliable semantic reconstruction for multi-column documents, complex table editing, formula
  editing, complete text wrapping, footnotes/endnotes, revision collaboration, and DOCX export.
- Different odd/even headers and footers.
- Complex form editing and bookmark editing.

## Start from a clean environment

Development prefers Python 3.14; the declared compatibility range is Python 3.12–3.14:

```powershell
py -3.14 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -U pip
pip install -e ".[dev]"
python -m flowpdf
```

Common commands:

```powershell
scripts\run_dev.ps1
scripts\lint.ps1
scripts\test.ps1
scripts\benchmark.ps1
```

## Windows build

The release build is pinned to CPython 3.14.5 x64 and the exact dependency versions in
`requirements-build.txt`:

```powershell
scripts\build_windows.ps1
```

The portable directory is written to `dist\FlowPDF\`. The build script generates a multi-size
`.ico` file and refuses other Python patch versions. See [BUILD_REPORT.md](BUILD_REPORT.md) for the
detailed verification record. The current binary is not code-signed, so Windows may display an
“Unknown publisher” warning.

## Testing and performance

`pytest` generates ordinary text, Chinese, single-/two-column, mixed-size, landscape, image,
simulated-scan, 300-page, encrypted, and damaged PDFs without network downloads. Tests cover
coordinates, caching, undo, page operations, true text replacement, safe saving, document
reconstruction, automatic reflow, project format, recovery, and searchable PDF export. The
performance script writes a JSON baseline for the current machine; those numbers are useful only
for regression comparisons and are not absolute claims about other computers.

CI runs on Windows with Python 3.12 and 3.14:

```powershell
ruff check .
ruff format --check .
pytest
```

## File and security design

PDFs are treated as untrusted input. FlowPDF does not execute embedded JavaScript or automatically
open external links or attachments. Passwords remain in memory, and logs do not record passwords
or PDF body text. Page count, file size, page dimensions, image size, and render pixel count have
resource limits. A source PDF is limited to 256 MiB and 250,000 internal objects. Files larger than
64 MiB remain viewable but snapshot-based editing is refused with a suggestion to split the file,
preventing multiple large allocations on the rejection path. Saving follows “temporary file →
reopen and validate → atomic target replacement” and never writes in place over the source PDF.
Encrypted undo snapshots and saved copies retain password protection. Page export requires the
owner password and uses the same validated temporary-file and atomic-replacement flow, so a
restricted user-password session cannot gain permissions through export.

PyMuPDF explicitly does not support concurrent use from multiple threads. All native MuPDF calls
therefore share a process-wide reentrant lock, while Qt background tasks keep expensive operations
off the GUI thread. True parallel processing will use isolated processes rather than removing this
protection.

## Important limitations

- PDF is not a Word document. Document mode reflows reconstructed content instead of preserving
  every original coordinate. Complex PDFs may not retain their exact layout; use the import score
  to choose layout mode when appropriate.
- Missing fonts are substituted and may change appearance. Substantially longer replacement text
  may require a smaller font or a larger region.
- Scanned PDFs require OCR. Document mode reflows ordinary paragraphs but does not fully
  reconstruct complex paragraphs, footnotes, formulas, or multi-column content.
- Certificate-backed digital signatures are not available.
- Some permission-restricted, resource-abnormal, or damaged PDFs cannot be edited.
- Source PDFs larger than 64 MiB can currently be viewed and split but not edited through the
  snapshot-based undo path.
- Snapshot undo has a 256 MB retained-history budget. An individual mutation that exceeds the
  budget is rejected before execution or rolled back automatically. Large-PDF overhead remains
  substantial; incremental undo is a future priority.
- The normal mouse wheel scrolls continuously; zoom uses Ctrl+wheel. There is no separate setting
  to make the plain wheel zoom.
- The right properties panel currently contains only basic guidance. Object-level movement,
  resizing, and secondary property editing are not connected.
- Automated tests cover Chinese IME commits and candidate rectangles in document mode. Candidate
  window placement for different Windows IMEs and touch devices still requires the manual checks
  in [MANUAL_DOCUMENT_MODE_TEST.md](MANUAL_DOCUMENT_MODE_TEST.md).

## Licensing

No license is currently granted for FlowPDF's own source code; do not label the project or binary
as MIT. The preliminary third-party review is in
[LICENSES/THIRD_PARTY.md](LICENSES/THIRD_PARTY.md). Before distributing a release, complete the
final inventory and collect required license texts, with particular attention to PyMuPDF's
AGPL/commercial dual license and PySide6/Qt's LGPL/GPL/commercial terms.
