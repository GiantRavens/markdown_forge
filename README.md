# markdown_forge

markdown_forge is a publication "forge" that reshapes opaque EPUB and PDF sources into AI/ML/search and discover toolready Markdown and clean publication exports of same.

## Purpose

- **Discovery-focused**: Strip away EPUB/PDF quirks so OS indexers, LLM pipelines, and search tooling can surface content that would otherwise stay buried inside binary containers.
- **Canonical touchstone**: Normalize publications into a single Markdown file with enriched front matter (`title`, `title_short`, `author`, `publisher`, `year`, identifiers, etc.) that serves as the source of truth for downstream automation.
- **Repeatable derivatives**: Regenerate clean EPUBs and fully self-contained HTML (embedded Base64 imagery, inline CSS) directly from that canonical Markdown.

## Core workflow

1. Drop raw source files into `IN/`.
2. Run `python tools/convert_IN_preprocess.py` to inspect file types, route EPUBs and PDFs through the matching conversion/cleanup flow, and populate publication workspaces.
Generally, run either epub_to_markdown <target> or pdf_to_markdown <target>. Then run epub_markdown_cleanup <target md file> or pdf_markdown_cleanup <target md file> to clean up the generated Markdown as needed. You will very likely need to confirm the frontmatter manually, and do regex cleanup.  
3. Iterate on the generated Markdown within each publication directory until the content and metadata look correct.
4. The intent is that the core .md files always stay and can be continually improved - and use the publishing tools  to generate EPUB/HTML versions - 
5. When happy with the results, typically the core .md file with all images in a peer images directory, a self-contained .html file, and a clean .epub version, you can run publication_cleanup to move the .md and exponents into the OUT folder for further archiving. 

## Tool highlights

- **`tools/filetype_inspect.py`**: Probes files with `file`, `exiftool`, and `ffprobe`, suggests canonical extensions, and updates metadata so inputs are well-typed before conversion.
- **`tools/epub_folderize.py`** → **`tools/epub_to_markdown.py`** → **`tools/epub_markdown_cleanup.py`**: Unpack EPUBs, extract Markdown/images, strip custom CSS, collapse Pandoc/Calibre artifacts, and leave a clean publication folder anchored by Markdown front matter.
- **`tools/markdown_to_self_contained_html.py`**: Produces single-file HTML (embedded assets, inline CSS) from the canonical Markdown for maximum portability.
- **`tools/markdown_to_epub.py`**: Rebuilds EPUB containers from the same Markdown touchstone once cleanup is complete.
- **`tools/publication_cleanup.py`**: Renames publications and derivative assets based on front matter so `OUT/` stays organized.
- **PDF track**: `tools/pdf_to_markdown.py`, `tools/pdf_markdown_cleanup.py`, and `tools/acrobat-html_to_markdown.py` offer multiple paths—from direct PDF extraction to Acrobat HTML exports—for turning printed layouts into workable Markdown.

## Working with PDFs

- **Hybrid strategy**: Start with `tools/pdf_to_markdown.py` for direct extraction; if layout noise persists, export the PDF through Adobe Acrobat to HTML and run `tools/acrobat-html_to_markdown.py` for a cleaner baseline.
- **Prepare the source**: Crop print-oriented PDFs to remove headers/footers before conversion to avoid repeated page numbers or chapter labels bleeding into the text.
- **Fallback via images**: When text extraction proves unreliable, leverage the per-page images that `tools/pdf_to_markdown.py` emits under `source_pdf/extracted/`. Re-compose them into a PDF and run OCR to recover faithful text without Acrobat’s typical spacing and glyph anomalies.

## Repository layout

- **`tools/`**: Command-line utilities that implement the ingestion, cleanup, and publishing pipeline.
- **`IN/`** / **`OUT/`**: Working directories kept in version control via `.gitkeep` but emptied by default. Contents are ignored so personal source material never leaks into public history.
- **`DEV/`**: Design notes and process documentation (see `DEV/design.md`).
- **`requirements.txt`**: Minimum Python package requirements for the toolchain.

## Getting started

- **Install dependencies**: `python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt`
- **Process inputs**: Place EPUB/PDF files inside `IN/` and run the orchestrator or individual tools as needed.
- **Publish outputs**: Use the Markdown touchstone plus `tools/markdown_to_self_contained_html.py` and `tools/markdown_to_epub.py` to forge portable deliverables ready for AI/ML ingestion or general distribution.
