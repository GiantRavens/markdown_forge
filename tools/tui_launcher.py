from __future__ import annotations

import asyncio
import ast
import shlex
from dataclasses import dataclass
import os
import platform
import shutil
from pathlib import Path
from typing import Iterable, Optional

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import DirectoryTree, Footer, Header, ListItem, ListView, Static
from rich.text import Text

try:
    from textual.widgets import TextLog  # type: ignore[attr-defined]
except ImportError:  # pragma: no cover - compatibility for older Textual versions
    from textual.widgets import Log as TextLog  # type: ignore[attr-defined]


TOOL_SUFFIX_RULES: dict[str, Optional[frozenset[str]]] = {
    "acrobat-html_to_markdown": frozenset({".html", ".htm"}),
    "acrobat-pdf-markdown_cleanup": frozenset({".md"}),
    "convert_IN_preprocess": None,
    "epub_folderize": frozenset({".epub"}),
    "epub_markdown_cleanup": frozenset({".md"}),
    "epub_to_markdown": frozenset({".epub"}),
    "filetype_inspect": None,
    "markdown_to_epub": frozenset({".md"}),
    "markdown_to_self_contained_html": frozenset({".md"}),
    "pdf_markdown_cleanup": frozenset({".md"}),
    "pdf_to_markdown": frozenset({".pdf"}),
    "publication_cleanup": frozenset({".md"}),
    "toc_rebuilder": frozenset({".md"}),
}


@dataclass
class ToolEntry:
    name: str
    path: Path
    description: str
    suffixes: Optional[frozenset[str]]


def discover_tools(directory: Path) -> list[ToolEntry]:
    entries: list[ToolEntry] = []
    for path in sorted(directory.glob("*.py")):
        if path.name == Path(__file__).name:
            continue
        suffixes = TOOL_SUFFIX_RULES.get(path.stem)
        entries.append(
            ToolEntry(
                name=path.stem.replace("_", " ").title(),
                path=path,
                description=_read_description(path),
                suffixes=suffixes,
            )
        )
    return entries


def _read_description(path: Path) -> str:
    try:
        module = ast.parse(path.read_text("utf-8"))
    except Exception:
        return ""
    doc = ast.get_docstring(module)
    if not doc:
        return ""
    for line in doc.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return ""


class ToolItem(ListItem):
    def __init__(self, entry: ToolEntry) -> None:
        if entry.description:
            label_text = Text.assemble((entry.name, "bold"), (" - ", ""), (entry.description, ""))
        else:
            label_text = Text(entry.name, style="bold")
        super().__init__(Static(label_text))
        self.entry = entry
        self.applicable = True

    def set_applicable(self, value: bool) -> None:
        self.applicable = value
        self.set_class(not value, "dim")


class FileIconDirectoryTree(DirectoryTree):
    """DirectoryTree that prepends ASCII file-type tags to certain file names."""

    EXT_TAGS = {
        ".pdf": "[PDF] ",
        ".epub": "[EPUB] ",
        ".md": "[MD] ",
    }

    def render_label(self, node, label=None, *_, **__) -> Text:
        # Fallbacks to derive a Path for the node
        path: Path | None = None
        try:
            data = getattr(node, "data", None)
            if data is not None:
                raw_path = getattr(data, "path", None)
                if raw_path is None and isinstance(data, (str, Path)):
                    raw_path = data
                if raw_path is not None:
                    path = Path(str(raw_path))
        except Exception:
            path = None

        if path is None:
            try:
                # Prefer explicit label arg if provided by Textual
                label_obj = label if label is not None else getattr(node, "label", "")
                label_text = str(label_obj)
                if label_text:
                    path = Path(label_text)
            except Exception:
                path = None

        if path is not None and path.is_file():
            prefix = self.EXT_TAGS.get(path.suffix.lower(), "")
            label_text = f"{prefix}{path.name}"
            is_cursor = getattr(self, "cursor_node", None) is node
            return Text(label_text, style=("bold" if is_cursor else ""))

        # Directories or unknown nodes fall back to default rendering (name only)
        name = path.name if path is not None else str(getattr(node, "label", ""))
        if path is not None and path.exists() and path.is_dir():
            name = f"{name}/"
        is_cursor = getattr(self, "cursor_node", None) is node
        return Text(name, style=("bold" if is_cursor else ""))


class ToolRunnerApp(App[None]):
    CSS = """
    Screen {
        layout: vertical;
    }
    Horizontal {
        height: 1fr;
    }
    DirectoryTree {
        width: 50%;
        border: round $primary;
    }
    #right {
        border: round $surface;
        width: 50%;
        padding: 1 1;
    }
    #tool_list {
        height: auto;
    }
    #command {
        padding: 1 0 0 0;
    }
    #log {
        height: 1fr;
        border: round $boost;
        padding: 1 1;
    }
    .dim {
        color: $text-muted;
    }
    """

    BINDINGS = [
        Binding("enter", "select_focus", "Select"),
        Binding("tab", "switch_panels", "Switch"),
        Binding("r", "refresh", "Refresh"),
        Binding("o", "open", "Open"),
        Binding("e", "run_tool", "Run"),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(self, root_path: Path | None = None, tools_path: Path | None = None) -> None:
        super().__init__()
        self.root_path = root_path or Path.cwd()
        self.tools_path = tools_path or Path(__file__).resolve().parent
        self.entries = discover_tools(self.tools_path)
        self.selected_path: Path | None = None
        self.selected_tool: ToolEntry | None = None

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal():
            yield FileIconDirectoryTree(str(self.root_path), id="tree")
            with Vertical(id="right"):
                yield Static("Tools", classes="title")
                items = [ToolItem(entry) for entry in self.entries]
                yield ListView(*items, id="tool_list")
                yield Static("Command", id="command")
                yield Static("Select a file and tool", id="command_preview")
                yield TextLog(id="log", highlight=True)
        yield Footer()

    def on_mount(self) -> None:
        # Ensure the directory tree has focus for arrow-key navigation
        try:
            tree = self.query_one("#tree", DirectoryTree)
            self.set_focus(tree)
        except Exception:
            pass

        list_view = self.query_one(ListView)
        if list_view.children:
            list_view.index = 0
            self.selected_tool = list_view.children[0].entry  # type: ignore[attr-defined]
            self._update_command_preview()

    def on_directory_tree_file_selected(self, event: DirectoryTree.FileSelected) -> None:
        self.selected_path = Path(event.path)
        self._update_tool_filter()
        self._update_command_preview()

    def on_directory_tree_directory_selected(self, event: DirectoryTree.DirectorySelected) -> None:
        self.selected_path = Path(event.path)
        self._update_tool_filter()
        self._update_command_preview()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        item = event.item
        if isinstance(item, ToolItem):
            self.selected_tool = item.entry
            self._update_command_preview()

    def _update_command_preview(self) -> None:
        preview = self.query_one("#command_preview", Static)
        if not self.selected_path or not self.selected_tool:
            preview.update("Select a file and tool")
            return
        command = self._build_command(self.selected_tool, self.selected_path)
        preview.update(" ".join(shlex.quote(part) for part in command))

    def _update_tool_filter(self) -> None:
        list_view = self.query_one(ListView)
        target = self.selected_path
        suffix = target.suffix.lower() if target and target.is_file() else None
        for child in list_view.children:
            if not isinstance(child, ToolItem):
                continue
            applicable = True
            if suffix and child.entry.suffixes is not None:
                applicable = suffix in child.entry.suffixes
            child.set_applicable(applicable)
        # Update selection to first applicable tool
        applicable_items = [item for item in list_view.children if isinstance(item, ToolItem) and item.applicable]
        if applicable_items:
            index = list_view.children.index(applicable_items[0])
            list_view.index = index
            self.selected_tool = applicable_items[0].entry
        else:
            self.selected_tool = None

    def _build_command(self, tool: ToolEntry, target: Path) -> list[str]:
        return ["python", str(tool.path), str(target)]

    async def action_run_tool(self) -> None:
        log = self.query_one(TextLog)
        log.clear()
        if not self.selected_tool or not self.selected_path:
            log.write("Select a file and tool before running")
            return
        # Prevent concurrent runs
        if getattr(self, "_is_running", False):
            log.write("A tool is already running; please wait...")
            return
        self._is_running = True
        command = self._build_command(self.selected_tool, self.selected_path)
        cmd_str = " ".join(shlex.quote(part) for part in command)
        log.write(f"Running: {cmd_str}")
        start = asyncio.get_event_loop().time()
        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            assert process.stdout is not None
            while True:
                line = await process.stdout.readline()
                if not line:
                    break
                log.write(line.decode().rstrip())
            await process.wait()
            code = process.returncode
            elapsed = asyncio.get_event_loop().time() - start
            if code == 0:
                log.write(f"Completed successfully in {elapsed:.2f}s")
                # Auto-refresh to reflect any new/changed outputs
                await self.action_refresh()
            else:
                log.write(f"Failed with exit code {code} in {elapsed:.2f}s")
        finally:
            self._is_running = False

    def _current_tree_path(self) -> Path | None:
        try:
            tree = self.query_one("#tree", DirectoryTree)
        except Exception:
            return None
        node = getattr(tree, "cursor_node", None)
        if not node:
            return None
        path: Path | None = None
        try:
            data = getattr(node, "data", None)
            if data is not None:
                raw_path = getattr(data, "path", None)
                if raw_path is None and isinstance(data, (str, Path)):
                    raw_path = data
                if raw_path is not None:
                    path = Path(str(raw_path))
        except Exception:
            path = None
        return path

    async def _open_with_system(self, path: Path) -> None:
        system = platform.system().lower()
        if system.startswith("darwin") or system == "darwin":
            await asyncio.create_subprocess_exec("open", str(path))
            return
        if system.startswith("windows"):
            await asyncio.create_subprocess_exec("cmd", "/c", "start", str(path))
            return
        # Linux and others
        opener = shutil.which("xdg-open") or shutil.which("gio")
        if opener:
            if os.path.basename(opener) == "gio":
                await asyncio.create_subprocess_exec(opener, "open", str(path))
            else:
                await asyncio.create_subprocess_exec(opener, str(path))
            return

    async def _open_markdown_in_terminal(self, path: Path) -> bool:
        # Try common terminal emulators
        candidates: list[list[str]] = []
        term = shutil.which("x-terminal-emulator")
        if term:
            candidates.append([term, "-e", "nvim", str(path)])
        for name, args in [
            ("gnome-terminal", ["--", "nvim", str(path)]),
            ("konsole", ["-e", "nvim", str(path)]),
            ("xfce4-terminal", ["-e", "nvim", str(path)]),
            ("kitty", ["nvim", str(path)]),
            ("alacritty", ["-e", "nvim", str(path)]),
            ("wezterm", ["start", "nvim", str(path)]),
            ("tilix", ["-e", "nvim", str(path)]),
            ("mate-terminal", ["-e", "nvim", str(path)]),
            ("urxvt", ["-e", "nvim", str(path)]),
            ("xterm", ["-e", "nvim", str(path)]),
        ]:
            exe = shutil.which(name)
            if exe:
                candidates.append([exe] + args)
        for cmd in candidates:
            try:
                await asyncio.create_subprocess_exec(*cmd)
                return True
            except Exception:
                continue
        return False

    async def action_open(self) -> None:
        # Determine current path from tree cursor, fall back to last selected path
        path = self._current_tree_path() or self.selected_path
        if not path:
            return
        if path.is_dir():
            return
        suffix = path.suffix.lower()
        if suffix in {".pdf", ".epub"}:
            await self._open_with_system(path)
            return
        if suffix == ".md":
            if shutil.which("nvim") and os.environ.get("DISPLAY"):
                used = await self._open_markdown_in_terminal(path)
                if used:
                    return
            await self._open_with_system(path)
            return
        # Default: system open
        await self._open_with_system(path)

    async def action_refresh(self) -> None:
        # Rebuild the directory tree from root_path
        try:
            old_tree = self.query_one("#tree", DirectoryTree)
        except Exception:
            return
        parent = old_tree.parent
        if parent is None:
            return
        # Preserve current selection if possible
        selected = self.selected_path
        # Record current index to preserve panel position
        try:
            siblings = list(parent.children)
            index = siblings.index(old_tree)
        except Exception:
            index = 0
        try:
            await old_tree.remove()
        except Exception:
            # Fallback to synchronous removal if needed
            old_tree.remove()
        new_tree = FileIconDirectoryTree(str(self.root_path), id="tree")
        # Determine sibling to mount before, based on original index
        current_children = list(parent.children)
        before_widget = current_children[index] if 0 <= index < len(current_children) else None
        if before_widget is not None:
            await parent.mount(new_tree, before=before_widget)
        else:
            await parent.mount(new_tree)
        # Re-emit selection update
        if selected and selected.exists():
            self.selected_path = selected
            self._update_tool_filter()
            self._update_command_preview()

    async def action_select_focus(self) -> None:
        # Select current highlighted file (if any) and focus tools list
        path = self._current_tree_path()
        if path:
            self.selected_path = path
            self._update_tool_filter()
            self._update_command_preview()
        try:
            tool_list = self.query_one(ListView)
            self.set_focus(tool_list)
        except Exception:
            pass

    async def action_switch_panels(self) -> None:
        # Toggle focus between the DirectoryTree and the tool ListView
        try:
            focused = self.focused
            tree = self.query_one("#tree", DirectoryTree)
            tool_list = self.query_one(ListView)
        except Exception:
            return
        if focused is tree:
            self.set_focus(tool_list)
        else:
            self.set_focus(tree)


def main(args: Iterable[str] | None = None) -> None:
    root = Path.cwd()
    tools_dir = Path(__file__).resolve().parent
    app = ToolRunnerApp(root_path=root, tools_path=tools_dir)
    app.run()


if __name__ == "__main__":
    main()
