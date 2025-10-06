#!/usr/bin/env python3
"""Remove Acrobat-specific artifacts from Markdown.

Part of the `markdown_forge` framework.

Usage::

    python tools/acrobat-pdf-markdown_cleanup.py path/to/file.md [--dry-run]

The tool removes inline `{...}` segments, escaped quote sequences (e.g. `\"`),
internal-only link wrappers, and markers like `\<return>` that linger after
Acrobat HTML exports. Additional cleanup passes can be layered on in future
revisions.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Iterable, Sequence

BRACE_BLOCK_RE = re.compile(r"\s*\{[^{}]*\}")
ESCAPED_QUOTE_RE = re.compile(r"\\(['\"])" )
ESCAPED_RETURN_RE = re.compile(r"\\<\s*return\s*>", re.IGNORECASE)
INTERNAL_LINK_RE = re.compile(r"(?<!!)\[([^\]]+)\]\(([^)]+)\)")
INTERNAL_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")
FOOTNOTE_DEF_RE = re.compile(r"^\s*\[[^\]]+\]:")
EMPTY_BRACKETS_RE = re.compile(r"(?<!!)\[\s*\]")
ZERO_WIDTH_RE = re.compile(r"[\u200b\u200c\u200d\u2060]")
TRIPLE_DASH_RE = re.compile(r"(?<!-)---(?!-)")
YEAR_RE = re.compile(r"(19|20)\d{2}")
DATE_RE = re.compile(r"(19|20)\d{2}(?:[-/](0[1-9]|1[0-2])(?:[-/](0[1-9]|[12]\d|3[01]))?)")
ISBN_RE = re.compile(r"\bISBN(?:-1[03])?[:\s]*([0-9Xx-]{10,17})")
GENERIC_ID_RE = re.compile(r"\b(?:ISBN|ISSN|ASIN|URN|UUID|LOC|LCCN)[:\s]*([A-Za-z0-9-]+)\b")
AUTHOR_LINE_RE = re.compile(r"^\s*(?:by|author[:\s]+)(.+)$", re.IGNORECASE)
PUBLISHER_RE = re.compile(r"^\s*(?:published\s+by|publisher[:\s]+)(.+)$", re.IGNORECASE)


def strip_brace_blocks(lines: Iterable[str]) -> list[str]:
    """Remove one-line `{...}` segments that Acrobat inserts around spans."""
    cleaned: list[str] = []
    for line in lines:
        cleaned_line = BRACE_BLOCK_RE.sub("", line)
        cleaned.append(cleaned_line.rstrip())
    return cleaned


def remove_escaped_sequences(text: str) -> str:
    """Unescape inline quote markers and drop explicit `<return>` placeholders."""
    text = ESCAPED_QUOTE_RE.sub(r"\1", text)
    text = ESCAPED_RETURN_RE.sub("", text)
    return text


def drop_stray_backslash_lines(text: str) -> str:
    """Strip standalone `\` lines that Acrobat sometimes emits."""
    lines = [line for line in text.splitlines() if line.strip() != "\\"]
    return "\n".join(lines)


def extract_frontmatter_metadata(text: str, markdown_path: Path | None = None) -> dict[str, object]:
    """Pull identifiers, authorship, and date hints from cleaned Markdown/HTML."""
    lines = text.splitlines()
    metadata: dict[str, object] = {}
    identifiers: set[str] = set()
    title: str | None = None
    subtitle: str | None = None
    for idx, line in enumerate(lines[:200]):
        stripped = line.strip()
        if not stripped:
            continue
        if not title and stripped.startswith("# "):
            title = stripped[2:].strip()
            for look_ahead in lines[idx + 1 : idx + 6]:
                candidate = look_ahead.strip()
                if not candidate:
                    continue
                if candidate.startswith("#"):
                    break
                subtitle = candidate
                break
        match = AUTHOR_LINE_RE.match(stripped)
        if match and "author" not in metadata:
            metadata["author"] = match.group(1).strip().strip('.')
        match = PUBLISHER_RE.match(stripped)
        if match and "publisher" not in metadata:
            metadata["publisher"] = match.group(1).strip().strip('.')
        for isbn in ISBN_RE.findall(stripped):
            identifiers.add(f"ISBN {isbn.strip()}")
        for ident in GENERIC_ID_RE.findall(stripped):
            identifiers.add(ident.strip())
        date_match = DATE_RE.search(stripped)
        if date_match and "date" not in metadata:
            date_str = date_match.group(0)
            if len(date_str) == 4:
                metadata["date"] = f"{date_str}-01-01T00:00:00+00:00"
            elif len(date_str) == 7:
                metadata["date"] = f"{date_str}-01T00:00:00+00:00"
            else:
                metadata["date"] = f"{date_str}T00:00:00+00:00"
    if identifiers:
        metadata["identifier"] = sorted(identifiers)

    if title:
        if subtitle and subtitle.lower() not in {"copyright"}:
            metadata["title"] = f"{title}: {subtitle}" if subtitle else title
        else:
            metadata["title"] = title
        short = title.split("—")[0].split("-")[0].strip()
        if short:
            metadata["title_short"] = short

    if "author" not in metadata:
        content_match = re.search(r"<meta[^>]*name=\"author\"[^>]*content=\"([^\"]+)\"", text, re.IGNORECASE)
        if content_match:
            metadata["author"] = content_match.group(1).strip()
        elif markdown_path:
            source_dir = markdown_path.parent / "source"
            if source_dir.exists():
                for html_file in sorted(source_dir.glob("*.html")):
                    try:
                        snippet = html_file.read_text(encoding="utf-8", errors="ignore")[:10000]
                    except Exception:
                        continue
                    match = re.search(r"<meta[^>]*name=\"author\"[^>]*content=\"([^\"]+)\"", snippet, re.IGNORECASE)
                    if match:
                        metadata["author"] = match.group(1).strip()
                        break

    if "publisher" not in metadata and markdown_path:
        source_dir = markdown_path.parent / "source"
        if source_dir.exists():
            for html_file in sorted(source_dir.glob("*.html")):
                try:
                    snippet = html_file.read_text(encoding="utf-8", errors="ignore")[:20000]
                except Exception:
                    continue
                pub_match = PUBLISHER_RE.search(snippet)
                if pub_match:
                    metadata["publisher"] = pub_match.group(1).strip().strip('.')
                    break
                meta_pub = re.search(r"<meta[^>]*name=\"publisher\"[^>]*content=\"([^\"]+)\"", snippet, re.IGNORECASE)
                if meta_pub:
                    metadata["publisher"] = meta_pub.group(1).strip()
                    break

    if "date" not in metadata:
        year_match = YEAR_RE.search(text)
        if year_match:
            year = year_match.group(0)
            metadata["date"] = f"{year}-01-01T00:00:00+00:00"
        elif markdown_path:
            source_dir = markdown_path.parent / "source"
            if source_dir.exists():
                for html_file in sorted(source_dir.glob("*.html")):
                    try:
                        snippet = html_file.read_text(encoding="utf-8", errors="ignore")[:20000]
                    except Exception:
                        continue
                    year_match = YEAR_RE.search(snippet)
                    if year_match:
                        year = year_match.group(0)
                        metadata["date"] = f"{year}-01-01T00:00:00+00:00"
                        break

    return metadata


def insert_frontmatter(text: str, markdown_path: Path | None = None) -> str:
    """Prepend YAML front matter if metadata can be inferred from the content."""
    if text.lstrip().startswith("---\n"):
        return text

    metadata = extract_frontmatter_metadata(text, markdown_path)
    if not metadata:
        return text

    front_lines = ["---"]
    if "author" in metadata:
        front_lines.append(f"author: {metadata['author']}")
    if "date" in metadata:
        front_lines.append(f"date: \"{metadata['date']}\"")
    identifiers = metadata.get("identifier")
    if identifiers:
        front_lines.append("identifier:")
        for ident in identifiers:
            front_lines.append(f"  - {ident}")
    front_lines.append("language: en")
    if "publisher" in metadata:
        front_lines.append(f"publisher: {metadata['publisher']}")
    if "title" in metadata:
        front_lines.append(f"title: \"{metadata['title']}\"")
    if "title_short" in metadata:
        front_lines.append(f"title_short: \"{metadata['title_short']}\"")
    front_lines.append("---\n")

    return "\n".join(front_lines) + text.lstrip("\n")


def strip_internal_links(text: str) -> str:
    """Drop Acrobat-only bookmarks while preserving real outbound links."""
    def is_external(target: str) -> bool:
        lower = target.strip().lower()
        if not lower:
            return False
        if lower.startswith("http://") or lower.startswith("https://"):
            return True
        if re.search(r"\.html?(?:[#?].*)?$", lower):
            return True
        return False

    def image_repl(match: re.Match[str]) -> str:
        target = match.group(2).strip()
        lower = target.lower()
        if not lower:
            return ""
        if lower.startswith("#") or "bookmark" in lower:
            return ""
        return match.group(0)

    def link_repl(match: re.Match[str]) -> str:
        label, target = match.group(1), match.group(2)
        if is_external(target):
            return match.group(0)
        return label

    text = INTERNAL_IMAGE_RE.sub(image_repl, text)
    text = INTERNAL_LINK_RE.sub(link_repl, text)

    cleaned_lines: list[str] = []
    for line in text.splitlines():
        if FOOTNOTE_DEF_RE.match(line):
            cleaned_lines.append(line)
            continue
        line = re.sub(r"(?<!!)\[([^\]]+)\]", r"\1", line)

        def paren_repl(match: re.Match[str]) -> str:
            inner = match.group(1).strip()
            lower_inner = inner.lower()
            if not inner:
                return ""
            if lower_inner.startswith("#") or "bookmark" in lower_inner:
                return ""
            return match.group(0)

        line = re.sub(r"\(([^)]+)\)", paren_repl, line)
        cleaned_lines.append(line)

    return "\n".join(cleaned_lines)


def remove_zero_width(text: str) -> str:
    """Remove zero-width Unicode characters that confuse renderers."""
    return ZERO_WIDTH_RE.sub("", text)


def remove_empty_brackets(text: str) -> str:
    """Delete leftover Markdown link markers without a label."""
    return EMPTY_BRACKETS_RE.sub("", text)


def normalize_image_alt_text(text: str) -> str:
    """Ensure Acrobat image spans collapse into empty-alt Markdown image tags."""
    def repl(match: re.Match[str]) -> str:
        return f"![]({match.group(2)})"

    return INTERNAL_IMAGE_RE.sub(repl, text)


def collapse_spaces(text: str) -> str:
    """Reduce runs of multiple spaces to single spaces per line."""
    def fix_line(line: str) -> str:
        return re.sub(r" {2,}", " ", line)

    return "\n".join(fix_line(line) for line in text.splitlines())


def collapse_blank_lines(text: str) -> str:
    """Normalize blank-line spacing to at most two consecutive newlines."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text


def should_merge_paragraphs(prev_line: str, next_line: str) -> bool:
    """Heuristically decide if two lines should form one continuous paragraph."""
    prev = prev_line.rstrip()
    if not prev:
        return False
    first_char = next_line.lstrip()[:1]
    if not first_char or not first_char.islower():
        return False
    if prev.endswith((".", "!", "?", ":", ";", "—", "–")):
        return False
    if next_line.lstrip().startswith(("#", "-", "*", ">", "```")):
        return False
    return True


def merge_split_paragraphs(text: str) -> str:
    """Rejoin paragraphs Acrobat split with blank lines but mid-sentence."""
    lines = text.splitlines()
    merged: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.strip() == "" and merged:
            j = i + 1
            while j < len(lines) and lines[j].strip() == "":
                j += 1
            if j < len(lines) and should_merge_paragraphs(merged[-1], lines[j]):
                merged[-1] = merged[-1].rstrip() + " " + lines[j].lstrip()
                i = j + 1
                continue
        merged.append(line)
        i += 1
    return "\n".join(merged)


def slugify_heading(title: str) -> str:
    """Create a lowercase anchor slug from a heading title."""
    slug = title.lower()
    slug = re.sub(r"[^a-z0-9\s-]", "", slug)
    slug = re.sub(r"\s+", "-", slug.strip())
    slug = re.sub(r"-+", "-", slug)
    return slug


def insert_table_of_contents(text: str) -> str:
    """Insert or replace a `## Table of Contents` section based on headings."""
    lines = text.splitlines()
    heading_re = re.compile(r"^## (?!#)(.+?)\s*$")
    headings: list[tuple[str, str]] = []

    for line in lines:
        match = heading_re.match(line)
        if not match:
            continue
        title = match.group(1).strip()
        if title.lower() == "table of contents":
            continue
        slug = slugify_heading(title)
        headings.append((title, slug))

    if not headings:
        return text

    toc_lines = ["## Table of Contents", ""]
    toc_lines.extend(f"- [{title}](#{slug})" for title, slug in headings)
    toc_lines.append("")

    toc_start = None
    for idx, line in enumerate(lines):
        if line.strip().lower() == "## table of contents":
            toc_start = idx
            break

    if toc_start is not None:
        toc_end = len(lines)
        for idx in range(toc_start + 1, len(lines)):
            if lines[idx].startswith("## "):
                toc_end = idx
                break
        lines = lines[:toc_start] + toc_lines + lines[toc_end:]
    else:
        insert_at = 0
        for idx, line in enumerate(lines):
            stripped = line.strip()
            insert_at = idx
            if stripped.startswith("#") and stripped.lower() != "# table of contents":
                break
        lines = lines[: insert_at + 1] + [""] + toc_lines + lines[insert_at + 1 :]

    return "\n".join(lines)


def process_file(markdown_path: Path, dry_run: bool) -> bool:
    """Apply cleanup passes to a Markdown file and write changes unless dry-run."""
    original = markdown_path.read_text(encoding="utf-8")
    lines = original.splitlines()
    cleaned_lines = strip_brace_blocks(lines)
    cleaned = "\n".join(cleaned_lines)
    cleaned = remove_escaped_sequences(cleaned)
    cleaned = strip_internal_links(cleaned)
    cleaned = normalize_image_alt_text(cleaned)
    cleaned = remove_zero_width(cleaned)
    cleaned = remove_empty_brackets(cleaned)
    cleaned = drop_stray_backslash_lines(cleaned)
    cleaned = collapse_spaces(cleaned)
    cleaned = merge_split_paragraphs(cleaned)
    cleaned = collapse_blank_lines(cleaned)
    cleaned = TRIPLE_DASH_RE.sub("—", cleaned)
    cleaned = insert_table_of_contents(cleaned)
    cleaned = insert_frontmatter(cleaned, markdown_path)
    if not cleaned.endswith("\n"):
        cleaned += "\n"
    if cleaned == original:
        return False
    if dry_run:
        print(cleaned, end="")
    else:
        markdown_path.write_text(cleaned, encoding="utf-8")
    return True


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments for the Acrobat Markdown cleanup utility."""
    parser = argparse.ArgumentParser(
        description="Remove Acrobat residual markup from Markdown"
    )
    parser.add_argument("markdown_file", type=Path, help="Path to the Markdown file to clean")
    parser.add_argument("--dry-run", action="store_true", help="Preview output without writing")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point that cleans a Markdown file exported from Acrobat."""
    args = parse_args(argv)
    if not args.markdown_file.exists():
        print(f"File '{args.markdown_file}' does not exist")
        return 1
    try:
        changed = process_file(args.markdown_file, args.dry_run)
    except Exception as exc:  # pragma: no cover - defensive
        print(f"Failed to clean Markdown: {exc}")
        return 2
    if changed and not args.dry_run:
        print(f"Updated {args.markdown_file}")
    elif not changed:
        print("No changes needed")
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
