#!/usr/bin/env python3
"""Post-processing utility for publication folders.

This script inspects the primary Markdown file within a publication directory,
extracts normalized metadata (title, title_short, author, publisher, year,
ISBN), and renames the directory itself along with key publication exports
(.md, .html, .epub). It is intended to run after `markdown_cleanup.py` and the
conversion scripts so that front matter is already enriched.
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

TITLE_SHORT_PATTERN = re.compile(r"\s*[-—–:].*$")
ISBN_NORMALIZE_PATTERN = re.compile(r"[^0-9Xx]")


def flatten_redundant_asset_dirs(base_dir: Path, dry_run: bool) -> None:
    for entry in base_dir.iterdir():
        if not entry.is_dir():
            continue
        flatten_redundant_asset_dirs(entry, dry_run)
        child = entry / entry.name
        if not child.is_dir():
            continue
        nested_images = child.name.lower() == "images"
        for item in child.iterdir():
            target = entry / item.name
            if dry_run:
                dest = entry if nested_images else child
                print(f"ASSET {item} -> {target if nested_images else dest}")
                continue
            if nested_images:
                if target.exists():
                    print(f"Skipping move '{item}' -> '{target}': target exists", file=sys.stderr)
                    continue
                shutil.move(str(item), target)
            else:
                inner_target = child / item.name
                if inner_target.exists():
                    continue
                shutil.move(str(item), inner_target)
        if not any(child.iterdir()):
            if not dry_run:
                child.rmdir()


@dataclass
class PublicationMetadata:
    title: str
    title_short: str
    author: str
    publisher: str | None
    year: str | None
    isbn: str | None


def load_markdown_metadata(markdown_path: Path) -> PublicationMetadata | None:
    text = markdown_path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return None

    lines = text.splitlines()
    front_matter: list[str] = []
    terminator_index: int | None = None
    for idx in range(1, len(lines)):
        if lines[idx].strip() == "---":
            terminator_index = idx
            break
        front_matter.append(lines[idx])

    if terminator_index is None:
        return None

    mapping: dict[str, str | list[str]] = {}
    current_key: str | None = None
    for raw_line in front_matter:
        if raw_line.strip().startswith("- ") and current_key:
            mapping.setdefault(current_key, [])
            if isinstance(mapping[current_key], list):
                mapping[current_key].append(raw_line.strip()[2:].strip())
            continue
        if ":" not in raw_line:
            continue
        key_part, value_part = raw_line.split(":", 1)
        key = key_part.strip().lower()
        value = value_part.strip()
        current_key = key
        if value:
            if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
                value = value[1:-1]
            mapping[key] = value
        else:
            mapping[key] = []

    title = str(mapping.get("title") or "").strip()
    if not title:
        return None

    title_short_raw = mapping.get("title_short") or title
    if isinstance(title_short_raw, list):
        title_short_candidate = " ".join(item.strip() for item in title_short_raw if item.strip())
    else:
        title_short_candidate = str(title_short_raw or "").strip()
    title_short = TITLE_SHORT_PATTERN.sub("", title_short_candidate).strip() or title

    author_raw = mapping.get("author")
    if isinstance(author_raw, list):
        author = ", ".join(item.strip() for item in author_raw if item.strip())
    else:
        author = str(author_raw or "").strip()
    if not author:
        return None

    publisher_raw = mapping.get("publisher")
    if isinstance(publisher_raw, list):
        publisher = ", ".join(item.strip() for item in publisher_raw if item.strip())
    else:
        publisher = str(publisher_raw or "").strip()
    if not publisher:
        publisher = None

    date_raw = str(mapping.get("date") or "").strip()
    year: str | None = None
    if date_raw:
        match = re.search(r"(19|20)\d{2}", date_raw)
        if match:
            year = match.group(0)

    isbn_raw = mapping.get("isbn")
    isbn: str | None = None
    if isinstance(isbn_raw, list):
        for item in isbn_raw:
            candidate = ISBN_NORMALIZE_PATTERN.sub("", str(item))
            if len(candidate) in {10, 13}:
                isbn = candidate.upper()
                break
    elif isinstance(isbn_raw, str):
        candidate = ISBN_NORMALIZE_PATTERN.sub("", isbn_raw)
        if len(candidate) in {10, 13}:
            isbn = candidate.upper()

    return PublicationMetadata(
        title=title,
        title_short=TITLE_SHORT_PATTERN.sub("", title_short).strip() or title,
        author=author,
        publisher=publisher,
        year=year,
        isbn=isbn,
    )


def build_basename(meta: PublicationMetadata) -> str:
    parts = [meta.title_short or meta.title, "by", meta.author]
    tail = []
    if meta.publisher:
        tail.append(meta.publisher)
    if meta.year:
        tail.append(meta.year)
    if tail:
        parts.append("- " + " ".join(tail))
    name = " ".join(part for part in parts if part)
    return re.sub(r"[\\/:*?\"<>|]+", "", name).strip()


def build_filename(meta: PublicationMetadata, extension: str) -> str:
    suffix_parts = []
    if meta.isbn:
        suffix_parts.append(f"ISBN {meta.isbn}")
    suffix = " ".join(suffix_parts)
    base = build_basename(meta)
    return f"{base} {suffix}.{extension}" if suffix else f"{base}.{extension}"


def rename_publication_artifacts(publication_dir: Path, meta: PublicationMetadata, dry_run: bool) -> Path:
    exports = list(publication_dir.glob("*"))
    new_dir_name = build_basename(meta)
    if not new_dir_name:
        raise ValueError("Failed to compute new directory name")

    if publication_dir.name != new_dir_name:
        target_dir = publication_dir.parent / new_dir_name
        if target_dir.exists() and target_dir != publication_dir:
            raise FileExistsError(f"Target directory '{target_dir}' already exists")
        if dry_run:
            print(f"DIR {publication_dir} -> {target_dir}")
        else:
            publication_dir.rename(target_dir)
            publication_dir = target_dir
            exports = list(publication_dir.glob("*"))

    for path in exports:
        if path.is_dir():
            continue
        if path.suffix.lower() not in {".md", ".html", ".epub"}:
            continue
        new_name = build_filename(meta, path.suffix.lstrip("."))
        new_path = path.with_name(new_name)
        if new_path == path:
            continue
        if new_path.exists():
            raise FileExistsError(f"Cannot rename '{path}' to '{new_path}': target exists")
        if dry_run:
            print(f"FILE {path.name} -> {new_name}")
        else:
            path.rename(new_path)
    return publication_dir


def move_to_out_directory(publication_dir: Path, dry_run: bool) -> Path:
    resolved_dir = publication_dir.resolve()
    base_dir = resolved_dir.parent

    out_root: Path | None = None
    parts = list(resolved_dir.parts)
    for idx in range(len(parts) - 1, -1, -1):
        if parts[idx].lower() == "in" and idx > 0:
            out_root = Path(*parts[:idx]) / "OUT"
            break
    if out_root is None:
        out_root = base_dir.parent / "OUT"

    if not out_root.exists() and not dry_run:
        out_root.mkdir(parents=True, exist_ok=True)

    destination = out_root / resolved_dir.name
    if destination.exists():
        raise FileExistsError(f"Target directory '{destination}' already exists")

    if dry_run:
        print(f"MOVE {resolved_dir} -> {destination}")
        source_candidate = resolved_dir / "source"
        if source_candidate.exists():
            print(f"REMOVE {destination / 'source'}")
        return publication_dir

    publication_dir.rename(destination)
    source_destination = destination / "source"
    if source_destination.exists():
        shutil.rmtree(source_destination)

    return destination


def find_primary_markdown(publication_dir: Path) -> Optional[Path]:
    candidates = sorted(publication_dir.glob("*.md"))
    if not candidates:
        return None
    return candidates[0]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Normalize publication metadata and rename artifacts")
    parser.add_argument("publication_dir", type=Path, help="Path to the publication directory")
    parser.add_argument("--dry-run", action="store_true", help="Preview changes without renaming")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    publication_dir: Path = args.publication_dir

    if not publication_dir.exists() or not publication_dir.is_dir():
        print(f"Directory '{publication_dir}' does not exist", file=sys.stderr)
        return 1

    markdown_path = find_primary_markdown(publication_dir)
    if markdown_path is None:
        print(f"No Markdown file found inside '{publication_dir}'", file=sys.stderr)
        return 1

    metadata = load_markdown_metadata(markdown_path)
    if metadata is None:
        print(f"Unable to parse metadata from '{markdown_path}'", file=sys.stderr)
        return 2

    flatten_redundant_asset_dirs(publication_dir, args.dry_run)

    try:
        publication_dir = rename_publication_artifacts(publication_dir, metadata, args.dry_run)
        publication_dir = move_to_out_directory(publication_dir, args.dry_run)
    except (FileExistsError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 3

    if args.dry_run:
        print("Dry run complete")
    else:
        print("Publication artifacts renamed successfully")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

