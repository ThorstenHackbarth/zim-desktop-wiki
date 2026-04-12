# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running Zim

No build step is required. Run directly from source:

```bash
./zim.py
```

## Testing

```bash
# Run the full test suite
./test.py

# Run a specific test module (from tests/)
./test.py formats
./test.py pageview

# Run with faster/stricter options
./test.py --fast        # skip slow tests, mock filesystem
./test.py --failfast    # stop on first failure
./test.py --ff          # both --fast and --failfast

# Coverage report (requires 'coverage' module)
./test.py --coverage    # outputs HTML to ./coverage/
```

## Code Style

- **Indentation: TABs, not spaces** (tabstop = 4 spaces). This is intentional and overrides PEP8.
- Signal handlers use `do_` prefix (same-class signals) or `on_` prefix (cross-class signals).
- Only use `assert` for checks that could be removed when code is stable.

## Architecture Overview

### Entry point and command dispatch

`zim.py` → `zim.main.main()` → constructs a `Command` subclass → either connects to a running zim instance via D-Bus or executes the command directly.

### Core layers

**Notebook** (`zim/notebook/`): The central data model. `Notebook` manages pages, attachments, and storage. It works with an `Index` (SQLite database in `zim/notebook/index/`) that caches page metadata for fast lookup and navigation. Pages are stored as plain text files; the layout is determined by `NotebookLayout`.

**Formats** (`zim/formats/`): Parsers and serializers for wiki text. Each format module defines exactly one `ParserClass` and one `DumperClass` subclass. The intermediate representation is an ElementTree-like parse tree (see `zim/formats/__init__.py` for the full tag schema). Key formats: `wiki` (native), `markdown`, `html`, `latex`.

**GUI** (`zim/gui/`): Built on GTK3 via PyGObject. The main window is in `zim/gui/mainwindow.py`. The page editor is `zim/gui/pageview/` — a complex GTK `TextView`-based component with a custom `TextBuffer` (`textbuffer.py`) that maintains the parse tree. `zim/gui/notebookview.py` wraps the main browsable notebook UI.

**Plugins** (`zim/plugins/`): Sub-modules of `zim.plugins`. Each plugin defines one `PluginClass` subclass and one or more extension classes that decorate application objects. Extensions are auto-instantiated when target objects are created. User-installed plugins live in `~/.local/share/zim/plugins/`.

**Signals** (`zim/signals.py`): Zim's own signal system layered on top of GObject. Non-GObject classes that need signals use `SignalEmitter`. Classes that connect to signals use `ConnectorMixin` (tracks connections for cleanup). Use `@SignalHandler` decorator for handlers that need blocking support.

**Config** (`zim/config/`): XDG-based config file handling. `ConfigManager` is the application-wide entry point. `INIConfigFile` wraps config files. Plugin preferences and notebook properties flow through the config system.

### Extension points for plugins

Find extendable classes by searching for the `@extendable` decorator. Key extension base classes:
- `NotebookExtension` — notebook data/index signals
- `PageViewExtension` — editor window, side panes
- `NotebookViewExtension` — main window with navigation (not single-page windows)
- `MainWindowExtension` — other main window changes
- `InsertedObjectTypeExtension` — inline object types (equations, diagrams, tables)

### Parse tree

Pages flow through: raw text file → `ParserClass` → ElementTree parse tree → `DumperClass` → output format. The GTK `TextBuffer` also maintains a live version of the parse tree while editing. The tree uses HTML-like tags; full schema is documented in `zim/formats/__init__.py`.

## Active Feature Branch

Currently on `feature/26-Support_markdown`. Changes add native markdown notebook support, affecting `zim/formats/markdown.py`, `zim/notebook/`, `zim/gui/pageview/textview.py`, and related tests.
