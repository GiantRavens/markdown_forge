# design

## Overall goal

The `markdown_forge/` workspace standardizes EPUB and PDF publications so they can be parsed, enriched, and redistributed. Clean Markdown becomes the canonical source for:

- **AI/ML discovery and vectorization** (LLM embeddings, semantic retrieval, fine-tuning datasets).
- **Human browsing and OS-level search** (descriptive filenames, metadata, accessible HTML/EPUB exports).
- **Repeatable publishing workflows** that regenerate derivative assets without manual rework.

## Core workflow

- **Intake**: Drop raw EPUB/PDF files into the `IN/` directory.
- **Preprocess**: Run `python tools/convert_IN_preprocess.py` to orchestrate detection, conversion, and cleanup. Individual tools can be run ad hoc when deeper control is required.
- **Canonicalize**: Treat the generated Markdown (and its front matter) as the single source of truth for edits, metadata, and downstream automation.
- **Enrich & iterate**: Apply cleanup utilities, augment metadata, and feed Markdown to AI/ML pipelines or vector stores for discovery tasks.
- **Publish**: Regenerate distributable assets on demand via `tools/markdown_to_self_contained_html.py` and `tools/markdown_to_epub.py`. Use `tools/publication_cleanup.py` to stage finished publications in `OUT/`.

## Tooling overview

Each script in `tools/` tackles a focused part of the pipeline. Use them individually or via the `convert_IN_preprocess.py` orchestrator inside the `markdown_forge` framework.

### Individual tools

- **`tools/filetype_inspect.py`**
  - **Usage**: `python tools/filetype_inspect.py PATH [PATH ...]`
    - `--info-only` preview actions without renaming or metadata writes.
    - `--recursive` traverse into provided directories.
    - `--json` emit machine-readable inspection output.
  - **Primary Output**: Pretty text summary per file (path, inferred type/mime/actions) or JSON payload when requested. Renames files to canonical extensions and updates XMP metadata when appropriate.

- **`tools/epub_folderize.py`**
  - **Usage**: `python tools/epub_folderize.py path/to/book.epub [--dest DIR] [--force]`
  - **Flags**:
    - `--dest` override the destination root (defaults to EPUB parent).
    - `--force` replace an existing folderized workspace.
  - **Primary Output**: Creates `<dest>/<slug>/source/` containing the original EPUB and an unpacked `extracted/` tree, printing the destination folder path.

- **`tools/epub_to_markdown.py`**
  - **Usage**: `python tools/epub_to_markdown.py BOOK_ROOT_OR_EPUB_PATH [--force]`
  - **Flags**:
    - `--force` overwrite existing `images/` directory and Markdown output.
  - **Primary Output**: Generates cleaned Markdown (`TITLE.md`) plus an `images/` directory, ensures cover art is present, and reports created paths.

- **`tools/markdown_cleanup.py`**
  - **Usage**: `python tools/markdown_cleanup.py path/to/file.md [--dry-run]`
  - **Flags**:
    - `--dry-run` write transformed Markdown to stdout without modifying the file.
  - **Primary Output**: Cleans Pandoc/Calibre artifacts, redundant escapes, unresolved anchors, and normalizes em-dashes and bullet markers. Prints a confirmation such as "Updated path/to/file.md" or "No changes needed".

- **`tools/markdown_to_self_contained_html.py`**
  - **Usage**: `python tools/markdown_to_self_contained_html.py SOURCE.md [--output OUTPUT.html] [--title TEXT] [--pandoc PATH]`
  - **Flags**:
    - `--output/-o` set destination HTML file.
    - `--title` override HTML title metadata.
    - `--pandoc` specify the pandoc executable.
  - **Primary Output**: Writes a single-page, asset-embedded HTML document and reports the written file path.

- **`tools/markdown_to_epub.py`**
  - **Usage**: `python tools/markdown_to_epub.py SOURCE.md [--output OUTPUT.epub] [--title TEXT] [--author TEXT] [--cover-image PATH] [--chapter-level N] [--pandoc PATH]`
  - **Flags**:
    - `--output/-o` choose EPUB destination (defaults to replacing `.md`).
    - `--title` / `--author` override metadata.
    - `--cover-image` embed a specific cover asset.
    - `--chapter-level` control heading level splits.
    - `--pandoc` select pandoc binary.
  - **Primary Output**: Builds a styled EPUB honoring front matter metadata and prints processing errors or exits with success.

- **`tools/pdf_to_markdown.py`**
  - **Usage**: `python tools/pdf_to_markdown.py path/to/file.pdf [--dest DIR] [--force] [--dpi N] [--margin-top PTS] [--margin-bottom PTS] [--min-repeat N] [--skip-pattern REGEX]`
  - **Flags**:
    - `--dest` override the workspace root (default: PDF parent directory).
    - `--force` replace an existing workspace.
    - `--margin-top` / `--margin-bottom` define header/footer detection bands (points).
    - `--min-repeat` controls how often a header/footer must repeat before removal.
    - `--skip-pattern` append additional regex filters for footer/header cleanup.
  - **Primary Output**: Moves the PDF into `source_pdf/`, writes `<slug>.md` with filtered text content, and stores page images as `source_pdf/extracted/page-####.png`.

- **`tools/epub_markdown_cleanup.py`**
  - **Usage**: `python tools/epub_markdown_cleanup.py path/to/file.md [--dry-run]`
  - **Flags**:
    - `--dry-run` preview output without writing.
  - **Primary Output**: Removes Calibre attribute blocks, normalizes headings/TOC, drops front-matter `contributor`/`description` entries, trims `title_short` after colons/dashes, deletes colon-prefixed block directives, converts long dash rules to `<hr>`, strips early SVG cover fragments, flattens `images/OEBPS/` assets into `images/`, rewrites image references, fixes malformed nested links, and cleans redundant anchors/classes from Pandoc EPUB conversions.

- **`tools/convert_IN_preprocess.py`**
  - **Usage**: `python tools/convert_IN_preprocess.py [--in-dir DIR] [--dry-run]`
  - **Flags**:
    - `--in-dir` override the default `IN/` directory root.
  - **Primary Output**: Iterates top-level EPUB/PDF files in `IN/`, runs `filetype_inspect.py`, converts via `epub_to_markdown.py` or `pdf_to_markdown.py`, and applies the matching cleanup tool. Logs progress and surfaces any command failures.

- **`tools/publication_cleanup.py`**
  - **Usage**: `python tools/publication_cleanup.py path/to/publication_dir [--dry-run]`
  - **Flags**:
    - `--dry-run` preview rename/move/delete operations without applying them.
  - **Primary Output**: Extracts Markdown front-matter metadata, renames the publication directory and key exports (`.md`, `.html`, `.epub`), moves the folder to the peer-level `OUT/` directory, prunes redundant asset subfolders, and removes the `source/` workspace inside the relocated publication. Reports actions taken or previewed.
