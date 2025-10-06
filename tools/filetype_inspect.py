#!/usr/bin/env python3
"""CLI tool to inspect and normalize file types.

Part of the `markdown_forge` framework.

For each input path this tool:
- gathers type hints from external utilities (`file`, `exiftool`, `ffprobe`)
- infers a canonical type/mime/extension
- optionally renames the file to the canonical extension and updates metadata

Usage:
    python tools/filetype_inspect.py <path> [<path> ...]

Flags:
    --info-only   Do not rename or modify metadata; report only.
    --recursive   Descend into directories when provided.
    --json        Emit machine-readable JSON (default pretty text summary).
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import shutil
import subprocess
import sys
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Map canonical types to preferred extension and mime type
TYPE_REGISTRY: Dict[str, Dict[str, str]] = {
    "epub": {"extension": "epub", "mime": "application/epub+zip"},
    "pdf": {"extension": "pdf", "mime": "application/pdf"},
    "txt": {"extension": "txt", "mime": "text/plain"},
    "md": {"extension": "md", "mime": "text/markdown"},
    "html": {"extension": "html", "mime": "text/html"},
}


@dataclass
class CommandResult:
    available: bool
    returncode: Optional[int]
    stdout: str = ""
    stderr: str = ""


@dataclass
class InspectionReport:
    path: Path
    file_type: Optional[str] = None
    mime_type: Optional[str] = None
    extension: Optional[str] = None
    inferred_from_zip: Optional[str] = None
    actions: Dict[str, str] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    file_cmd: Optional[CommandResult] = None
    exiftool_cmd: Optional[CommandResult] = None
    ffprobe_cmd: Optional[CommandResult] = None

    def to_dict(self) -> Dict[str, object]:
        data = {
            "path": str(self.path),
            "file_type": self.file_type,
            "mime_type": self.mime_type,
            "extension": self.extension,
            "inferred_from_zip": self.inferred_from_zip,
            "actions": self.actions,
            "warnings": self.warnings,
            "errors": self.errors,
        }
        if self.file_cmd:
            data["file"] = self.file_cmd.__dict__
        if self.exiftool_cmd:
            data["exiftool"] = self.exiftool_cmd.__dict__
        if self.ffprobe_cmd:
            data["ffprobe"] = self.ffprobe_cmd.__dict__
        return data


def run_command(args: List[str]) -> CommandResult:
    """Execute the given command and capture stdout/stderr for reporting."""
    executable = args[0]
    if shutil.which(executable) is None:
        return CommandResult(available=False, returncode=None, stdout="", stderr=f"{executable} not found")
    try:
        completed = subprocess.run(args, capture_output=True, text=True, check=False)
        return CommandResult(
            available=True,
            returncode=completed.returncode,
            stdout=completed.stdout.strip(),
            stderr=completed.stderr.strip(),
        )
    except Exception as exc:  # pragma: no cover - defensive
        return CommandResult(available=True, returncode=-1, stdout="", stderr=str(exc))


def parse_exiftool(stdout: str) -> Dict[str, str]:
    """Parse `exiftool` key/value output into a dictionary."""
    info: Dict[str, str] = {}
    for line in stdout.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        info[key.strip()] = value.strip()
    return info


def zip_epub_hint(path: Path) -> Optional[str]:
    """Inspect a ZIP container for the EPUB mimetype declaration."""
    if not path.is_file():
        return None
    try:
        with zipfile.ZipFile(path) as zf:
            try:
                data = zf.read("mimetype")
            except KeyError:
                return None
            mimetype_str = data.decode("utf-8", errors="ignore").strip()
            if mimetype_str:
                return mimetype_str
    except zipfile.BadZipFile:
        return None
    return None


def infer_type(path: Path, file_mime: Optional[str], exif_info: Dict[str, str], zip_hint: Optional[str]) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """Determine file type, MIME, and canonical extension using multiple hints."""
    # Priority order: ZIP hint -> file command -> exif info -> mimetypes guess
    mime = None
    file_type = None

    if zip_hint == "application/epub+zip":
        mime = zip_hint
        file_type = "epub"

    if not file_type and file_mime:
        mime = file_mime
        file_type = canonical_type_from_mime(file_mime)

    if not file_type:
        exif_type = exif_info.get("File Type") or exif_info.get("FileType")
        if exif_type:
            ft = exif_type.strip().lower()
            if ft in TYPE_REGISTRY:
                file_type = ft
                mime = TYPE_REGISTRY[ft]["mime"]
        exif_mime = exif_info.get("MIME Type") or exif_info.get("MIMEType")
        if not file_type and exif_mime:
            mime = exif_mime
            file_type = canonical_type_from_mime(exif_mime)

    if not file_type:
        # Fall back to Python's mimetypes on current name
        guess_mime, _ = mimetypes.guess_type(path.name)
        if guess_mime:
            mime = guess_mime
            file_type = canonical_type_from_mime(guess_mime)

    extension = None
    if file_type and file_type in TYPE_REGISTRY:
        extension = TYPE_REGISTRY[file_type]["extension"]
        mime = TYPE_REGISTRY[file_type]["mime"]
    elif mime:
        extension = extension_from_mime(mime)

    return file_type, mime, extension


def canonical_type_from_mime(mime: str) -> Optional[str]:
    """Translate a MIME string into a canonical type identifier when known."""
    mime = mime.lower()
    for key, meta in TYPE_REGISTRY.items():
        if meta["mime"].lower() == mime:
            return key
    if mime.startswith("text/markdown"):
        return "md"
    if mime.startswith("text/"):
        return "txt"
    if mime in {"application/zip", "application/x-zip-compressed"}:
        return "zip"
    return None


def extension_from_mime(mime: str) -> Optional[str]:
    """Return the preferred extension for the provided MIME type."""
    mime = mime.lower()
    for data in TYPE_REGISTRY.values():
        if data["mime"].lower() == mime:
            return data["extension"]
    guessed = mimetypes.guess_extension(mime)
    if guessed:
        return guessed.lstrip('.')
    return None


def maybe_rename(path: Path, wanted_extension: Optional[str], info_only: bool, report: InspectionReport) -> Path:
    """Rename the file to the canonical extension when appropriate."""
    if not wanted_extension:
        return path
    current_ext = path.suffix.lower().lstrip('.')
    if current_ext == wanted_extension.lower():
        return path
    target = path.with_suffix(f".{wanted_extension}")
    if target.exists() and target != path:
        report.warnings.append(f"Cannot rename to {target.name}; destination exists.")
        return path
    if info_only:
        report.actions["rename"] = f"would rename to {target.name}"
        return target
    try:
        path.rename(target)
        report.actions["rename"] = f"renamed to {target.name}"
        return target
    except Exception as exc:
        report.errors.append(f"Failed to rename: {exc}")
        return path


def update_metadata(path: Path, file_type: Optional[str], mime: Optional[str], info_only: bool, report: InspectionReport) -> None:
    """Refresh XMP metadata via `exiftool` when available."""
    if info_only or not mime:
        return
    if shutil.which("exiftool") is None:
        report.warnings.append("exiftool not available; metadata not updated")
        return
    args = [
        "exiftool",
        "-overwrite_original",
        f"-XMP:Format={mime}",
    ]
    if file_type and file_type.upper() not in {"ZIP", "UNKNOWN"}:
        args.append(f"-XMP-dc:Type={file_type.upper()}")
    args.append(str(path))
    result = run_command(args)
    report.exiftool_cmd = result
    if not result.available:
        report.warnings.append("exiftool command unavailable during metadata write")
        return
    if result.returncode != 0:
        report.warnings.append("exiftool failed to update metadata")
    else:
        report.actions["metadata"] = "updated XMP:Format"


def inspect_path(path: Path, info_only: bool) -> InspectionReport:
    """Run external probes against `path` and aggregate the results."""
    report = InspectionReport(path=path)

    file_cmd = run_command(["file", "-b", "--mime-type", str(path)])
    report.file_cmd = file_cmd
    file_mime = file_cmd.stdout if file_cmd.available and file_cmd.returncode == 0 else None

    exiftool_cmd = run_command(["exiftool", "-FileType", "-FileTypeExtension", "-MIMEType", str(path)])
    report.exiftool_cmd = exiftool_cmd
    exif_info = parse_exiftool(exiftool_cmd.stdout) if exiftool_cmd.available else {}

    ffprobe_cmd = run_command(["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", "-show_streams", str(path)])
    report.ffprobe_cmd = ffprobe_cmd

    zip_hint = zip_epub_hint(path)
    report.inferred_from_zip = zip_hint

    file_type, mime_type, extension = infer_type(path, file_mime, exif_info, zip_hint)
    report.file_type = file_type
    report.mime_type = mime_type
    report.extension = extension

    new_path = maybe_rename(path, extension, info_only, report)

    if new_path != path:
        report.path = new_path

    update_metadata(new_path, file_type, mime_type, info_only, report)

    return report


def iter_target_files(paths: List[Path], recursive: bool) -> List[Path]:
    """Expand provided paths into a flat file list, respecting recursion flag."""
    targets: List[Path] = []
    for item in paths:
        if item.is_dir():
            if recursive:
                for sub in item.rglob('*'):
                    if sub.is_file() and sub.name != ".DS_Store":
                        targets.append(sub)
            else:
                for sub in item.iterdir():
                    if sub.is_file() and sub.name != ".DS_Store":
                        targets.append(sub)
        elif item.is_file() and item.name != ".DS_Store":
            targets.append(item)
        else:
            continue
    return targets


def format_report(report: InspectionReport) -> str:
    """Render a human-readable summary for an `InspectionReport`."""
    lines = [f"Path: {report.path}"]
    lines.append(f"  Inferred type : {report.file_type or 'unknown'}")
    lines.append(f"  MIME type     : {report.mime_type or 'unknown'}")
    lines.append(f"  Extension     : {report.extension or 'n/a'}")
    if report.inferred_from_zip:
        lines.append(f"  ZIP mimetype  : {report.inferred_from_zip}")
    if report.actions:
        lines.append("  Actions       :")
        for key, value in report.actions.items():
            lines.append(f"    - {key}: {value}")
    if report.warnings:
        lines.append("  Warnings      :")
        for w in report.warnings:
            lines.append(f"    - {w}")
    if report.errors:
        lines.append("  Errors        :")
        for e in report.errors:
            lines.append(f"    - {e}")
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    """CLI entry point to inspect paths and optionally normalize file metadata."""
    parser = argparse.ArgumentParser(description="Inspect and normalize file types")
    parser.add_argument("paths", nargs="+", type=Path, help="Files or directories to inspect")
    parser.add_argument("--info-only", action="store_true", help="Do not rename or update metadata")
    parser.add_argument("--recursive", action="store_true", help="Recurse into directories")
    parser.add_argument("--json", dest="emit_json", action="store_true", help="Emit JSON output")

    args = parser.parse_args(argv)

    targets = iter_target_files(args.paths, args.recursive)
    if not targets:
        print("No files to inspect", file=sys.stderr)
        return 1

    reports = [inspect_path(path, info_only=args.info_only) for path in targets]

    if args.emit_json:
        payload = [r.to_dict() for r in reports]
        json.dump(payload, sys.stdout, indent=2)
        print()
    else:
        for rpt in reports:
            print(format_report(rpt))
            print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
