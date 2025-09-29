#!/usr/bin/env python3
"""Organize an EPUB into a titled workspace and unpack its contents.

For a given EPUB this tool:
- Determines a folder name based on the EPUB title metadata (fallback to filename)
- Creates `<dest>/<title>/source/`
- Moves the EPUB file into the `source/` directory
- Extracts the EPUB archive into `<dest>/<title>/source/extracted/`

Usage:
    python tools/epub_folderize.py path/to/book.epub [--dest DIR] [--force]
"""

from __future__ import annotations

import argparse
import shutil
import unicodedata
import zipfile
from pathlib import Path
from typing import Optional
import xml.etree.ElementTree as ET

DC_NS = "http://purl.org/dc/elements/1.1/"
CONTAINER_NS = "urn:oasis:names:tc:opendocument:xmlns:container"

def read_epub_title(epub_path: Path) -> Optional[str]:
    try:
        with zipfile.ZipFile(epub_path) as zf:
            container_xml = zf.read("META-INF/container.xml")
            container_root = ET.fromstring(container_xml)
            rootfile_el = container_root.find(
                "{CONTAINER_NS}rootfiles/{CONTAINER_NS}rootfile".format(CONTAINER_NS="{" + CONTAINER_NS + "}")
            )
            if rootfile_el is None:
                return None
            full_path = rootfile_el.attrib.get("full-path") or rootfile_el.attrib.get("fullPath")
            if not full_path:
                return None
            opf_data = zf.read(full_path)
            opf_root = ET.fromstring(opf_data)
            title_el = opf_root.find(".//{{{dc}}}title".format(dc=DC_NS))
            if title_el is not None and title_el.text:
                return title_el.text.strip()
    except (KeyError, zipfile.BadZipFile, ET.ParseError):
        return None
    return None

def slugify(text: str, fallback: str) -> str:
    normalized = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    cleaned = "".join(ch if ch.isalnum() or ch in (" ", "-", "_") else " " for ch in normalized)
    slug = "-".join(part for part in cleaned.strip().split() if part)
    return slug or fallback

def prepare_destination(epub_path: Path, dest_root: Path, title: Optional[str], force: bool) -> Path:
    fallback_name = epub_path.stem
    folder_name = slugify(title or fallback_name, fallback=fallback_name)
    target_dir = dest_root / folder_name
    if target_dir.exists():
        if not force:
            raise FileExistsError(f"Destination '{target_dir}' already exists. Use --force to replace it.")
        shutil.rmtree(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    (target_dir / "source").mkdir(exist_ok=True)
    return target_dir

def move_original(epub_path: Path, dest_dir: Path) -> Path:
    source_dir = dest_dir / "source"
    source_dir.mkdir(exist_ok=True)
    target_path = source_dir / epub_path.name
    shutil.move(str(epub_path), target_path)
    return target_path

def extract_epub(epub_path: Path, dest_dir: Path) -> Path:
    extract_dir = dest_dir / "source" / "extracted"
    extract_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(epub_path) as zf:
        zf.extractall(extract_dir)
    return extract_dir

def folderize_epub(epub_path: Path, dest_root: Path, force: bool) -> Path:
    if not epub_path.exists():
        raise FileNotFoundError(epub_path)
    if not epub_path.is_file():
        raise ValueError(f"Path '{epub_path}' is not a file")
    title = read_epub_title(epub_path)
    dest_dir = prepare_destination(epub_path, dest_root, title, force)
    moved_path = move_original(epub_path, dest_dir)
    extract_epub(moved_path, dest_dir)
    return dest_dir

def main() -> int:
    parser = argparse.ArgumentParser(description="Organize an EPUB and unpack its contents")
    parser.add_argument("epub", type=Path, help="Path to the EPUB file")
    parser.add_argument("--dest", type=Path, default=None, help="Destination directory (default: EPUB parent)")
    parser.add_argument("--force", action="store_true", help="Overwrite existing destination folder if present")
    args = parser.parse_args()

    epub_path = args.epub.resolve()
    dest_root = args.dest.resolve() if args.dest else epub_path.parent

    try:
        dest_dir = folderize_epub(epub_path, dest_root, args.force)
    except Exception as exc:
        print(f"Error: {exc}")
        return 1

    print(f"Created folderized EPUB at {dest_dir}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
