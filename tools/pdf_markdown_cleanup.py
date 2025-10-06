#!/usr/bin/env python3
"""Normalize Markdown generated from PDFs by collapsing noisy whitespace.

Part of the `markdown_forge` framework.

Key behaviours:
- Collapse runs of spaces or tabs within prose lines to a single space.
- Trim trailing whitespace and normalise blank lines.
- Preserve content inside fenced code blocks so spacing is untouched.
- Optionally preview the cleaned output via ``--dry-run``.

Usage:
    python tools/pdf_markdown_cleanup.py path/to/file.md [--dry-run]
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Iterable, List, Sequence

WHITESPACE_RUN_RE = re.compile(r"[ \t]{2,}")
LIST_MARKER_RE = re.compile(r"^(?:[-*+]\s+|\d+[.)]\s+|[A-Za-z][.)]\s+)")
FOOTNOTE_DEF_RE = re.compile(r"^\[\^[^\]]+\]:")
FENCE_PREFIXES = ("```", "~~~")


def collapse_internal_whitespace(lines: Sequence[str]) -> List[str]:
    """Collapse repeated spaces within prose lines while preserving code blocks."""
    cleaned: List[str] = []
    in_code_block = False

    for line in lines:
        stripped = line.lstrip()
        if any(stripped.startswith(prefix) for prefix in FENCE_PREFIXES):
            in_code_block = not in_code_block
            cleaned.append(line.rstrip())
            continue

        if in_code_block:
            cleaned.append(line.rstrip())
            continue

        leading_len = len(line) - len(line.lstrip(" "))
        prefix = line[:leading_len]
        rest = line[leading_len:]
        rest = WHITESPACE_RUN_RE.sub(" ", rest)
        cleaned.append((prefix + rest).rstrip())

    return cleaned


def collapse_blank_lines(lines: Iterable[str]) -> List[str]:
    """Reduce consecutive blank lines to a single blank separator."""
    result: List[str] = []
    blank_streak = 0
    for line in lines:
        if line == "":
            blank_streak += 1
            if blank_streak > 1:
                continue
        else:
            blank_streak = 0
        result.append(line)
    return result


def is_paragraph_candidate(original_line: str) -> bool:
    """Determine whether a line can participate in paragraph reflowing."""
    stripped = original_line.strip()
    if not stripped:
        return False
    leading_spaces = len(original_line) - len(original_line.lstrip(" "))
    if leading_spaces >= 4:
        return False
    if stripped.startswith("#"):
        return False
    if stripped.startswith(">"):
        return False
    if stripped.startswith("|"):
        return False
    if stripped in {"---", "***", "___"}:
        return False
    if stripped.startswith("<") and stripped.endswith(">"):
        return False
    if LIST_MARKER_RE.match(stripped):
        return False
    if FOOTNOTE_DEF_RE.match(stripped):
        return False
    return True


def combine_paragraph_lines(lines: Sequence[str]) -> str:
    """Join wrapped paragraph fragments into a single line of text."""
    combined = ""
    for part in lines:
        chunk = part.strip()
        if not chunk:
            continue
        if combined:
            if combined.endswith("-") and not combined.endswith("--"):
                combined = combined[:-1] + chunk
            else:
                combined += " " + chunk
        else:
            combined = chunk
    return combined


def unwrap_paragraphs(lines: Sequence[str]) -> List[str]:
    """Reconstruct paragraphs from hard-wrapped Markdown lines."""
    result: List[str] = []
    buffer: List[str] = []
    in_code_block = False

    def flush_buffer() -> None:
        if not buffer:
            return
        paragraph = combine_paragraph_lines(buffer)
        if paragraph:
            result.append(paragraph)
            result.append("")
        buffer.clear()

    for line in lines:
        current = line.rstrip()
        stripped_leading = current.lstrip()
        if any(stripped_leading.startswith(prefix) for prefix in FENCE_PREFIXES):
            flush_buffer()
            in_code_block = not in_code_block
            result.append(current)
            continue

        if in_code_block:
            result.append(current)
            continue

        if not current.strip():
            flush_buffer()
            result.append("")
            continue

        if is_paragraph_candidate(current):
            buffer.append(current)
            continue

        flush_buffer()
        result.append(current)

    flush_buffer()
    if result and result[-1] == "":
        result.pop()
    return result


def normalise_text(text: str) -> str:
    """Apply whitespace cleanup, paragraph unwrapping, and trailing newline."""
    text = text.replace("\u00a0", " ")
    lines = text.splitlines()
    lines = unwrap_paragraphs(lines)
    lines = collapse_internal_whitespace(lines)
    lines = collapse_blank_lines(lines)
    normalised = "\n".join(lines).strip()
    return normalised + "\n"


def process_file(markdown_path: Path, dry_run: bool) -> bool:
    """Clean a Markdown file in-place (or preview) and report if changes occurred."""
    original = markdown_path.read_text(encoding="utf-8")
    cleaned = normalise_text(original)
    if cleaned == original:
        return False
    if dry_run:
        print(cleaned, end="")
    else:
        markdown_path.write_text(cleaned, encoding="utf-8")
    return True


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Configure CLI flags for PDF Markdown whitespace cleanup."""
    parser = argparse.ArgumentParser(description="Tidy Markdown emitted from PDFs by normalising whitespace")
    parser.add_argument("markdown_file", type=Path, help="Path to the Markdown file to clean")
    parser.add_argument("--dry-run", action="store_true", help="Print cleaned output to stdout instead of writing")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point that wraps `process_file` with basic error handling."""
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


if __name__ == "__main__":  # pragma: no cover - CLI entry
    raise SystemExit(main())
