#!/usr/bin/env python3
"""Convert Markdown into a clean EPUB file via Pandoc.

Part of the `markdown_forge` framework.

This utility mirrors the behaviour of `markdown_to_self_contained_html.py`,
but the output is an EPUB container. Front matter metadata (title, author)
is respected, a simple Georgia/Menlo stylesheet is embedded, and external
assets are resolved through Pandoc's resource path handling.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import re
from pathlib import Path

DEFAULT_CSS = """
body {
    font-family: 'Georgia', 'Times New Roman', serif;
    line-height: 1.6;
    margin: 1rem;
    color: #222;
}

h1, h2, h3, h4, h5, h6 {
    font-family: 'Georgia', 'Times New Roman', serif;
    line-height: 1.25;
    color: #111;
    margin-top: 1.5em;
}

h1 {
    break-before: page;
    page-break-before: always;
    -webkit-column-break-before: always;
}

body > h1:first-of-type {
    break-before: auto;
    page-break-before: auto;
    -webkit-column-break-before: auto;
}

div.level1 {
    break-before: page;
    page-break-before: always;
    -webkit-column-break-before: always;
}

div.book .chapter {
    break-before: page;
    page-break-before: always;
    -webkit-column-break-before: always;
}

pre, code, kbd, samp {
    font-family: 'Menlo', 'Courier New', monospace;
}

pre {
    background: #f0f2f5;
    border-radius: 6px;
    padding: 0.75rem;
    overflow-x: auto;
}

a {
    color: #0b5cad;
    text-decoration: none;
}

a:hover {
    text-decoration: underline;
}

blockquote {
    border-left: 4px solid #d0d7de;
    margin: 1.25rem 0;
    padding: 0.5rem 1rem;
    color: #4b5563;
    background: #f7f9fc;
}
""".strip()


def strip_front_matter(text: str) -> tuple[str, dict[str, str], bool]:
    """Remove YAML front matter block, returning remaining text, metadata, and flag."""
    metadata: dict[str, str] = {}
    if not text.startswith("---"):
        return text, metadata, False

    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return text, metadata, False

    closing_index = None
    for idx in range(1, len(lines)):
        if lines[idx].strip() == "---":
            closing_index = idx
            break

    if closing_index is None:
        return text, metadata, False

    for raw_line in lines[1:closing_index]:
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if ':' not in stripped:
            continue
        key, value = stripped.split(':', 1)
        key = key.strip().lower()
        value = value.strip()
        if not key:
            continue
        if value.startswith(('"', "'")) and value.endswith(('"', "'")) and len(value) >= 2:
            value = value[1:-1]
        metadata[key] = value.strip()

    remaining = "\n".join(lines[closing_index + 1 :])
    return remaining.lstrip("\n"), metadata, True


def infer_epub_chapter_level(markdown_text: str) -> int:
    """Guess which heading level should split chapters based on heading frequency."""
    heading_counts: dict[int, int] = {}
    for line in markdown_text.splitlines():
        match = re.match(r"^(#{1,6})\s+", line)
        if not match:
            continue
        level = len(match.group(1))
        heading_counts[level] = heading_counts.get(level, 0) + 1

    if not heading_counts:
        return 1

    for level in sorted(heading_counts):
        if heading_counts[level] > 1:
            return level

    return min(heading_counts)


def resolve_cover_image(
    explicit_cover: Path | None,
    metadata: dict[str, str],
    markdown_text: str,
    source: Path,
) -> Path | None:
    """Find a cover image from CLI flag, metadata, or first Markdown image."""
    if explicit_cover is not None:
        return explicit_cover

    for key in ("cover-image", "cover_image", "cover"):
        value = metadata.get(key)
        if value:
            candidate = (source.parent / value).resolve()
            if candidate.exists():
                return candidate

    image_match = re.search(r"!\[[^\]]*\]\(([^)]+)\)", markdown_text)
    if image_match:
        candidate = (source.parent / image_match.group(1)).resolve()
        if candidate.exists():
            return candidate

    return None


def render_markdown_to_epub(
    source: Path,
    output: Path,
    pandoc: str = "pandoc",
    title: str | None = None,
    author: str | None = None,
    cover_image: Path | None = None,
    chapter_level: int | None = None,
) -> None:
    """Invoke Pandoc to package Markdown into an EPUB with styling and metadata."""
    if not source.exists():
        raise FileNotFoundError(f"Markdown source '{source}' does not exist")

    if shutil.which(pandoc) is None:
        raise FileNotFoundError(
            f"Pandoc executable '{pandoc}' was not found on PATH. Install pandoc or specify --pandoc."
        )

    output.parent.mkdir(parents=True, exist_ok=True)

    source_text = source.read_text(encoding="utf-8")
    processed_text, metadata, had_front_matter = strip_front_matter(source_text)
    markdown_path = source
    temp_markdown_path: Path | None = None

    if had_front_matter:
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as md_file:
            if processed_text and not processed_text.endswith("\n"):
                processed_text_to_write = processed_text + "\n"
            else:
                processed_text_to_write = processed_text
            md_file.write(processed_text_to_write)
            temp_markdown_path = Path(md_file.name)
        markdown_path = temp_markdown_path

    with tempfile.NamedTemporaryFile("w", suffix=".css", delete=False, encoding="utf-8") as css_file:
        css_file.write(DEFAULT_CSS)
        css_path = Path(css_file.name)

    resource_paths = {source.parent.resolve()}
    for path in list(resource_paths):
        for child in path.iterdir():
            if child.is_dir() and "images" in child.name.lower():
                resource_paths.add(child.resolve())
    resource_path_arg = os.pathsep.join(str(path) for path in sorted(resource_paths))

    effective_title = title or metadata.get("title")
    effective_author = author or metadata.get("author")
    effective_chapter_level = chapter_level
    if effective_chapter_level is None:
        effective_chapter_level = infer_epub_chapter_level(processed_text or source_text)

    cover_path = resolve_cover_image(cover_image, metadata, processed_text, source)

    pandoc_cmd = [
        pandoc,
        str(markdown_path),
        "--standalone",
        "--resource-path",
        resource_path_arg,
        "--css",
        str(css_path),
        "--epub-chapter-level",
        str(effective_chapter_level),
        "-o",
        str(output),
    ]

    if effective_title:
        pandoc_cmd.extend(["--metadata", f"title={effective_title}"])
    if effective_author:
        pandoc_cmd.extend(["--metadata", f"author={effective_author}"])
    if cover_path is not None:
        pandoc_cmd.extend(["--epub-cover-image", str(cover_path)])

    try:
        completed = subprocess.run(pandoc_cmd, check=False, capture_output=True, text=True)
    finally:
        try:
            css_path.unlink()
        except FileNotFoundError:
            pass
        if temp_markdown_path is not None:
            try:
                temp_markdown_path.unlink()
            except FileNotFoundError:
                pass

    if completed.returncode != 0:
        stdout = completed.stdout.strip()
        stderr = completed.stderr.strip()
        message_parts = [
            f"Pandoc command failed with exit code {completed.returncode}.",
        ]
        if stdout:
            message_parts.append(f"stdout:\n{stdout}")
        if stderr:
            message_parts.append(f"stderr:\n{stderr}")
        raise RuntimeError("\n".join(message_parts))


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Configure CLI options for Markdown-to-EPUB conversion."""
    parser = argparse.ArgumentParser(description="Convert Markdown to a clean EPUB with Pandoc.")
    parser.add_argument("source", type=Path, help="Input Markdown file")
    parser.add_argument("--output", "-o", type=Path, help="Destination EPUB file (default: replace .md with .epub)")
    parser.add_argument("--title", type=str, help="Override document title (default: from front matter or filename)")
    parser.add_argument("--author", type=str, help="Override document author (default: from front matter)")
    parser.add_argument("--cover-image", type=Path, help="Optional cover image to embed in the EPUB")
    parser.add_argument(
        "--chapter-level",
        type=int,
        dest="chapter_level",
        help="Heading level at which to split EPUB chapters (default: auto-detected)",
    )
    parser.add_argument("--pandoc", type=str, default="pandoc", help="Pandoc executable to use (default: pandoc)")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point that converts Markdown content into an EPUB."""
    args = parse_args(argv)

    source: Path = args.source
    if not source.exists():
        print(f"Source file '{source}' was not found", file=sys.stderr)
        return 1

    if args.cover_image and not args.cover_image.exists():
        print(f"Cover image '{args.cover_image}' was not found", file=sys.stderr)
        return 1

    output: Path
    if args.output:
        output = args.output
    else:
        output = source.with_suffix(".epub")

    try:
        render_markdown_to_epub(
            source=source,
            output=output,
            pandoc=args.pandoc,
            title=args.title,
            author=args.author,
            cover_image=args.cover_image,
            chapter_level=args.chapter_level,
        )
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    print(f"Wrote {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

