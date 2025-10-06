#!/usr/bin/env python3
"""Render Markdown into a single-page self-contained HTML document via Pandoc.

Part of the `markdown_forge` framework.

This utility wraps `pandoc` to emit an HTML file with embedded assets and
inline CSS. The generated page prefers Georgia for body copy and Menlo for
monospaced code blocks.

Usage:
    python tools/markdown_to_self_contained_html.py SOURCE.md [--output OUTPUT.html]

Options:
    --title TEXT   Override the HTML document title.
    --pandoc PATH  Specify a custom pandoc executable (default: "pandoc" on PATH).
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

DEFAULT_CSS = """
body {
    font-family: 'Georgia', 'Times New Roman', serif;
    line-height: 1.6;
    margin: 2.5rem auto;
    max-width: 960px;
    padding: 0 1.5rem;
    color: #222;
    background-color: #faf9f7;
}

h1, h2, h3, h4, h5, h6 {
    font-family: 'Georgia', 'Times New Roman', serif;
    line-height: 1.25;
    color: #111;
}

pre, code, kbd, samp {
    font-family: 'Menlo', 'Courier New', monospace;
}

pre {
    background: #f0f2f5;
    border-radius: 6px;
    padding: 1rem;
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
    margin: 1.5rem 0;
    padding: 0.5rem 1rem;
    color: #4b5563;
    background: #f7f9fc;
}

img {
    display:block;
    max-width: 100%;
    margin-left:auto;
    margin-right:auto;
    height: auto;
}
""".strip()


def strip_front_matter(text: str) -> tuple[str, dict[str, str], bool]:
    """Remove leading YAML front matter, returning body text, metadata, and flag."""
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
        if not stripped or stripped.startswith('#'):
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


def render_markdown_to_html(
    source: Path,
    output: Path,
    pandoc: str = "pandoc",
    title: str | None = None,
) -> None:
    """Convert Markdown to standalone HTML using Pandoc with embedded CSS/assets."""
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

    resource_paths = {str(source.parent.resolve())}
    if source.parent != Path("."):
        resource_paths.add(str(source.parent))
    resource_path_arg = os.pathsep.join(sorted(resource_paths))

    effective_title = title or metadata.get("title")

    pandoc_cmd = [
        pandoc,
        str(markdown_path),
        "--standalone",
        "--self-contained",
        "--embed-resources",
        "--resource-path",
        resource_path_arg,
        "--css",
        str(css_path),
        "-o",
        str(output),
    ]

    if effective_title:
        pandoc_cmd.extend(["--metadata", f"title={effective_title}"])

    try:
        completed = subprocess.run(pandoc_cmd, check=False, capture_output=True, text=True)
    finally:
        try:
            css_path.unlink()
        except FileNotFoundError:
            pass

    if completed.returncode != 0:
        stderr = completed.stderr.strip()
        stdout = completed.stdout.strip()
        message_parts = [
            f"Pandoc command failed with exit code {completed.returncode}.",
        ]
        if stdout:
            message_parts.append(f"stdout:\n{stdout}")
        if stderr:
            message_parts.append(f"stderr:\n{stderr}")
        raise RuntimeError("\n".join(message_parts))

    if temp_markdown_path is not None:
        try:
            temp_markdown_path.unlink()
        except FileNotFoundError:
            pass


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Configure CLI arguments for Markdown-to-HTML conversion."""
    parser = argparse.ArgumentParser(
        description="Convert Markdown to a self-contained single-page HTML document via Pandoc."
    )
    parser.add_argument("source", type=Path, help="Input Markdown file")
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        help="Destination HTML file (default: replace .md with .html)",
    )
    parser.add_argument(
        "--title",
        type=str,
        help="Override document title (default: derived from Markdown heading or filename)",
    )
    parser.add_argument(
        "--pandoc",
        type=str,
        default="pandoc",
        help="Pandoc executable to use (default: pandoc)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point that renders Markdown into a single HTML file."""
    args = parse_args(argv)

    source: Path = args.source
    if not source.exists():
        print(f"Source file '{source}' was not found", file=sys.stderr)
        return 1

    output: Path
    if args.output:
        output = args.output
    else:
        output = source.with_suffix(".html")

    try:
        render_markdown_to_html(
            source=source,
            output=output,
            pandoc=args.pandoc,
            title=args.title,
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
