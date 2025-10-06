#!/usr/bin/env python3
"""Create a publication workspace from an Acrobat HTML export.

Part of the `markdown_forge` framework.

Workflow:
1. Read the supplied Acrobat-generated HTML file and extract its `<title>`.
2. Create a new publication directory named after the title (slugified for safety).
3. Move the HTML file, its sibling asset folder, and any matching PDFs into the new workspace.
4. Invoke pandoc on the relocated HTML to produce Markdown and extract referenced images.

Usage::

    python tools/acrobat-html_to_markdown.py /path/to/export.html [--dest DIR] [--force]

The script assumes the Acrobat export produced a directory next to the HTML file
whose name matches the HTML stem. Any PDF files beginning with the same stem are
also relocated into the publication workspace.
"""

from __future__ import annotations

import argparse
import html
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional, Sequence
from urllib.parse import unquote

try:  # Prefer local import when executed from repo root
    from epub_folderize import slugify
except ImportError:  # pragma: no cover - fallback to package-style import
    from tools.epub_folderize import slugify  # type: ignore

try:
    from epub_to_markdown import sanitize_filename
except ImportError:  # pragma: no cover - fallback to package-style import
    from tools.epub_to_markdown import sanitize_filename  # type: ignore

try:
    from bs4 import BeautifulSoup  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    BeautifulSoup = None  # type: ignore

HTML_EXTENSIONS = {".html", ".htm"}


class PandocError(RuntimeError):
    """Raised when pandoc fails to convert the source HTML."""


def ensure_pandoc_available() -> None:
    """Verify that `pandoc` is available on PATH before running conversions."""
    if shutil.which("pandoc") is None:
        raise RuntimeError("pandoc is required but was not found on PATH")


def extract_title(html_path: Path) -> Optional[str]:
    """Read the HTML file and try to extract a human-friendly document title."""
    try:
        raw = html_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        raw = html_path.read_text(encoding="utf-8", errors="ignore")

    if BeautifulSoup is not None:
        soup = BeautifulSoup(raw, "html.parser")
        if soup.title and soup.title.string:
            candidate = soup.title.string.strip()
            if candidate:
                return candidate

    match = re.search(r"<title>(.*?)</title>", raw, flags=re.IGNORECASE | re.DOTALL)
    if match:
        title = html.unescape(match.group(1)).strip()
        if title:
            return title
    return None


def move_path(source: Path, destination_dir: Path) -> Path:
    """Move a file or directory into `destination_dir`, returning the new path."""
    target = destination_dir / source.name
    shutil.move(str(source), str(target))
    return target


def collect_pdf_candidates(html_path: Path) -> list[Path]:
    """Return sibling PDF files whose names share the HTML stem."""
    base = html_path.stem
    parent = html_path.parent
    pattern = f"{base}*.pdf"
    return sorted(candidate for candidate in parent.glob(pattern) if candidate.is_file())


def find_asset_folder(html_path: Path) -> Path:
    """Locate the Acrobat export asset directory adjacent to the HTML file."""
    parent = html_path.parent
    stem = html_path.stem
    direct = parent / stem
    if direct.is_dir():
        return direct

    suffixes = ["_files", "-files", " files"]
    for suffix in suffixes:
        candidate = parent / f"{stem}{suffix}"
        if candidate.is_dir():
            return candidate

    stem_lower = stem.lower()
    for candidate in parent.iterdir():
        if not candidate.is_dir():
            continue
        name_lower = candidate.name.lower()
        if name_lower.startswith(stem_lower) and name_lower.endswith("files"):
            return candidate

    attempted = [direct] + [parent / f"{stem}{suffix}" for suffix in suffixes]
    attempted_names = ", ".join(str(path.name) for path in attempted)
    raise FileNotFoundError(
        "Could not locate asset folder for Acrobat export; tried: " + attempted_names
    )


def run_pandoc(html_path: Path, publication_dir: Path, markdown_filename: str) -> None:
    """Invoke pandoc on the relocated HTML and write Markdown plus extracted media."""
    cmd = [
        "pandoc",
        str(html_path),
        "--from",
        "html",
        "--to",
        "markdown-simple_tables+pipe_tables+tex_math_dollars+superscript+subscript",
        "--wrap=none",
        "--markdown-headings=atx",
        "--extract-media=images",
        "-o",
        markdown_filename,
    ]
    completed = subprocess.run(cmd, cwd=str(publication_dir), capture_output=True, text=True)
    if completed.returncode != 0:
        message = completed.stderr.strip() or completed.stdout.strip() or "pandoc failed"
        raise PandocError(message)


def flatten_images(images_dir: Path) -> None:
    """Collapse nested image directories into a single level, ensuring unique filenames."""
    if not images_dir.exists():
        return

    nested_files = [p for p in images_dir.rglob("*") if p.is_file() and p.parent != images_dir]
    for file_path in nested_files:
        target = images_dir / file_path.name
        if target.exists():
            suffix = 1
            stem = file_path.stem
            while target.exists():
                target = images_dir / f"{stem}-{suffix}{file_path.suffix}"
                suffix += 1
        file_path.rename(target)

    for dir_path in sorted(images_dir.rglob("*"), reverse=True):
        if dir_path.is_dir():
            try:
                dir_path.rmdir()
            except OSError:
                pass


def rewrite_markdown_images(markdown_path: Path, images_dir: Path, source_dir: Path) -> None:
    """Rewrite proprietary image directives into local Markdown image links."""
    if not markdown_path.exists():
        return

    text = markdown_path.read_text(encoding="utf-8")

    pattern = re.compile(
        r"\[image\]\{[^}]*?original-image-src=\"([^\"]+)\"[^}]*\}", re.IGNORECASE
    )

    if not pattern.search(text):
        return

    copied: dict[str, str] = {}

    def resolve_source(relative: str) -> Optional[Path]:
        decoded = unquote(relative)
        rel_path = Path(*decoded.split("/"))
        candidate = (source_dir / rel_path).resolve()
        try:
            candidate.relative_to(source_dir.resolve())
        except ValueError:
            return None
        if candidate.exists() and candidate.is_file():
            return candidate
        return None

    def ensure_copied(source_file: Path) -> str:
        key = str(source_file)
        if key in copied:
            return copied[key]
        images_dir.mkdir(parents=True, exist_ok=True)
        target = images_dir / source_file.name
        if target.exists():
            stem = target.stem
            suffix = 1
            while target.exists():
                target = images_dir / f"{stem}-{suffix}{target.suffix}"
                suffix += 1
        shutil.copy2(source_file, target)
        relative = f"images/{target.name}"
        copied[key] = relative
        return relative

    def replacement(match: re.Match[str]) -> str:
        raw_src = match.group(1)
        source_file = resolve_source(raw_src)
        if not source_file:
            return ""
        rel_path = ensure_copied(source_file)
        return f"![image]({rel_path})"

    new_text = pattern.sub(replacement, text)
    if new_text != text:
        markdown_path.write_text(new_text, encoding="utf-8")


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    """Build and parse CLI arguments for the Acrobat HTML conversion tool."""
    parser = argparse.ArgumentParser(
        description="Convert an Acrobat HTML export into a Markdown workspace"
    )
    parser.add_argument("html_file", type=Path, help="Path to the Acrobat-generated HTML file")
    parser.add_argument(
        "--dest",
        type=Path,
        help="Destination directory for the publication workspace (default: HTML parent)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing publication workspace if present",
    )
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Entry point for converting an Acrobat HTML export into a publication workspace."""
    args = parse_args(argv)

    try:
        ensure_pandoc_available()

        html_path = args.html_file.resolve()
        if not html_path.exists():
            raise FileNotFoundError(f"HTML file '{html_path}' does not exist")
        if not html_path.is_file():
            raise ValueError(f"Path '{html_path}' is not a file")
        if html_path.suffix.lower() not in HTML_EXTENSIONS:
            raise ValueError("Input file must have a .html or .htm extension")

        asset_folder = find_asset_folder(html_path)

        pdf_candidates = collect_pdf_candidates(html_path)

        title = extract_title(html_path) or html_path.stem
        slug = slugify(title, fallback=html_path.stem)
        dest_root = args.dest.resolve() if args.dest else html_path.parent
        publication_dir = dest_root / slug

        if publication_dir.exists():
            if args.force:
                shutil.rmtree(publication_dir)
            else:
                raise FileExistsError(
                    f"Destination '{publication_dir}' already exists; use --force to overwrite"
                )
        publication_dir.mkdir(parents=True, exist_ok=True)
        source_dir = publication_dir / "source"
        source_dir.mkdir(parents=True, exist_ok=True)

        relocated_html = move_path(html_path, source_dir)
        relocated_folder = move_path(asset_folder, source_dir)
        relocated_pdfs = [move_path(pdf, source_dir) for pdf in pdf_candidates]

        markdown_filename = sanitize_filename(f"{title}.md")
        markdown_path = publication_dir / markdown_filename
        if markdown_path.exists():
            if args.force:
                markdown_path.unlink()
            else:
                raise FileExistsError(
                    f"Markdown file '{markdown_path}' already exists; use --force to overwrite"
                )

        run_pandoc(relocated_html, publication_dir, markdown_filename)

        images_dir = publication_dir / "images"
        if not images_dir.exists():
            images_dir.mkdir(parents=True, exist_ok=True)
        flatten_images(images_dir)
        rewrite_markdown_images(markdown_path, images_dir, source_dir)

        print(f"Created publication workspace: {publication_dir}")
        print(f"Markdown written to: {markdown_path}")
        print(f"Source assets stored under: {source_dir}")
        print(f"Moved HTML file to: {relocated_html}")
        print(f"Moved asset folder to: {relocated_folder}")
        if relocated_pdfs:
            print(
                "Moved PDF files:" ,
                ", ".join(str(pdf) for pdf in relocated_pdfs),
            )
        if images_dir.exists():
            print(f"Images extracted under: {images_dir}")
        return 0
    except PandocError as exc:
        print(f"pandoc error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # pragma: no cover - defensive CLI guard
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
