#!/usr/bin/env python3
"""Convert a PDF into Markdown text alongside rendered page images.

Part of the `markdown_forge` framework.

This tool performs a two-phase extraction:
- Text content is parsed with ``pdfminer.six`` so we can filter out repeating
  headers/footers and simple page numbers.
- Page images are produced with ``PyMuPDF`` (``fitz``) at a configurable DPI and
  saved into the ``source/extracted`` workspace for later reference.

Usage:
    python tools/pdf_to_markdown.py path/to/file.pdf [--dest DIR] [--force]

The script creates a workspace sibling to the PDF (or inside ``--dest``) with
this structure:
    <slug>/
        <slug>.md
        source_pdf/
            <original.pdf>
            extracted/
                page-0001.png
                page-0002.png
                ...

Filtering heuristics can be tuned via CLI flags. Repeated top/bottom margin
lines (e.g. headers, footers) are detected across pages and removed.
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional, Sequence, Tuple

import fitz  # type: ignore
from pdfminer.high_level import extract_pages
from pdfminer.layout import LTTextContainer, LTTextLine

try:  # Local import when executed from repo root
    from epub_folderize import slugify
except ImportError:  # pragma: no cover - fallback to package-style import
    from tools.epub_folderize import slugify  # type: ignore


DEFAULT_SKIP_PATTERNS = [
    r"^\d+$",  # bare page numbers
    r"^page\s+\d+(\s*/\s*\d+)?$",
    r"^\d+\s*/\s*\d+$",
    r"^isbn\b.*$",
]


@dataclass
class ExtractionConfig:
    margin_top: float
    margin_bottom: float
    min_repeating: int
    skip_patterns: Sequence[re.Pattern[str]]


def compile_skip_patterns(patterns: Iterable[str]) -> List[re.Pattern[str]]:
    """Compile regex strings into case-insensitive patterns, validating input."""
    compiled: List[re.Pattern[str]] = []
    for raw in patterns:
        try:
            compiled.append(re.compile(raw, re.IGNORECASE))
        except re.error as exc:
            raise ValueError(f"Invalid skip pattern '{raw}': {exc}") from exc
    return compiled


def ensure_workspace(pdf_path: Path, dest_root: Optional[Path], force: bool) -> Tuple[Path, Path, Path]:
    """Create/prepare the publication workspace and move the source PDF."""
    if not pdf_path.exists() or not pdf_path.is_file():
        raise FileNotFoundError(f"PDF '{pdf_path}' not found")

    target_root = dest_root or pdf_path.parent

    title: Optional[str] = None
    try:
        with fitz.open(pdf_path) as doc:
            metadata = doc.metadata or {}
            title = (metadata.get("title") or "").strip()
    except Exception:  # pragma: no cover - metadata retrieval best-effort
        title = None

    slug_source = title if title else pdf_path.stem
    folder_name = slugify(slug_source, fallback=pdf_path.stem)

    book_root = target_root / folder_name
    source_dir = book_root / "source_pdf"
    extracted_dir = source_dir / "extracted"
    markdown_path = book_root / f"{folder_name}.md"
    stored_pdf_path = source_dir / pdf_path.name

    if book_root.exists() and not force:
        raise FileExistsError(f"Destination '{book_root}' already exists; use --force to overwrite")

    if book_root.exists() and force:
        shutil.rmtree(book_root)

    extracted_dir.mkdir(parents=True, exist_ok=True)

    if pdf_path.resolve() != stored_pdf_path.resolve():
        if stored_pdf_path.exists():
            if not force:
                raise FileExistsError(
                    f"Destination PDF '{stored_pdf_path}' already exists; use --force to overwrite"
                )
            stored_pdf_path.unlink()
        shutil.move(str(pdf_path), stored_pdf_path)

    return markdown_path, extracted_dir, stored_pdf_path


def render_page_images(pdf_path: Path, output_dir: Path, dpi: int) -> None:
    """Render each PDF page to PNG at the requested DPI."""
    zoom = max(dpi, 72) / 72.0
    matrix = fitz.Matrix(zoom, zoom)
    with fitz.open(pdf_path) as doc:
        for index, page in enumerate(doc, start=1):
            pix = page.get_pixmap(matrix=matrix, alpha=False)
            target = output_dir / f"page-{index:04d}.png"
            pix.save(target)


def should_skip_text(text: str, patterns: Sequence[re.Pattern[str]]) -> bool:
    """Return True if the text is empty or matches a configured skip pattern."""
    stripped = text.strip()
    if not stripped:
        return True
    for pattern in patterns:
        if pattern.search(stripped):
            return True
    return False


def collect_text_lines(pdf_path: Path, config: ExtractionConfig) -> List[str]:
    """Extract filtered text lines, dropping headers/footers and repeated noise."""
    pages: List[List[Tuple[str, str]]] = []
    header_counts: Counter[str] = Counter()
    footer_counts: Counter[str] = Counter()
    total_pages = 0

    for page_layout in extract_pages(pdf_path):
        total_pages += 1
        page_height = getattr(page_layout, "height", None)
        if page_height is None:
            # Fallback to default letter height if unavailable
            page_height = 792.0

        page_entries: List[Tuple[str, str]] = []
        for element in page_layout:
            if not isinstance(element, LTTextContainer):
                continue
            for line in element:
                if not isinstance(line, LTTextLine):
                    continue
                text = line.get_text().strip()
                if not text:
                    continue
                y_top = line.y1
                y_bottom = line.y0
                if page_height - y_top <= config.margin_top:
                    header_counts[text] += 1
                    page_entries.append((text, "header"))
                elif y_bottom <= config.margin_bottom:
                    footer_counts[text] += 1
                    page_entries.append((text, "footer"))
                else:
                    page_entries.append((text, "body"))
        pages.append(page_entries)

    min_repeating = config.min_repeating
    if min_repeating <= 0:
        min_repeating = max(2, total_pages // 3)
    header_drop = {text for text, count in header_counts.items() if count >= min_repeating}
    footer_drop = {text for text, count in footer_counts.items() if count >= min_repeating}

    output_lines: List[str] = []
    for page_index, entries in enumerate(pages, start=1):
        page_lines: List[str] = []
        for text, region in entries:
            if region == "header" and text in header_drop:
                continue
            if region == "footer" and text in footer_drop:
                continue
            if should_skip_text(text, config.skip_patterns):
                continue
            page_lines.append(text)
        if not page_lines:
            continue
        if output_lines and output_lines[-1] != "":
            output_lines.append("")
        output_lines.extend(page_lines)
    # Normalize consecutive blank lines
    normalized: List[str] = []
    for line in output_lines:
        if line == "" and normalized and normalized[-1] == "":
            continue
        normalized.append(line)
    if normalized and normalized[-1] != "":
        normalized.append("")
    return normalized


def write_markdown(markdown_path: Path, lines: Sequence[str]) -> None:
    """Write the collected Markdown lines to disk with UTF-8 encoding."""
    markdown_path.write_text("\n".join(lines), encoding="utf-8")


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    """Parse CLI options controlling PDF conversion behavior."""
    parser = argparse.ArgumentParser(description="Convert a PDF into Markdown with extracted page images")
    parser.add_argument("pdf", type=Path, help="Path to the PDF file")
    parser.add_argument("--dest", type=Path, help="Destination directory for the workspace (default: PDF parent)")
    parser.add_argument("--force", action="store_true", help="Overwrite existing workspace if present")
    parser.add_argument("--dpi", type=int, default=200, help="DPI for rendered page images (default: 200)")
    parser.add_argument(
        "--margin-top",
        type=float,
        default=36.0,
        help="Top margin in points considered header content (default: 36)",
    )
    parser.add_argument(
        "--margin-bottom",
        type=float,
        default=36.0,
        help="Bottom margin in points considered footer content (default: 36)",
    )
    parser.add_argument(
        "--min-repeat",
        type=int,
        default=0,
        help="Minimum page count occurrences before a header/footer line is dropped (default: auto)",
    )
    parser.add_argument(
        "--skip-pattern",
        action="append",
        dest="skip_patterns",
        help="Additional regex pattern of lines to skip (case-insensitive). Can be supplied multiple times.",
    )
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    """CLI entry point that converts a PDF into Markdown plus page images."""
    args = parse_args(argv)

    skip_sources = list(DEFAULT_SKIP_PATTERNS)
    if args.skip_patterns:
        skip_sources.extend(args.skip_patterns)

    try:
        skip_patterns = compile_skip_patterns(skip_sources)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    try:
        markdown_path, extracted_dir, stored_pdf_path = ensure_workspace(
            args.pdf.resolve(), args.dest, args.force
        )
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1

    config = ExtractionConfig(
        margin_top=max(args.margin_top, 0.0),
        margin_bottom=max(args.margin_bottom, 0.0),
        min_repeating=args.min_repeat,
        skip_patterns=skip_patterns,
    )

    try:
        lines = collect_text_lines(stored_pdf_path, config)
        write_markdown(markdown_path, lines)
    except Exception as exc:
        print(f"Text extraction failed: {exc}", file=sys.stderr)
        return 3

    try:
        render_page_images(stored_pdf_path, extracted_dir, args.dpi)
    except Exception as exc:
        print(f"Image rendering failed: {exc}", file=sys.stderr)
        return 4

    print(f"Markdown written to {markdown_path}")
    print(f"Page images saved under {extracted_dir}")
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
