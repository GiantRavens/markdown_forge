# design

The 'convert' folder will contain media that will be converted to various formats to make it easier for them to be searched, organized, and discovered for AI and OS level file search.

A general 'convert' script can be called that will in turn invoke smaller, more modular tools to perform more atomic functions such as:

- file type verification and extension correction
- publication publisher house extraction
- publication publication year extraction
- publication author or editor extraction
- publication ISBN, or LOC, or other identifier extraction
- publication title renaming in this order if present:
  - series name and number in numerals in proper titlecase
  - title and edition (without any subtitlespunctuation such as apostrophes, colons, parentheses, etc.) in proper titlecase
  - a conjunction marker of ' - '
  - the publisher name in proper titlecase without company names like 'Inc.', 'LLC', etc.
  - a conjunction of ' '
  - the publication year in numerals
  - a conjunction of ' '
  - the publication identifier type and value in numerals

A proper title might look like this:

  `Alternative Scriptwriting 4th edition by Ken Dancyger and Jeff Rush - Focal Press 2022 ISBN13 9780240808499.pdf`

- a description shall be determined for the documents content
- In the case of PDF's, the PDF document properties shall be reset for the title, author, subject, and keywords - if possible h1 (title), h2 (chapter titles), h3 (chapter section headers) with strict html semantic hierarchy.

A single 'media_convert' command shall be analyze the contents of the IN folder and take the appropriate actions, calling modular tools from the 'tools' folder as needed to perform its actions as needed.

## Tooling Overview

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

- **`tools/publication_cleanup.py`**
  - **Usage**: `python tools/publication_cleanup.py path/to/publication_dir [--dry-run]`
  - **Flags**:
    - `--dry-run` preview rename/move/delete operations without applying them.
  - **Primary Output**: Extracts Markdown front-matter metadata, renames the publication directory and key exports (`.md`, `.html`, `.epub`), moves the folder to the peer-level `OUT/` directory, prunes redundant asset subfolders, and removes the `source/` workspace inside the relocated publication. Reports actions taken or previewed.
