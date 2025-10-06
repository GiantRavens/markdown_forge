#!/usr/bin/env python3
"""Batch-process EPUB and PDF files found in the `IN/` root workspace.

Part of the `markdown_forge` framework.

For each file in the top-level `IN/` directory:
- Run `filetype_inspect` to gather metadata/actions (logged to stdout).
- If the file is an EPUB, invoke `epub_to_markdown` followed by `epub_markdown_cleanup`.
- If the file is a PDF, invoke `pdf_to_markdown` followed by `pdf_markdown_cleanup`.

Usage:
    python tools/convert_IN_preprocess.py [--in-dir DIR] [--dry-run]

A dry run performs inspection only and prints the commands that would be
executed for conversion.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path
from typing import List, Optional, Sequence

REPO_ROOT = Path(__file__).resolve().parent.parent
TOOLS_DIR = REPO_ROOT / "tools"
DEFAULT_IN_DIR = REPO_ROOT / "IN"

FILETYPE_INSPECT = TOOLS_DIR / "filetype_inspect.py"
EPUB_TO_MARKDOWN = TOOLS_DIR / "epub_to_markdown.py"
EPUB_MARKDOWN_CLEANUP = TOOLS_DIR / "epub_markdown_cleanup.py"
PDF_TO_MARKDOWN = TOOLS_DIR / "pdf_to_markdown.py"
PDF_MARKDOWN_CLEANUP = TOOLS_DIR / "pdf_markdown_cleanup.py"

SUPPORTED_SUFFIXES = {".epub", ".pdf"}

MARKDOWN_PATH_RE = re.compile(r"Markdown written to\s+(?P<path>.+)")


def _resolve_output_path(raw: str) -> Optional[Path]:
    """Extract an absolute Markdown path from a tool's stdout snippet."""
    match = MARKDOWN_PATH_RE.search(raw)
    if not match:
        return None
    candidate = match.group("path").strip()
    path = Path(candidate)
    if not path.is_absolute():
        path = (REPO_ROOT / path).resolve()
    return path


def run_command(cmd: Sequence[str], dry_run: bool, *, capture: bool = False) -> tuple[int, str]:
    """Execute a subprocess, optionally only logging the command when dry running."""
    if dry_run:
        print("DRY-RUN:", " ".join(str(part) for part in cmd))
        return 0, ""
    if capture:
        proc = subprocess.run(cmd, cwd=str(REPO_ROOT), text=True, capture_output=True)
        if proc.stdout:
            print(proc.stdout, end="")
        if proc.stderr:
            print(proc.stderr, end="", file=sys.stderr)
        if proc.returncode != 0:
            print(f"Command failed ({proc.returncode}):", " ".join(str(part) for part in cmd))
        return proc.returncode, proc.stdout
    proc = subprocess.run(cmd, cwd=str(REPO_ROOT))
    if proc.returncode != 0:
        print(f"Command failed ({proc.returncode}):", " ".join(str(part) for part in cmd))
    return proc.returncode, ""


def locate_generated_markdown(book_root: Path) -> Optional[Path]:
    """Return the first Markdown file within a derived publication workspace."""
    candidates = sorted(book_root.glob("*.md"))
    return candidates[0] if candidates else None


def inspect_file(path: Path, dry_run: bool) -> int:
    """Invoke `filetype_inspect` for a given candidate path."""
    cmd = ["python", str(FILETYPE_INSPECT), str(path)]
    print("-- Inspecting:", path)
    return run_command(cmd, dry_run=dry_run)[0]


def handle_epub(path: Path, dry_run: bool) -> None:
    """Convert an EPUB to Markdown and trigger EPUB-specific cleanup."""
    print("-- Processing EPUB:", path)
    cmd = ["python", str(EPUB_TO_MARKDOWN), str(path)]
    result, stdout = run_command(cmd, dry_run, capture=True)
    if result != 0:
        print("Aborting EPUB pipeline due to failure.")
        return

    if dry_run:
        print("DRY-RUN: Would locate generated Markdown and run epub_markdown_cleanup")
        return

    markdown_path = _resolve_output_path(stdout)
    if not markdown_path:
        print("Warning: Could not determine Markdown output for", path)
        # Fallback to first markdown in presumed workspace
        book_root = path.parent / path.stem
        markdown_path = locate_generated_markdown(book_root)
    if not markdown_path:
        print("Warning: No Markdown file found for", path)
        return

    cleanup_cmd = ["python", str(EPUB_MARKDOWN_CLEANUP), str(markdown_path)]
    run_command(cleanup_cmd, dry_run, capture=True)


def handle_pdf(path: Path, dry_run: bool) -> None:
    """Convert a PDF to Markdown and trigger PDF-specific cleanup."""
    print("-- Processing PDF:", path)
    cmd = ["python", str(PDF_TO_MARKDOWN), str(path)]
    result, stdout = run_command(cmd, dry_run, capture=True)
    if result != 0:
        print("Aborting PDF pipeline due to failure.")
        return

    if dry_run:
        print("DRY-RUN: Would locate generated Markdown and run pdf_markdown_cleanup")
        return

    markdown_path = _resolve_output_path(stdout)
    if not markdown_path:
        book_root = path.parent / path.stem
        markdown_path = locate_generated_markdown(book_root)
    if not markdown_path:
        print("Warning: No Markdown file found for", path)
        return

    cleanup_cmd = ["python", str(PDF_MARKDOWN_CLEANUP), str(markdown_path)]
    run_command(cleanup_cmd, dry_run, capture=True)


def process_directory(in_dir: Path, dry_run: bool) -> None:
    """Iterate the IN/ directory and dispatch EPUB/PDF files through the pipeline."""
    if not in_dir.exists() or not in_dir.is_dir():
        raise FileNotFoundError(f"IN directory '{in_dir}' does not exist")

    candidates = sorted(item for item in in_dir.iterdir() if item.suffix.lower() in SUPPORTED_SUFFIXES)
    if not candidates:
        print("No EPUB or PDF files found in", in_dir)
        return

    for item in candidates:
        inspect_file(item, dry_run=False)
        if item.suffix.lower() == ".epub":
            handle_epub(item, dry_run)
        elif item.suffix.lower() == ".pdf":
            handle_pdf(item, dry_run)


def parse_args(argv: List[str] | None = None) -> argparse.Namespace:
    """Configure CLI options for bulk preprocessing of the `IN/` directory."""
    parser = argparse.ArgumentParser(description="Convert EPUB/PDF files in IN/ using the preprocessing pipeline")
    parser.add_argument("--in-dir", type=Path, default=DEFAULT_IN_DIR, help="Override the IN/ directory root")
    parser.add_argument("--dry-run", action="store_true", help="Inspect only and print planned commands")
    return parser.parse_args(argv)


def main(argv: List[str] | None = None) -> int:
    """CLI entry point that orchestrates scanning and conversion of `IN/`."""
    args = parse_args(argv)
    try:
        process_directory(args.in_dir.resolve(), args.dry_run)
    except Exception as exc:
        print(f"Failed: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
