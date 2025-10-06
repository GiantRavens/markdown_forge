#!/usr/bin/env python3
"""Incremental Markdown cleanup utilities.

Part of the `markdown_forge` framework.

Currently supports removing inlined Pandoc/Calibre anchor spans such as
`{#part0005.html_id_Toc123 .block_17}`.

Usage:
    python tools/markdown_cleanup.py path/to/file.md

This script is intended to grow feature-by-feature. Run with `--dry-run`
 to preview changes.
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

ANCHOR_PATTERN = re.compile(r"\s*\{#[^}]+\}")
EMPTY_LINK_LINE_PATTERN = re.compile(r"^\s*\[\s*\]\s*$", re.MULTILINE)
CSS_CLASS_PATTERN = re.compile(r"\.([A-Za-z0-9_-]+)\s*\{([^}]*)\}", re.DOTALL)
INLINE_CLASS_PATTERN = re.compile(r"\[([^\]]+)\]\{([^}]+)\}")
LEGACY_DOUBLE_LINK_PATTERN = re.compile(
    r"\[\[(?P<display>[^\]]+?)\]\]\s*\(\s*(?P<target>#[^\)]+)\)",
    re.IGNORECASE,
)
ORPHAN_DOUBLE_BRACKETS_PATTERN = re.compile(r"\[\[([^\]]+?)\]\]")
SPAN_CLASS_PATTERN = re.compile(r"<span class=\"([^\"]+)\">(.*?)</span>", re.DOTALL)
CLASS_ONLY_BRACES_PATTERN = re.compile(r"\{\s*(?:\.[A-Za-z0-9_-]+\s*)+\}")
MULTI_BLANK_PATTERN = re.compile(r"(?:[ \t]*\n){3,}")
HEADING_PATTERN = re.compile(r"^(#{1,6})\s+(.*)$")
CALIBRE_CONTAINER_PATTERN = re.compile(
    r"(?sm)^(?P<indent>[ \t]*):::{4,}\s+calibre\w*\s*\n(?P<body>.*?)(?:\n(?P=indent):::{4,}\s*(?:\n|$))"
)
CALIBRE_ITEM_PATTERN = re.compile(r":::\s+block_[^\s]+\s*\n(.*?)(?:\n:::\s*(?:\n|$))", re.DOTALL)
CALIBRE_BULLET_PATTERN = re.compile(r"^\s*\[[^\]]*\]\[(?P<text>.*?)\]\s*$", re.DOTALL)
CALIBRE_ONLY_PATTERN = re.compile(r"^:::+\s+calibre[^\s]*\s*$", re.IGNORECASE)
BLOCK_ONLY_PATTERN = re.compile(r"^:::+\s+block_[^\s]*\s*$", re.IGNORECASE)
BULLETED_SQUARE_PATTERN = re.compile(r"^(?P<prefix>\s*)\[•\s*\]\s*(?P<text>.+)$")
BULLET_ONLY_PATTERN = re.compile(r"^(?P<prefix>\s*)•\s+(?P<text>.+)$")
SQUARE_BULLET_MARKER_PATTERN = re.compile(r"\[•\s*\]")
EMPTY_STYLE_BLOCK_PATTERN = re.compile(r"^:::\s*\{[^}]*\}\s*$")
BARE_CALIBRE_PATTERN = re.compile(r"^:::+\s*$")
REDUNDANT_ESCAPE_PATTERN = re.compile(r"\\([.!?,:;'])")
TILDE_LINE_PATTERN = re.compile(r"^\s*~+\s*$")
EMPTY_BRACKETS_PATTERN = re.compile(r"\[\s+\]")
HYPHEN_BULLET_PATTERN = re.compile(r"^\s*-\s+\S")
REDUNDANT_IMAGE_SEGMENT_PATTERN = re.compile(r"images/(?:(?:images|OEBPS)/)+", re.IGNORECASE)
ISBN_PATTERN = re.compile(r"\bISBN(?:-1[03])?:?\s*([0-9][0-9Xx\s-]{8,}[0-9Xx])", re.IGNORECASE)
NON_LINK_BRACKET_PATTERN = re.compile(r"\[(?P<text>[^\]]+)\](?!\s*(\(|:))")
PART_LINK_PATTERN = re.compile(r"\[(?P<label>[^\]]+)\]\(#part[^\)]+\)", re.IGNORECASE)
INLINE_EM_DASH_PATTERN = re.compile(r"(?<!-)(---)(?!-)")
HTML_COMMENT_PATTERN = re.compile(r"<!--.*?-->", re.DOTALL)
CBJ_BLOCK_PATTERN = re.compile(r"^\s*:::\s+cbj_[^\s]+$", re.IGNORECASE)
BACKSLASH_ONLY_PATTERN = re.compile(r"^\s*\\\s*$")
STYLE_LINE_PATTERN = re.compile(r"^\s*\{\s*style\s*=\s*\"[^\"]*\"\s*\}\s*$", re.IGNORECASE)
COLON_BLOCK_PATTERN = re.compile(r"^:::+\s*.*$")
DASH_RULE_PATTERN = re.compile(r"^-{5,}$")
MALFORMED_LINK_PATTERN = re.compile(r"\[\[\]\[(?P<text>[^\]]+)\]\((?P<primary>#[^\)]+)\)\]\((?P<secondary>#[^\)]+)\)")
EMPTY_LABEL_LINK_PATTERN = re.compile(r'\[\]\s*([^\]]+?)(?=\]\()')
SVG_OPEN_PATTERN = re.compile(r"<svg\b", re.IGNORECASE)
SVG_CLOSE_PATTERN = re.compile(r"</svg>", re.IGNORECASE)
OEBPS_IMAGE_PATTERN = re.compile(r"^images/(?:OEBPS/)+(.+)$")
MARKDOWN_IMAGE_PATTERN = re.compile(r"(!\[[^\]]*\]\()([^\)]+)(\))")


def normalize_isbn(raw: str | None) -> Optional[str]:
    """Normalize raw ISBN strings into 10/13 digit uppercase variants."""
    if not raw:
        return None
    cleaned = re.sub(r"[^0-9Xx]", "", raw)
    if len(cleaned) == 13 and cleaned.isdigit():
        return cleaned
    if len(cleaned) == 10 and re.fullmatch(r"[0-9]{9}[0-9Xx]", cleaned):
        return cleaned.upper()
    return None


def extract_isbn(text: str, fallback_identifiers: Iterable[str] | None = None) -> Optional[str]:
    """Search Markdown text and fallback identifiers for a usable ISBN."""
    for match in ISBN_PATTERN.finditer(text):
        normalized = normalize_isbn(match.group(1))
        if normalized:
            return normalized
    if fallback_identifiers:
        for candidate in fallback_identifiers:
            normalized = normalize_isbn(candidate)
            if normalized:
                return normalized
    return None


def compute_title_short(title: str) -> str:
    """Derive a succinct title by trimming subtitles and dash suffixes."""
    if not title:
        return ""
    result = title.strip()
    if ":" in result:
        result = result.split(":", 1)[0].strip()
    dash_split = re.split(r"\s*[–—-]\s+", result, 1)
    if len(dash_split) > 1:
        result = dash_split[0].strip()
    return result


def trim_title_short(value: str) -> str:
    """Convenience wrapper that routes to `compute_title_short` when populated."""
    if not value:
        return ""
    return compute_title_short(value)


def parse_front_matter_block(lines: List[str]) -> Optional[Tuple[Dict[str, Any], List[str], Set[str]]]:
    """Parse a YAML front matter block into metadata, preserving key order."""
    if not lines or lines[0].strip() != "---" or lines[-1].strip() != "---":
        return None

    metadata: Dict[str, Any] = {}
    order: List[str] = []
    quoted: Set[str] = set()
    current_key: Optional[str] = None

    for raw in lines[1:-1]:
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("- "):
            if not current_key or not isinstance(metadata.get(current_key), list):
                return None
            metadata[current_key].append(stripped[2:].strip())
            continue
        if ":" in raw:
            key_part, value_part = raw.split(":", 1)
            key = key_part.strip()
            if not key:
                return None
            value = value_part.strip()
            if key not in order:
                order.append(key)
            if not value:
                metadata[key] = []
                current_key = key
                continue
            if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
                quoted.add(key)
                value = value[1:-1]
            metadata[key] = value
            current_key = key
            continue
        return None

    return metadata, order, quoted


def needs_quotes(value: str) -> bool:
    """Return True when a YAML scalar should be quoted for safety."""
    if value == "" or value != value.strip():
        return True
    if any(ch in value for ch in (":", "#", "\"", "'")):
        return True
    if re.search(r"\s", value) and ("::" in value or value.startswith("http")):
        return True
    if value.lower() in {"true", "false", "null", "~"}:
        return True
    return False


def format_scalar_value(value: Any, force_quotes: bool) -> str:
    """Render a YAML scalar string, quoting when requested or necessary."""
    text = "" if value is None else str(value)
    if force_quotes or needs_quotes(text):
        escaped = text.replace("\"", "\\\"")
        return f'"{escaped}"'
    return text


def serialize_front_matter(metadata: Dict[str, Any], order: List[str], quoted: Set[str]) -> List[str]:
    """Serialize metadata dict back into a YAML front matter sequence."""
    lines = ["---"]
    seen: Set[str] = set()
    for key in order + [k for k in metadata.keys() if k not in order]:
        if key in seen:
            continue
        seen.add(key)
        value = metadata.get(key)
        if isinstance(value, list):
            lines.append(f"{key}:")
            for item in value:
                lines.append(f"  - {format_scalar_value(item, False)}")
        else:
            lines.append(f"{key}: {format_scalar_value(value, key in quoted)}")
    lines.append("---")
    return lines


def parse_css_styles(css_text: str) -> Dict[str, Set[str]]:
    """Extract class-to-style flags (bold/italic/sup/sub) from CSS text."""
    mapping: Dict[str, Set[str]] = {}
    for match in CSS_CLASS_PATTERN.finditer(css_text):
        class_name = match.group(1)
        body = match.group(2)
        styles = mapping.setdefault(class_name, set())
        for declaration in body.split(';'):
            declaration = declaration.strip()
            if not declaration or ':' not in declaration:
                continue
            prop, value = declaration.split(':', 1)
            prop = prop.strip().lower()
            value = value.strip().lower()
            if prop == "font-weight" and value.startswith("bold"):
                styles.add("bold")
            elif prop == "font-style" and value.startswith("italic"):
                styles.add("italic")
            elif prop == "vertical-align":
                if "super" in value:
                    styles.add("sup")
                elif "sub" in value:
                    styles.add("sub")
    return mapping


def load_style_map(markdown_file: Path) -> Dict[str, Set[str]]:
    """Locate adjacent CSS files and build a class->style lookup map."""
    candidates = [
        markdown_file.parent / "source_epub" / "extracted" / "stylesheet.css",
        markdown_file.parent / "source_epub" / "stylesheet.css",
        markdown_file.parent / "source" / "extracted" / "stylesheet.css",
        markdown_file.parent / "source" / "stylesheet.css",
    ]
    style_map: Dict[str, Set[str]] = {}
    for css_path in candidates:
        if css_path.exists():
            css_text = css_path.read_text(encoding="utf-8")
            css_map = parse_css_styles(css_text)
            for key, styles in css_map.items():
                style_map.setdefault(key, set()).update(styles)
    return style_map


def parse_class_list(spec: str) -> List[str]:
    """Tokenize a Pandoc/Markdown class specification into individual names."""
    spec = spec.strip()
    if not spec:
        return []
    if spec.startswith('.'):
        return re.findall(r"\.([A-Za-z0-9_-]+)", spec)
    return [part for part in spec.split() if part]


def aggregate_styles(class_names: Iterable[str], style_map: Dict[str, Set[str]]) -> Set[str]:
    """Combine style attributes for all class names with known mappings."""
    styles: Set[str] = set()
    for class_name in class_names:
        styles.update(style_map.get(class_name, set()))
    return styles


def apply_inline_styles(text: str, styles: Set[str]) -> str:
    if not styles:
        return text
    inner = text
    emphasis = ""
    if "bold" in styles and "italic" in styles:
        emphasis = "***"
    elif "bold" in styles:
        emphasis = "**"
    elif "italic" in styles:
        emphasis = "*"
    if emphasis:
        inner = f"{emphasis}{inner}{emphasis}"
    for tag in ("sup", "sub"):
        if tag in styles:
            inner = f"<{tag}>{inner}</{tag}>"
    return inner


def apply_pandoc_class_notation(text: str, style_map: Dict[str, Set[str]]) -> str:
    def replace(match: re.Match[str]) -> str:
        content = match.group(1)
        spec = match.group(2)
        classes = parse_class_list(spec)
        styles = aggregate_styles(classes, style_map)
        return apply_inline_styles(content, styles)

    return INLINE_CLASS_PATTERN.sub(replace, text)

def apply_span_classes(text: str, style_map: Dict[str, Set[str]]) -> str:
    def replace(match: re.Match[str]) -> str:
        classes = parse_class_list(match.group(1))
        content = match.group(2)
        styles = aggregate_styles(classes, style_map)
        return apply_inline_styles(content, styles)

    return SPAN_CLASS_PATTERN.sub(replace, text)


def convert_calibre_blocks(text: str) -> str:
    def replace(match: re.Match[str]) -> str:
        indent = match.group("indent")
        body = match.group("body")
        items: List[str] = []
        for item_match in CALIBRE_ITEM_PATTERN.finditer(body):
            content = item_match.group(1).strip()
            bullet_match = CALIBRE_BULLET_PATTERN.match(content)
            if bullet_match:
                cleaned = bullet_match.group("text").strip()
            else:
                cleaned = re.sub(r"^\s*\[[^\]]*\]\s*", "", content).strip()
                if cleaned.startswith("[") and cleaned.endswith("]"):
                    cleaned = cleaned[1:-1].strip()
            if cleaned:
                items.append(f"{indent}- {cleaned}")
        if not items:
            fallback: List[str] = []
            for raw_line in body.splitlines():
                stripped = raw_line.strip()
                if not stripped or stripped.startswith(":::"):
                    continue
                bullet_match = CALIBRE_BULLET_PATTERN.match(raw_line)
                if bullet_match:
                    cleaned = bullet_match.group("text").strip()
                    if cleaned:
                        fallback.append(f"{indent}- {cleaned}")
                    continue
                fallback.append(f"{indent}{stripped}")
            if fallback:
                return "\n".join(fallback) + "\n"
            return match.group(0)
        return "\n".join(items) + "\n"

    return CALIBRE_CONTAINER_PATTERN.sub(replace, text)


def normalize_square_bullets(lines: List[str]) -> List[str]:
    normalized: List[str] = []
    for line in lines:
        match = BULLETED_SQUARE_PATTERN.match(line)
        if match:
            prefix = match.group("prefix")
            normalized.append(f"{prefix}- {match.group('text').strip()}")
            continue
        match = BULLET_ONLY_PATTERN.match(line)
        if match:
            prefix = match.group("prefix")
            normalized.append(f"{prefix}- {match.group('text').strip()}")
            continue
        replaced = SQUARE_BULLET_MARKER_PATTERN.sub(" - ", line)
        normalized.append(replaced)
    return normalized


def remove_vestigial_blocks(lines: List[str]) -> List[str]:
    cleaned: List[str] = []
    in_code_block = False
    for line in lines:
        stripped_leading = line.lstrip()
        if stripped_leading.startswith("```") or stripped_leading.startswith("~~~"):
            in_code_block = not in_code_block
            cleaned.append(line)
            continue
        if in_code_block:
            cleaned.append(line)
            continue

        stripped = line.strip()
        if not stripped:
            cleaned.append(line)
            continue
        if EMPTY_STYLE_BLOCK_PATTERN.match(stripped):
            continue
        if BARE_CALIBRE_PATTERN.match(stripped):
            continue
        if CALIBRE_ONLY_PATTERN.match(stripped):
            continue
        if BLOCK_ONLY_PATTERN.match(stripped):
            continue
        if TILDE_LINE_PATTERN.match(stripped):
            continue
        if CBJ_BLOCK_PATTERN.match(stripped):
            continue
        if BACKSLASH_ONLY_PATTERN.match(stripped):
            continue
        if STYLE_LINE_PATTERN.match(stripped):
            continue
        if COLON_BLOCK_PATTERN.match(stripped):
            continue
        cleaned.append(line)
    return cleaned


def convert_dash_rules(lines: List[str]) -> List[str]:
    result: List[str] = []
    in_code_block = False
    for line in lines:
        stripped_leading = line.lstrip()
        if stripped_leading.startswith("```") or stripped_leading.startswith("~~~"):
            in_code_block = not in_code_block
            result.append(line)
            continue
        if in_code_block:
            result.append(line)
            continue
        if DASH_RULE_PATTERN.match(line.strip()):
            result.append("<hr>")
            continue
        result.append(line)
    return result


def remove_svg_blocks(lines: List[str]) -> List[str]:
    result: List[str] = []
    in_svg = False
    for line in lines:
        if not in_svg and SVG_OPEN_PATTERN.search(line):
            in_svg = True
            continue
        if in_svg:
            if SVG_CLOSE_PATTERN.search(line):
                in_svg = False
            continue
        result.append(line)
    return result


def fix_malformed_links(lines: List[str]) -> List[str]:
    fixed: List[str] = []
    for line in lines:
        def repl(match: re.Match[str]) -> str:
            text = match.group("text").strip()
            target = match.group("primary")
            return f"[{text}]({target})"

        fixed.append(MALFORMED_LINK_PATTERN.sub(repl, line))
    return fixed


def remove_empty_label_links(lines: List[str]) -> List[str]:
    cleaned: List[str] = []
    for line in lines:
        cleaned.append(EMPTY_LABEL_LINK_PATTERN.sub(lambda m: f"[{m.group(1).strip()}]", line))
    return cleaned


def flatten_image_paths(markdown_file: Path) -> None:
    images_root = markdown_file.parent / "images"
    if not images_root.exists():
        return

    for image_path in list(images_root.rglob("*")):
        if not image_path.is_file():
            continue
        relative_parts = image_path.relative_to(images_root).parts
        if "OEBPS" not in relative_parts:
            continue
        target = images_root / image_path.name
        if target == image_path:
            continue
        if target.exists():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(image_path), target)

    # Remove now-empty directories inside images/, including OEBPS
    empty_dirs = sorted((p for p in images_root.rglob("*") if p.is_dir()), reverse=True)
    for directory in empty_dirs:
        try:
            directory.rmdir()
        except OSError:
            continue

    oebps_dir = images_root / "OEBPS"
    if oebps_dir.exists():
        try:
            oebps_dir.rmdir()
        except OSError:
            pass


def rewrite_markdown_image_paths(lines: List[str]) -> List[str]:
    rewritten: List[str] = []
    for line in lines:
        def replacer(match: re.Match[str]) -> str:
            prefix, path, suffix = match.groups()
            normalized = REDUNDANT_IMAGE_SEGMENT_PATTERN.sub("images/", path)
            normalized = OEBPS_IMAGE_PATTERN.sub(r"images/\1", normalized)
            return f"{prefix}{normalized}{suffix}"

        rewritten.append(MARKDOWN_IMAGE_PATTERN.sub(replacer, line))
    return rewritten


def remove_empty_brackets(lines: List[str]) -> List[str]:
    cleaned: List[str] = []
    for line in lines:
        leading_spaces = len(line) - len(line.lstrip(" "))
        prefix = line[:leading_spaces]
        content = line[leading_spaces:]
        if not content:
            cleaned.append(line)
            continue
        content = EMPTY_BRACKETS_PATTERN.sub("", content)
        content = re.sub(r" {2,}", " ", content)
        cleaned.append(prefix + content)
    return cleaned


def strip_part_links(lines: List[str]) -> List[str]:
    cleaned: List[str] = []
    in_code_block = False
    for line in lines:
        stripped = line.lstrip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_code_block = not in_code_block
            cleaned.append(line)
            continue
        if in_code_block:
            cleaned.append(line)
            continue
        cleaned.append(PART_LINK_PATTERN.sub(lambda match: match.group("label"), line))
    return cleaned


def convert_inline_em_dashes(lines: List[str]) -> List[str]:
    cleaned: List[str] = []
    in_code_block = False
    for line in lines:
        stripped = line.lstrip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_code_block = not in_code_block
            cleaned.append(line)
            continue
        if in_code_block:
            cleaned.append(line)
            continue
        stripped_full = line.strip()
        if stripped_full and set(stripped_full) <= {"-"}:
            cleaned.append(line)
            continue
        cleaned.append(INLINE_EM_DASH_PATTERN.sub("—", line))
    return cleaned


def strip_non_link_brackets(lines: List[str]) -> List[str]:
    cleaned: List[str] = []
    in_code_block = False
    for line in lines:
        stripped = line.lstrip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_code_block = not in_code_block
            cleaned.append(line)
            continue
        if in_code_block:
            cleaned.append(line)
            continue
        cleaned.append(NON_LINK_BRACKET_PATTERN.sub(lambda match: match.group("text"), line))
    return cleaned


def ensure_blank_line_after_hyphen_lists(lines: List[str]) -> List[str]:
    result: List[str] = []
    in_code_block = False
    total = len(lines)
    for idx, line in enumerate(lines):
        stripped = line.lstrip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_code_block = not in_code_block
            result.append(line)
            continue
        result.append(line)
        if in_code_block:
            continue
        if not HYPHEN_BULLET_PATTERN.match(line):
            continue
        next_line = lines[idx + 1] if idx + 1 < total else None
        if next_line is None:
            if result and result[-1].strip():
                result.append("")
            continue
        if not next_line.strip():
            continue
        if HYPHEN_BULLET_PATTERN.match(next_line):
            continue
        if result and result[-1].strip():
            result.append("")
    return result


def bold_uppercase_lines(lines: List[str]) -> List[str]:
    result: List[str] = []
    in_code_block = False
    for line in lines:
        stripped_leading = line.lstrip(" ")
        if stripped_leading.startswith("```") or stripped_leading.startswith("~~~"):
            in_code_block = not in_code_block
            result.append(line)
            continue
        if in_code_block:
            result.append(line)
            continue

        stripped = line.strip()
        if not stripped:
            result.append(line)
            continue
        if stripped.startswith(('#', '-', '*', '+', '>')):
            result.append(line)
            continue
        if stripped.startswith('**') and stripped.endswith('**') and len(stripped) > 4:
            result.append(line)
            continue
        if stripped.startswith('<') and stripped.endswith('>'):
            result.append(line)
            continue
        if stripped.startswith('`') and stripped.endswith('`'):
            result.append(line)
            continue

        letters = [ch for ch in stripped if ch.isalpha()]
        if not letters:
            result.append(line)
            continue
        if any(ch.islower() for ch in letters):
            result.append(line)
            continue

        prefix_len = len(line) - len(line.lstrip(' '))
        prefix = line[:prefix_len]
        bolded = f"**{stripped}**"
        result.append(prefix + bolded)
    return result


def strip_redundant_escapes(lines: List[str]) -> List[str]:
    result: List[str] = []
    in_code_block = False
    for line in lines:
        stripped = line.lstrip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_code_block = not in_code_block
            result.append(line)
            continue
        if in_code_block:
            result.append(line)
            continue
        result.append(REDUNDANT_ESCAPE_PATTERN.sub(r"\1", line))
    return result


def slugify_heading(text: str) -> str:
    slug = text.strip().lower()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"\s+", "-", slug)
    slug = re.sub(r"-+", "-", slug)
    return slug.strip("-")


def demote_headings(lines: List[str]) -> tuple[List[str], List[Tuple[str, str]], str | None]:
    in_code_block = False
    new_lines: List[str] = []
    toc_entries: List[Tuple[str, str]] = []
    first_heading_text: str | None = None
    slug_counts: Dict[str, int] = {}

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_code_block = not in_code_block
            new_lines.append(line)
            continue
        if not in_code_block:
            match = HEADING_PATTERN.match(line)
            if match:
                level = len(match.group(1))
                text = match.group(2).strip()
                normalized = text.lower().rstrip(":")
                if first_heading_text is None and normalized not in {"table of contents", "table of content"}:
                    first_heading_text = text
                if level == 1:
                    new_level = 2
                else:
                    new_level = level
                slug_id: Optional[str] = None
                if new_level == 2 and normalized not in {"table of contents", "table of content"}:
                    base_slug = slugify_heading(text) or "section"
                    count = slug_counts.get(base_slug, 0)
                    slug_id = base_slug if count == 0 else f"{base_slug}-{count}"
                    slug_counts[base_slug] = count + 1
                    toc_entries.append((text, slug_id))

                new_line = f"{'#' * new_level} {text}".rstrip()
                if slug_id:
                    new_line = f"{new_line} {{#{slug_id}}}"
                new_lines.append(new_line)
                continue
        new_lines.append(line)

    return new_lines, toc_entries, first_heading_text


def build_toc_lines(entries: List[Tuple[str, str]]) -> List[str]:
    if not entries:
        return []
    lines = ["## Table of Contents", ""]
    for text, slug in entries:
        lines.append(f"- [{text}](#{slug})")
    lines.append("")
    return lines


def replace_existing_toc(lines: List[str], toc_lines: List[str]) -> tuple[List[str], bool]:
    if not toc_lines:
        return lines, False

    i = 0
    while i < len(lines):
        match = HEADING_PATTERN.match(lines[i])
        if match and len(match.group(1)) == 2:
            heading_text = match.group(2).strip().lower().rstrip(":")
            if heading_text in {"table of contents", "table of content"}:
                start = i
                i += 1
                while i < len(lines) and not HEADING_PATTERN.match(lines[i]):
                    i += 1
                return lines[:start] + toc_lines + lines[i:], True
        i += 1

    return lines, False


def adjust_headings_and_build_toc(text: str, markdown_file: Path) -> str:
    text = text.replace("\u00a0", " ")
    lines = text.splitlines()
    if not lines:
        return text

    front_matter_lines: List[str] = []
    title_from_front_matter: str | None = None
    body_start = 0
    metadata: Dict[str, Any] | None = None
    metadata_order: List[str] = []
    quoted_keys: Set[str] = set()

    if lines and lines[0].strip() == "---":
        front_matter_lines.append(lines[0])
        for idx in range(1, len(lines)):
            front_matter_lines.append(lines[idx])
            if lines[idx].strip() == "---":
                body_start = idx + 1
                break
        else:
            body_start = len(lines)

        parsed = parse_front_matter_block(front_matter_lines)
        if parsed:
            metadata, metadata_order, quoted_keys = parsed
            title_raw = metadata.get("title")
            if isinstance(title_raw, str) and title_raw.strip():
                title_from_front_matter = title_raw.strip()
        else:
            metadata = None
    else:
        front_matter_lines = []

    body_lines = lines[body_start:]
    flatten_image_paths(markdown_file)
    body_lines = normalize_square_bullets(body_lines)
    body_lines = strip_part_links(body_lines)
    body_lines = convert_inline_em_dashes(body_lines)
    body_lines = strip_non_link_brackets(body_lines)
    body_lines = remove_empty_brackets(body_lines)
    body_lines = remove_vestigial_blocks(body_lines)
    body_lines = convert_dash_rules(body_lines)
    body_lines = remove_svg_blocks(body_lines)
    body_lines = fix_malformed_links(body_lines)
    body_lines = remove_empty_label_links(body_lines)
    body_lines = rewrite_markdown_image_paths(body_lines)
    body_lines = bold_uppercase_lines(body_lines)
    body_lines = ensure_blank_line_after_hyphen_lists(body_lines)
    body_lines = strip_redundant_escapes(body_lines)
    demoted_lines, toc_entries, first_heading_text = demote_headings(body_lines)
    toc_lines = build_toc_lines(toc_entries)
    demoted_lines, toc_replaced = replace_existing_toc(demoted_lines, toc_lines)

    body_text_for_isbn = "\n".join(body_lines)

    if metadata is not None:
        for drop_key in ("contributor", "description"):
            if drop_key in metadata:
                metadata.pop(drop_key, None)
                if drop_key in metadata_order:
                    metadata_order.remove(drop_key)
                quoted_keys.discard(drop_key)

        identifiers_raw = metadata.get("identifier")
        identifier_candidates: List[str] = []
        if isinstance(identifiers_raw, list):
            identifier_candidates.extend(str(item) for item in identifiers_raw)
        elif isinstance(identifiers_raw, str):
            identifier_candidates.append(identifiers_raw)

        isbn_value = extract_isbn(body_text_for_isbn, identifier_candidates)
        if not isbn_value and isinstance(metadata.get("isbn"), str):
            isbn_value = normalize_isbn(metadata.get("isbn"))
        if isbn_value:
            metadata["isbn"] = isbn_value
            quoted_keys.add("isbn")
            if isinstance(identifiers_raw, list):
                normalized_list = [str(item) for item in identifiers_raw]
                if isbn_value not in normalized_list and f"ISBN {isbn_value}" not in normalized_list:
                    normalized_list.append(f"ISBN {isbn_value}")
                metadata["identifier"] = normalized_list
            elif isinstance(identifiers_raw, str) and identifiers_raw:
                if identifiers_raw != isbn_value and identifiers_raw != f"ISBN {isbn_value}":
                    metadata["identifier"] = [identifiers_raw, f"ISBN {isbn_value}"]
                else:
                    metadata["identifier"] = [identifiers_raw]
            else:
                metadata["identifier"] = [f"ISBN {isbn_value}"]

        title_source: Optional[str] = None
        if isinstance(metadata.get("title"), str) and metadata["title"].strip():
            title_source = metadata["title"].strip()
        elif first_heading_text:
            metadata["title"] = first_heading_text
            title_source = first_heading_text
        if title_source and not metadata.get("title_short"):
            metadata["title_short"] = compute_title_short(title_source)
        if "title_short" in metadata and isinstance(metadata.get("title_short"), str):
            metadata["title_short"] = trim_title_short(metadata["title_short"])
            quoted_keys.add("title_short")

        front_matter_lines = serialize_front_matter(metadata, metadata_order, quoted_keys)

    metadata_title = None
    if metadata and isinstance(metadata.get("title"), str):
        metadata_title = metadata["title"].strip()
    title_text = title_from_front_matter or metadata_title or first_heading_text
    final_body: List[str] = []

    if title_text:
        final_body.append(f"# {title_text}".rstrip())
        final_body.append("")
        if toc_lines and not toc_replaced:
            final_body.extend(toc_lines)

    while demoted_lines and demoted_lines[0] == "" and final_body and final_body[-1] == "":
        demoted_lines = demoted_lines[1:]

    final_body.extend(demoted_lines)

    final_lines: List[str] = []
    if front_matter_lines:
        final_lines.extend(front_matter_lines)
        if final_body:
            final_lines.append("")
    final_lines.extend(final_body)

    return "\n".join(final_lines)


def collapse_blank_lines(text: str) -> str:
    return MULTI_BLANK_PATTERN.sub("\n\n", text)


def clean_markdown_text(text: str, markdown_file: Path, style_map: Dict[str, Set[str]]) -> str:
    # Remove inline anchors
    text = ANCHOR_PATTERN.sub("", text)
    # Drop empty link lines
    text = EMPTY_LINK_LINE_PATTERN.sub("", text)
    # Strip legacy internal double-bracket links targeting Calibre anchors
    def drop_legacy_link(match: re.Match[str]) -> str:
        target = match.group("target")
        if target.lower().startswith("#part") or target.lower().startswith("#toc"):
            return match.group("display")
        return match.group(0)

    text = LEGACY_DOUBLE_LINK_PATTERN.sub(drop_legacy_link, text)
    # Remove HTML comments
    text = HTML_COMMENT_PATTERN.sub("", text)
    # Remove any remaining double-bracket markup
    text = ORPHAN_DOUBLE_BRACKETS_PATTERN.sub(r"\1", text)
    # Apply class-based styling
    text = apply_pandoc_class_notation(text, style_map)
    text = apply_span_classes(text, style_map)
    text = convert_calibre_blocks(text)
    text = adjust_headings_and_build_toc(text, markdown_file)
    # Remove residual class braces and attributes
    text = CLASS_ONLY_BRACES_PATTERN.sub("", text)
    text = re.sub(r"\sclass=\"[^\"]+\"", "", text)
    # Collapse multiple blank lines
    text = collapse_blank_lines(text)
    # Normalise redundant image directory segments
    text = REDUNDANT_IMAGE_SEGMENT_PATTERN.sub("images/", text)
    # Trim trailing spaces on lines
    text = re.sub(r"[ \t]+\n", "\n", text)
    return text.strip() + "\n"


def process_file(path: Path, dry_run: bool) -> bool:
    original = path.read_text(encoding="utf-8")
    style_map = load_style_map(path)
    cleaned_text = clean_markdown_text(original, path, style_map)
    if cleaned_text == original:
        return False
    if dry_run:
        sys.stdout.write(cleaned_text)
    else:
        path.write_text(cleaned_text, encoding="utf-8")
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Clean Markdown artifacts")
    parser.add_argument("markdown_file", type=Path, help="Markdown file to clean")
    parser.add_argument("--dry-run", action="store_true", help="Preview output without writing")
    args = parser.parse_args(argv)

    if not args.markdown_file.exists():
        parser.error(f"File '{args.markdown_file}' does not exist")

    changed = process_file(args.markdown_file, args.dry_run)
    if changed and not args.dry_run:
        print(f"Updated {args.markdown_file}")
    elif not changed:
        print("No changes needed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
