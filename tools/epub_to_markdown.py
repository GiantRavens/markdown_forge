#!/usr/bin/env python3
"""Convert an EPUB workspace into cleaned Markdown with extracted images.

Steps performed:
- Ensure a book root folder exists (create via `epub_folderize` if starting from an EPUB file).
- Run pandoc to create `<Title>.md` in the book root and extract referenced images to `images/`.
- Copy the largest cover image into `images/` if pandoc omitted it.
- Clean the generated Markdown by stripping calibre-specific classes and attribute lists.

Usage:
    python tools/epub_to_markdown.py <book_root_or_epub_path> [--force]
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional
import xml.etree.ElementTree as ET

try:
    from epub_folderize import folderize_epub, read_epub_title, slugify
except ImportError:  # pragma: no cover - fallback if module path changes
    from tools.epub_folderize import folderize_epub, read_epub_title, slugify  # type: ignore


def ensure_pandoc_available() -> None:
    if shutil.which("pandoc") is None:
        raise RuntimeError("pandoc is required but not found on PATH")


def sanitize_filename(name: str) -> str:
    # Remove characters not allowed in file names on common filesystems
    forbidden = '<>:"/\\|?*'
    translated = ''.join('_' if ch in forbidden else ch for ch in name)
    return translated.strip() or "untitled"


def resolve_book_root(input_path: Path, force: bool) -> tuple[Path, Path]:
    """Return (book_root, epub_path) ensuring the source workspace exists."""
    if input_path.is_file():
        if input_path.suffix.lower() != ".epub":
            raise ValueError("Input file must be an .epub")
        title = read_epub_title(input_path) or input_path.stem
        folder_name = slugify(title, fallback=input_path.stem)
        parent = input_path.parent
        candidate_root = parent / folder_name
        if candidate_root.exists() and (candidate_root / "source" / "extracted").exists():
            book_root = candidate_root
        else:
            book_root = folderize_epub(input_path, parent, force)
        epub_in_source = next((candidate_root / "source").glob("*.epub"), None)
        if epub_in_source:
            epub_path = epub_in_source
        else:
            # After folderize the file has been moved; search again inside book_root
            epub_path = next((book_root / "source").glob("*.epub"), None)
            if epub_path is None:
                raise FileNotFoundError("Could not locate EPUB inside book root")
        return book_root, epub_path

    if input_path.is_dir():
        book_root = input_path
        source_dir = book_root / "source"
        extracted_dir = source_dir / "extracted"
        if not extracted_dir.exists():
            epub_candidates = list(source_dir.glob("*.epub"))
            if not epub_candidates:
                raise FileNotFoundError("No EPUB found in book_root/source; run epub_folderize first")
            folderize_epub(epub_candidates[0], book_root.parent, force)
            if not extracted_dir.exists():
                raise FileNotFoundError("Extraction directory missing after folderize")
        epub_path = next((source_dir / "").glob("*.epub"), None)
        if epub_path is None:
            epub_path = next(source_dir.glob("*.epub"), None)
        if epub_path is None:
            raise FileNotFoundError("Could not locate EPUB in source directory")
        return book_root, epub_path

    raise FileNotFoundError(f"Path '{input_path}' does not exist")


def clean_existing_targets(images_dir: Path, markdown_path: Path, force: bool) -> None:
    if images_dir.exists():
        if force:
            shutil.rmtree(images_dir)
        else:
            if any(images_dir.iterdir()):
                raise FileExistsError(f"Images directory '{images_dir}' already exists; use --force to overwrite")
            # empty directory can be reused
    if markdown_path.exists():
        if force:
            markdown_path.unlink()
        else:
            raise FileExistsError(f"Markdown file '{markdown_path}' already exists; use --force to overwrite")


def flatten_extracted_media(images_dir: Path) -> None:
    if not images_dir.exists():
        return
    while True:
        nested = images_dir / "images"
        if not nested.is_dir():
            break
        for item in list(nested.iterdir()):
            target = images_dir / item.name
            if target.exists():
                # Avoid clobbering existing files; skip duplicates
                continue
            shutil.move(str(item), target)
        if not any(nested.iterdir()):
            nested.rmdir()
        else:
            # If items remain (due to name collisions), stop looping to avoid infinite loop
            break


def run_pandoc(epub_path: Path, book_root: Path, markdown_filename: str) -> None:
    cmd = [
        "pandoc",
        str(epub_path),
        "--to",
        "markdown-simple_tables+pipe_tables+tex_math_dollars+superscript+subscript",
        "--wrap=none",
        "--markdown-headings=atx",
        "--extract-media=images",
        "--standalone",
        "-o",
        markdown_filename,
    ]
    completed = subprocess.run(cmd, cwd=str(book_root), capture_output=True, text=True)
    if completed.returncode != 0:
        raise RuntimeError(f"pandoc failed: {completed.stderr.strip() or completed.stdout.strip()}")


def strip_calibre_artifacts(markdown_text: str) -> str:
    # Remove attribute lists like {: .calibre1 }
    cleaned_lines = []
    attr_re = re.compile(r"\s*\{[^}]*\}")
    for line in markdown_text.splitlines():
        if "calibre" in line:
            line = attr_re.sub("", line)
        cleaned_lines.append(line)
    text = "\n".join(cleaned_lines)
    # Remove residual calibre span/div wrappers
    text = re.sub(r"<(/?)(span|div)[^>]*calibre[^>]*>", "", text, flags=re.IGNORECASE)
    # Collapse repeated blank lines
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = normalize_image_links(text)
    return text.strip() + "\n"


def normalize_image_links(text: str) -> str:
    text = re.sub(r"(?<=\()images/(?:images/)+", "images/", text)
    text = re.sub(r"(?<=[\"'])images/(?:images/)+", "images/", text)
    return text


def parse_opf_path(extracted_dir: Path) -> Optional[Path]:
    container = extracted_dir / "META-INF" / "container.xml"
    if not container.exists():
        return None
    try:
        root = ET.parse(container).getroot()
        ns = {"c": "urn:oasis:names:tc:opendocument:xmlns:container"}
        rootfile = root.find("c:rootfiles/c:rootfile", ns)
        if rootfile is None:
            return None
        full_path = rootfile.attrib.get("full-path") or rootfile.attrib.get("fullPath")
        if not full_path:
            return None
        opf_path = extracted_dir / full_path
        return opf_path
    except ET.ParseError:
        return None


def find_cover_candidates(opf_path: Path) -> list[Path]:
    candidates: list[Path] = []
    try:
        tree = ET.parse(opf_path)
    except ET.ParseError:
        return candidates
    root = tree.getroot()
    ns = {
        "opf": "http://www.idpf.org/2007/opf",
    }
    manifest = root.find("opf:manifest", ns)
    if manifest is None:
        return candidates
    for item in manifest.findall("opf:item", ns):
        href = item.attrib.get("href")
        if not href:
            continue
        props = item.attrib.get("properties", "")
        item_id = item.attrib.get("id", "")
        if "cover-image" in props or item_id.lower() == "cover" or "cover" in href.lower():
            candidate_path = (opf_path.parent / href).resolve()
            if candidate_path.exists():
                candidates.append(candidate_path)
    return candidates


def ensure_cover_in_images(extracted_dir: Path, images_dir: Path) -> None:
    opf_path = parse_opf_path(extracted_dir)
    if not opf_path:
        return
    candidates = find_cover_candidates(opf_path)
    if not candidates:
        return
    # choose the largest file by size
    cover_path = max(candidates, key=lambda p: p.stat().st_size)
    destination = images_dir / cover_path.name
    if destination.exists():
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(cover_path, destination)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Generate Markdown and images from an EPUB workspace")
    parser.add_argument("input_path", type=Path, help="Book root directory or EPUB file path")
    parser.add_argument("--force", action="store_true", help="Overwrite existing markdown/images outputs")
    args = parser.parse_args(argv)

    try:
        ensure_pandoc_available()
        book_root, epub_path = resolve_book_root(args.input_path.resolve(), args.force)
        title = read_epub_title(epub_path) or book_root.name
        markdown_filename = sanitize_filename(f"{title}.md")
        markdown_path = book_root / markdown_filename
        images_dir = book_root / "images"
        clean_existing_targets(images_dir, markdown_path, args.force)
        run_pandoc(epub_path, book_root, markdown_path.name)
        flatten_extracted_media(images_dir)
        # Pandoc created markdown and images; now clean the markdown content
        markdown_text = markdown_path.read_text(encoding="utf-8")
        cleaned = strip_calibre_artifacts(markdown_text)
        markdown_path.write_text(cleaned, encoding="utf-8")
        extracted_dir = book_root / "source" / "extracted"
        ensure_cover_in_images(extracted_dir, images_dir)
        print(f"Markdown written to {markdown_path}")
        print(f"Images available in {images_dir}")
        return 0
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
