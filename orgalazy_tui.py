#!/usr/bin/env python3
"""
orgalazy_tui.py — Interactive text interface (TUI) for Orgalazy.

Must be placed in the same folder as orgalazy.py (direct import).
Standard library only (curses has shipped with Linux/macOS for ages).

Usage:
    python3 orgalazy_tui.py

Navigation:
    Up/Down arrows : move
    Enter          : select / expand a category
    Space          : toggle an option
    a              : apply the planned actions (from the preview screen)
    q / Escape     : back / quit

A "Help" screen is available from the main menu.
"""

from __future__ import annotations

import curses
import sys
from pathlib import Path

import orgalazy


# --------------------------------------------------------------------------
# ASCII art
# --------------------------------------------------------------------------

ASCII_ART = [
    r" ██████╗ ██████╗  ██████╗  █████╗ ██╗      █████╗ ███████╗██╗   ██╗",
    r"██╔═══██╗██╔══██╗██╔════╝ ██╔══██╗██║     ██╔══██╗╚══███╔╝╚██╗ ██╔╝",
    r"██║   ██║██████╔╝██║  ███╗███████║██║     ███████║  ███╔╝  ╚████╔╝ ",
    r"██║   ██║██╔══██╗██║   ██║██╔══██║██║     ██╔══██║ ███╔╝    ╚██╔╝  ",
    r"╚██████╔╝██║  ██║╚██████╔╝██║  ██║███████╗██║  ██║███████╗   ██║   ",
    r" ╚═════╝ ╚═╝  ╚═╝ ╚═════╝ ╚═╝  ╚═╝╚══════╝╚═╝  ╚═╝╚══════╝   ╚═╝   ",
]
ASCII_ART_WIDTH = max(len(line) for line in ASCII_ART)


# --------------------------------------------------------------------------
# Application state
# --------------------------------------------------------------------------

class AppState:
    def __init__(self) -> None:
        self.target_dir_str: str = str(Path.home() / "Downloads")
        self.recursive: bool = False
        self.dedupe: bool = True
        self.by_date: bool = False
        self.include_hidden: bool = False
        self.exclude_str: str = ""
        self.config_path_str: str = ""
        self.actions: list[orgalazy.Action] = []


# --------------------------------------------------------------------------
# Small curses display helpers
# --------------------------------------------------------------------------

def safe_addstr(win, y: int, x: int, text: str, attr=0) -> None:
    """Avoid crashes when text is wider than the window (terminal too small)."""
    max_y, max_x = win.getmaxyx()
    if y < 0 or y >= max_y or x >= max_x:
        return
    try:
        win.addstr(y, x, text[: max(0, max_x - x - 1)], attr)
    except curses.error:
        pass


def prompt_text(stdscr, prompt: str, initial: str = "") -> str | None:
    """Show an input prompt at the bottom of the screen. Return None if cancelled (Escape)."""
    curses.curs_set(1)
    max_y, _max_x = stdscr.getmaxyx()
    y = max_y - 2
    text = initial
    while True:
        stdscr.move(y, 0)
        stdscr.clrtoeol()
        safe_addstr(stdscr, y, 0, f"{prompt}{text}", curses.A_BOLD)
        stdscr.refresh()
        ch = stdscr.getch()
        if ch in (curses.KEY_ENTER, 10, 13):
            curses.curs_set(0)
            return text
        elif ch == 27:  # Escape
            curses.curs_set(0)
            return None
        elif ch in (curses.KEY_BACKSPACE, 127, 8):
            text = text[:-1]
        elif 32 <= ch <= 126:
            text += chr(ch)


def show_message(stdscr, lines: list[str], title: str = "") -> None:
    """Show a simple message and wait for a key press."""
    stdscr.clear()
    y = 1
    if title:
        safe_addstr(stdscr, y, 2, title, curses.A_BOLD | curses.A_UNDERLINE)
        y += 2
    for line in lines:
        safe_addstr(stdscr, y, 2, line)
        y += 1
    safe_addstr(stdscr, y + 1, 2, "-- Press any key to continue --", curses.A_DIM)
    stdscr.refresh()
    stdscr.getch()


# --------------------------------------------------------------------------
# Screens
# --------------------------------------------------------------------------

def screen_main_menu(stdscr, state: AppState) -> str:
    """Main menu. Return the chosen action: 'scan', 'undo', 'help', 'quit'."""
    items = [
        ("Scan a folder", "scan"),
        ("Undo last applied run", "undo"),
        ("Help", "help"),
        ("Quit", "quit"),
    ]
    selected = 0
    curses.curs_set(0)

    while True:
        stdscr.clear()
        max_y, max_x = stdscr.getmaxyx()
        y = 1

        if max_x >= ASCII_ART_WIDTH + 4:
            x = max(0, (max_x - ASCII_ART_WIDTH) // 2)
            for line in ASCII_ART:
                safe_addstr(stdscr, y, x, line, curses.A_BOLD)
                y += 1
            y += 1
        else:
            safe_addstr(stdscr, y, 2, "=== ORGALAZY ===", curses.A_BOLD)
            y += 2

        subtitle = "File organizer by category — safe, dependency-free, no surprises"
        safe_addstr(stdscr, y, max(0, (max_x - len(subtitle)) // 2), subtitle, curses.A_DIM)
        y += 2

        for i, (label, _) in enumerate(items):
            attr = curses.A_REVERSE if i == selected else 0
            safe_addstr(stdscr, y + i, 4, f"  {label}", attr)

        safe_addstr(stdscr, y + len(items) + 2, 2, "↑↓ navigate · Enter select · q quit", curses.A_DIM)
        stdscr.refresh()

        ch = stdscr.getch()
        if ch in (curses.KEY_UP, ord("k")):
            selected = (selected - 1) % len(items)
        elif ch in (curses.KEY_DOWN, ord("j")):
            selected = (selected + 1) % len(items)
        elif ch in (curses.KEY_ENTER, 10, 13):
            return items[selected][1]
        elif ch in (ord("q"), 27):
            return "quit"


def screen_help(stdscr) -> None:
    lines = [
        "SCAN A FOLDER",
        "  1. Choose the target folder and options (recursive, duplicates, exclusions).",
        "  2. The scan is a SIMULATION: nothing changes until you apply it.",
        "  3. In the preview, expand a category to see the files involved.",
        "  4. Press 'a' to apply for real (confirmation required).",
        "",
        "UNDO",
        "  Restore files from an applied run to their original location.",
        "  Requires the same folder that was used for the applied scan.",
        "",
        "GLOBAL SHORTCUTS",
        "  Arrows / j k      : move",
        "  Enter             : confirm / expand",
        "  Space             : toggle an option",
        "  a                 : apply (preview screen)",
        "  q / Escape        : back / cancel input",
    ]
    show_message(stdscr, lines, "Help")


def screen_setup(stdscr, state: AppState) -> bool:
    """Scan setup screen. Return False if cancelled."""
    options = [
        ("Target folder", "dir"),
        ("Recursive (subfolders)", "recursive"),
        ("Detect duplicates", "dedupe"),
        ("Group by date (YYYY-MM)", "by_date"),
        ("Include hidden files", "include_hidden"),
        ("Exclude (space-separated names)", "exclude"),
        ("Custom config (JSON, optional)", "config"),
        (">>> Start scan", "scan"),
    ]
    selected = 0

    while True:
        stdscr.clear()
        safe_addstr(stdscr, 1, 2, "=== Scan setup ===", curses.A_BOLD)

        for i, (label, key) in enumerate(options):
            attr = curses.A_REVERSE if i == selected else 0
            if key == "dir":
                value = state.target_dir_str
            elif key == "recursive":
                value = "[x]" if state.recursive else "[ ]"
            elif key == "dedupe":
                value = "[x]" if state.dedupe else "[ ]"
            elif key == "by_date":
                value = "[x]" if state.by_date else "[ ]"
            elif key == "include_hidden":
                value = "[x]" if state.include_hidden else "[ ]"
            elif key == "exclude":
                value = state.exclude_str or "(none)"
            elif key == "config":
                value = state.config_path_str or "(default categories)"
            else:
                value = ""
            safe_addstr(stdscr, 4 + i, 4, f"{label:<38} {value}", attr)

        safe_addstr(stdscr, 4 + len(options) + 2, 2,
                    "↑↓ navigate · Enter edit/confirm · Space toggle · q back", curses.A_DIM)
        stdscr.refresh()

        ch = stdscr.getch()
        key = options[selected][1]

        if ch in (curses.KEY_UP, ord("k")):
            selected = (selected - 1) % len(options)
        elif ch in (curses.KEY_DOWN, ord("j")):
            selected = (selected + 1) % len(options)
        elif ch == ord(" "):
            if key == "recursive":
                state.recursive = not state.recursive
            elif key == "dedupe":
                state.dedupe = not state.dedupe
            elif key == "by_date":
                state.by_date = not state.by_date
            elif key == "include_hidden":
                state.include_hidden = not state.include_hidden
        elif ch in (curses.KEY_ENTER, 10, 13):
            if key == "dir":
                result = prompt_text(stdscr, "Target folder: ", state.target_dir_str)
                if result is not None:
                    state.target_dir_str = result
            elif key == "exclude":
                result = prompt_text(stdscr, "Exclude (e.g. ProjectX Archive): ", state.exclude_str)
                if result is not None:
                    state.exclude_str = result
            elif key == "config":
                result = prompt_text(stdscr, "Config JSON file path: ", state.config_path_str)
                if result is not None:
                    state.config_path_str = result
            elif key == "recursive":
                state.recursive = not state.recursive
            elif key == "dedupe":
                state.dedupe = not state.dedupe
            elif key == "by_date":
                state.by_date = not state.by_date
            elif key == "include_hidden":
                state.include_hidden = not state.include_hidden
            elif key == "scan":
                return True
        elif ch in (ord("q"), 27):
            return False


def run_scan(stdscr, state: AppState) -> str | None:
    """Run plan_actions(). Return an error message, or None on success."""
    target_dir = Path(state.target_dir_str).expanduser().resolve()
    if not target_dir.exists() or not target_dir.is_dir():
        return f"The folder '{target_dir}' does not exist or is not a folder."

    exclude = set(state.exclude_str.split()) if state.exclude_str.strip() else set()

    categories = orgalazy.DEFAULT_CATEGORIES
    if state.config_path_str.strip():
        config_path = Path(state.config_path_str).expanduser().resolve()
        if not config_path.exists():
            return f"Config file not found: '{config_path}'."
        try:
            data = orgalazy.json.loads(config_path.read_text(encoding="utf-8"))
            categories = orgalazy.validate_categories(data)
        except (OSError, orgalazy.json.JSONDecodeError, ValueError) as e:
            return f"Could not read config: {e}"

    try:
        state.actions = orgalazy.plan_actions(
            target_dir=target_dir,
            categories=categories,
            dedupe=state.dedupe,
            recursive=state.recursive,
            exclude=exclude,
            layout="date" if state.by_date else "type",
            include_hidden=state.include_hidden,
        )
    except OSError as e:
        return f"Error during scan: {e}"

    return None


def screen_preview(stdscr, state: AppState) -> None:
    """
    Preview screen: browse categories, show the files involved, and apply the
    actions for real with 'a'.
    """
    target_dir = Path(state.target_dir_str).expanduser().resolve()

    if not state.actions:
        show_message(stdscr, ["No files to process (already organized, or empty folder)."], "Preview")
        return

    # Group by category
    by_category: dict[str, list[orgalazy.Action]] = {}
    for action in state.actions:
        by_category.setdefault(action.category, []).append(action)

    categories = sorted(by_category.keys())
    cat_selected = 0
    expanded: str | None = None   # category currently expanded
    file_selected = 0

    while True:
        stdscr.clear()
        safe_addstr(stdscr, 1, 2, f"=== Preview: {target_dir} ===", curses.A_BOLD)
        total = len(state.actions)
        safe_addstr(stdscr, 2, 2, f"{total} planned action(s) — SIMULATION, nothing changed yet", curses.A_DIM)

        y = 4
        for i, cat in enumerate(categories):
            count = len(by_category[cat])
            is_cat_selected = (i == cat_selected and expanded is None)
            attr = curses.A_REVERSE if is_cat_selected else curses.A_BOLD
            prefix = "▼" if expanded == cat else "▶"
            safe_addstr(stdscr, y, 4, f"{prefix} {cat} ({count} file(s))", attr)
            y += 1

            if expanded == cat:
                for j, action in enumerate(by_category[cat]):
                    is_file_selected = (j == file_selected)
                    attr = curses.A_REVERSE if is_file_selected else 0
                    tag = "[duplicate] " if action.kind == "duplicate" else ""
                    line = f"    {tag}{action.src.name}"
                    safe_addstr(stdscr, y, 4, line, attr)
                    y += 1
                    if y >= curses.LINES - 4:
                        break

        help_y = curses.LINES - 3
        safe_addstr(stdscr, help_y, 2,
                    "↑↓ navigate · Enter expand/collapse · a apply · q back", curses.A_DIM)
        stdscr.refresh()

        ch = stdscr.getch()

        if expanded is None:
            if ch in (curses.KEY_UP, ord("k")):
                cat_selected = (cat_selected - 1) % len(categories)
            elif ch in (curses.KEY_DOWN, ord("j")):
                cat_selected = (cat_selected + 1) % len(categories)
            elif ch in (curses.KEY_ENTER, 10, 13):
                expanded = categories[cat_selected]
                file_selected = 0
            elif ch == ord("a"):
                if confirm_apply(stdscr, total):
                    undo_log_path = target_dir / orgalazy.UNDO_LOG_FILENAME
                    errors = orgalazy.apply_actions(state.actions, undo_log_path=undo_log_path)
                    if errors:
                        lines = [
                            f"{len(errors)} action(s) failed; "
                            f"{total - len(errors)} succeeded.",
                            "",
                            "Errors:",
                        ]
                        lines.extend(errors[:10])
                        show_message(stdscr, lines, "Partial failure")
                    else:
                        show_message(
                            stdscr,
                            [
                                f"{total} action(s) applied successfully.",
                                f"Undo log: {undo_log_path}",
                            ],
                            "Done",
                        )
                    state.actions = []
                    return
            elif ch in (ord("q"), 27):
                return
        else:
            n_files = len(by_category[expanded])
            if ch in (curses.KEY_UP, ord("k")):
                file_selected = (file_selected - 1) % n_files
            elif ch in (curses.KEY_DOWN, ord("j")):
                file_selected = (file_selected + 1) % n_files
            elif ch in (curses.KEY_ENTER, 10, 13, ord("q"), 27):
                expanded = None


def confirm_apply(stdscr, count: int) -> bool:
    stdscr.clear()
    safe_addstr(stdscr, 2, 2, f"Apply {count} action(s)? (y/n)", curses.A_BOLD)
    stdscr.refresh()
    while True:
        ch = stdscr.getch()
        if ch in (ord("o"), ord("O"), ord("y"), ord("Y")):
            return True
        if ch in (ord("n"), ord("N"), 27):
            return False


def screen_undo(stdscr, state: AppState) -> None:
    result = prompt_text(stdscr, "Folder: ", state.target_dir_str)
    if result is None:
        return
    target_dir = Path(result).expanduser().resolve()
    undo_log_path = target_dir / orgalazy.UNDO_LOG_FILENAME

    if not undo_log_path.exists():
        show_message(
            stdscr,
            [
                f"No undo log found in {target_dir}.",
                "(You need to have applied a run first.)",
            ],
            "Undo",
        )
        return

    try:
        restored, errors = orgalazy.undo_last_run(undo_log_path)
    except (OSError, ValueError) as e:
        show_message(stdscr, [f"Error while undoing: {e}"], "Undo")
        return

    lines = [f"{restored} file(s) restored to their original location."]
    if errors:
        lines.append("")
        lines.append("Errors encountered:")
        lines.extend(errors[:10])
    show_message(stdscr, lines, "Undo complete")


# --------------------------------------------------------------------------
# Main loop
# --------------------------------------------------------------------------

def main(stdscr) -> None:
    curses.curs_set(0)
    state = AppState()

    while True:
        choice = screen_main_menu(stdscr, state)

        if choice == "quit":
            break
        elif choice == "help":
            screen_help(stdscr)
        elif choice == "undo":
            screen_undo(stdscr, state)
        elif choice == "scan":
            if not screen_setup(stdscr, state):
                continue
            error = run_scan(stdscr, state)
            if error:
                show_message(stdscr, [error], "Error")
                continue
            screen_preview(stdscr, state)


if __name__ == "__main__":
    try:
        curses.wrapper(main)
    except KeyboardInterrupt:
        sys.exit(130)
