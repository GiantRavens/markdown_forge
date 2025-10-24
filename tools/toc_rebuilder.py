#!/usr/bin/env python3
"""Rebuild the `## TABLE OF CONTENTS` section in Markdown files.

Given a Markdown file, this tool locates (or inserts) the `## TABLE OF CONTENTS`
section and populates it with links to every H2 heading in the document.
"""

from __future__ import annotations

import argparse
import re
import sys
import unicodedata
from pathlib import Path
from typing import Iterable, List, Tuple


def parse_args(argv: List[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Rebuild TABLE OF CONTENTS for Markdown H2 headings")
    parser.add_argument("markdown_path", type=Path, help="Path to the Markdown file to update")
    parser.add_argument("--dry-run", action="store_true", help="Report actions without writing changes")
    return parser.parse_args(argv)


def load_lines(path: Path) -> Tuple[List[str], bool]:
    text = path.read_text(encoding="utf-8")
    has_trailing_newline = text.endswith("\n")
    # splitlines without keepends to simplify editing
    return text.splitlines(), has_trailing_newline


def slugify(text: str, *, seen: dict[str, int]) -> str:
    normalized = unicodedata.normalize("NFKD", text)
    normalized = "".join(char for char in normalized if not unicodedata.combining(char))
    normalized = normalized.lower().strip()
    normalized = re.sub(r"[^a-z0-9\s-]", "", normalized)
    normalized = re.sub(r"\s+", "-", normalized)
    normalized = re.sub(r"-+", "-", normalized)
    slug = normalized.strip("-") or "section"

    count = seen.get(slug, 0)
    seen[slug] = count + 1
    if count:
        slug = f"{slug}-{count}"
    return slug


def collect_h2_headings(lines: Iterable[str]) -> List[str]:
    headings: List[str] = []
    for line in lines:
        if not line.startswith("## "):
            continue
        title = line[3:].strip()
        if title.upper() == "TABLE OF CONTENTS":
            continue
        headings.append(title)
    return headings


def build_toc_block(headings: List[str]) -> List[str]:
    block: List[str] = ["## TABLE OF CONTENTS"]
    block.append("")
    if headings:
        seen: dict[str, int] = {}
        for heading in headings:
            slug = slugify(heading, seen=seen)
            block.append(f"- [{heading}](#{slug})")
        block.append("")
    return block


def find_existing_toc(lines: List[str]) -> Tuple[int | None, int | None]:
    toc_start = None
    for idx, line in enumerate(lines):
        if line.strip().lower() == "## table of contents":
            toc_start = idx
            break
    if toc_start is None:
        return None, None

    toc_end = len(lines)
    for idx in range(toc_start + 1, len(lines)):
        candidate = lines[idx]
        if candidate.startswith("## ") or candidate.startswith("# "):
            toc_end = idx
            break
    return toc_start, toc_end


def determine_insertion_index(lines: List[str]) -> int:
    if lines and lines[0].strip() == "---":
        for idx in range(1, len(lines)):
            if lines[idx].strip() == "---":
                return min(idx + 1, len(lines))
    for idx, line in enumerate(lines):
        if line.startswith("# "):
            return idx + 1
    return 0


def rebuild_toc(lines: List[str]) -> Tuple[List[str], bool]:
    headings = collect_h2_headings(lines)
    toc_lines = build_toc_block(headings)

    existing_start, existing_end = find_existing_toc(lines)

    if existing_start is not None:
        new_lines = lines[:existing_start] + toc_lines + lines[existing_end:]
    else:
        insert_at = determine_insertion_index(lines)
        # Ensure a blank line above the TOC for readability when inserting newly
        needs_blank_before = insert_at > 0 and lines[insert_at - 1].strip() != ""
        prefix = lines[:insert_at]
        suffix = lines[insert_at:]
        if needs_blank_before:
            toc_lines = [""] + toc_lines
        if suffix and suffix[0].strip() != "":
            toc_lines = toc_lines + [""]
        new_lines = prefix + toc_lines + suffix

    changed = new_lines != lines
    return new_lines, changed


def write_lines(path: Path, lines: List[str], has_trailing_newline: bool) -> None:
    text = "\n".join(lines)
    if has_trailing_newline or not text.endswith("\n"):
        text += "\n"
    path.write_text(text, encoding="utf-8")


def main(argv: List[str] | None = None) -> int:
    args = parse_args(argv)
    target = args.markdown_path.resolve()

    if not target.exists():
        print(f"Error: {target} does not exist", file=sys.stderr)
        return 1
    if not target.is_file():
        print(f"Error: {target} is not a file", file=sys.stderr)
        return 1

    lines, had_trailing_newline = load_lines(target)
    updated_lines, changed = rebuild_toc(lines)

    if not changed:
        print(f"No changes needed for {target}")
        return 0

    if args.dry_run:
        print(f"TOC would be updated for {target}")
        return 0

    write_lines(target, updated_lines, had_trailing_newline)
    print(f"Updated TABLE OF CONTENTS in {target}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
