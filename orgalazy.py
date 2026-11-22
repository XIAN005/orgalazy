#!/usr/bin/env python3
"""
orgalazy.py — Automatically organize a folder by category (or date) and handle duplicates.

Design goals:
- Self-contained: Python standard library only (no external dependency to install
  or maintain, so there is nothing to break in 10 years).
- Safe by default: dry-run mode unless --apply is explicitly passed.
- Idempotent: running the script several times does not break anything.
- Traceable: every action actually performed is written to a log file.

Usage:
    python3 orgalazy.py ~/Downloads                     # preview only
    python3 orgalazy.py ~/Downloads --apply             # apply for real
    python3 orgalazy.py ~/Downloads --apply --dedupe    # also move duplicate copies aside
    python3 orgalazy.py ~/Downloads --apply --by-date   # group into 2026-11 folders
    python3 orgalazy.py ~/Downloads --apply --include-hidden
    python3 orgalazy.py ~/Downloads --undo              # undo recorded moves
    python3 orgalazy.py ~/Downloads --config my_config.json

Python 3.8+ (`X | None` annotations are made harmless by
`from __future__ import annotations`).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import shutil
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

__version__ = "2.1.0"

# --------------------------------------------------------------------------
# Default categories (extension -> folder name)
# Can be overridden with an external JSON config file (--config).
# --------------------------------------------------------------------------

DEFAULT_CATEGORIES = {
    "Images": [
        "jpg", "jpeg", "png", "gif", "bmp", "svg", "webp", "heic", "heif",
        "tiff", "tif", "ico", "raw", "cr2", "nef", "arw",
    ],
    "Videos": [
        "mp4", "mkv", "avi", "mov", "wmv", "flv", "webm", "m4v", "mpg",
        "mpeg", "3gp", "ts",
    ],
    "Audio": [
        "mp3", "wav", "flac", "aac", "ogg", "m4a", "wma", "opus", "aiff",
    ],
    "Documents": [
        "pdf", "doc", "docx", "odt", "txt", "rtf", "md", "tex", "pages",
    ],
    "Spreadsheets": [
        "xls", "xlsx", "ods", "csv", "tsv",
    ],
    "Presentations": [
        "ppt", "pptx", "odp", "key",
    ],
    "Archives": [
        "zip", "rar", "7z", "tar", "gz", "bz2", "xz", "tgz", "iso",
    ],
    "Code": [
        "py", "js", "ts", "html", "css", "c", "cpp", "h", "hpp", "java",
        "rs", "go", "rb", "php", "sh", "json", "yaml", "yml", "xml", "sql",
    ],
    "Executables": [
        "exe", "msi", "deb", "rpm", "appimage", "run", "bin",
    ],
    "Fonts": [
        "ttf", "otf", "woff", "woff2",
    ],
    "Ebooks": [
        "epub", "mobi", "azw", "azw3", "fb2",
    ],
}

DUPLICATES_DIRNAME = "_Duplicates"
OTHERS_DIRNAME = "Others"
LOG_FILENAME = ".orgalazy_log.txt"
UNDO_LOG_FILENAME = ".orgalazy_undo.json"
HASH_CHUNK_SIZE = 65536  # 64 KiB, a good memory/speed trade-off

VALID_LAYOUTS = ("type", "date")


# --------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------

def validate_categories(data: object) -> dict[str, list[str]]:
    """
    Validate and normalize a {category: [extensions]} config.

    Category names that could escape the target folder (e.g. "../evil") are
    rejected, as is any attempt to reuse the internal duplicates folder.
    """
    if not isinstance(data, dict):
        raise ValueError(
            "The config file must contain a JSON object {category: [extensions]}"
        )

    cleaned: dict[str, list[str]] = {}
    for category, extensions in data.items():
        if not isinstance(category, str) or not category.strip():
            raise ValueError("Each category name must be a non-empty string.")
        if category in (".", "..") or "/" in category or "\\" in category:
            raise ValueError(f"Category name not allowed (path): {category!r}")
        if category == DUPLICATES_DIRNAME:
            raise ValueError(f"Category name {DUPLICATES_DIRNAME!r} is reserved.")
        if not isinstance(extensions, list) or not all(isinstance(e, str) for e in extensions):
            raise ValueError(
                f"Extensions for category {category!r} must be a list of strings."
            )
        cleaned[category] = [e.lower().lstrip(".") for e in extensions if e.strip()]

    return cleaned


def load_categories(config_path: Path | None) -> dict[str, list[str]]:
    """Load categories from an external JSON file, or use the defaults."""
    if config_path is None:
        return DEFAULT_CATEGORIES
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
        return validate_categories(data)
    except Exception as e:
        logging.error(
            "Could not load config %s: %s. Falling back to default categories.",
            config_path, e,
        )
        return DEFAULT_CATEGORIES


def build_extension_map(categories: dict[str, list[str]]) -> dict[str, str]:
    """Turn the category->extensions mapping into an extension->category map."""
    ext_map: dict[str, str] = {}
    for category, extensions in categories.items():
        for ext in extensions:
            ext_map[ext.lower().lstrip(".")] = category
    return ext_map


# --------------------------------------------------------------------------
# Duplicate detection
# --------------------------------------------------------------------------

def file_hash(path: Path) -> str:
    """SHA-256 of a file, read in chunks to avoid filling RAM on large files."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(HASH_CHUNK_SIZE):
            h.update(chunk)
    return h.hexdigest()


def _safe_mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return float("inf")


def find_duplicates(files: list[Path]) -> list[list[Path]]:
    """
    Return groups of duplicate files (identical content).
    Optimization: only files that already share the same size are hashed,
    which avoids hashing an entire disk for nothing.

    In each group, the first file is the original (the oldest one).
    """
    by_size: dict[int, list[Path]] = defaultdict(list)
    for f in files:
        try:
            by_size[f.stat().st_size].append(f)
        except OSError as e:
            logging.warning("Could not read size of %s: %s", f, e)

    duplicate_groups: list[list[Path]] = []
    for candidates in by_size.values():
        if len(candidates) < 2:
            continue
        by_hash: dict[str, list[Path]] = defaultdict(list)
        for f in candidates:
            try:
                by_hash[file_hash(f)].append(f)
            except OSError as e:
                logging.warning("Could not hash %s: %s", f, e)
        for group in by_hash.values():
            if len(group) > 1:
                duplicate_groups.append(
                    sorted(group, key=lambda p: (_safe_mtime(p), str(p).casefold()))
                )
    return duplicate_groups


# --------------------------------------------------------------------------
# Utilities
# --------------------------------------------------------------------------

def _path_key(path: Path) -> str:
    """Normalized key for comparing destination paths (OS-aware)."""
    return os.path.normcase(os.path.abspath(str(path)))


def unique_destination(dest: Path, reserved: set[str] | None = None) -> Path:
    """
    If `dest` already exists (name conflict, not a content duplicate) or has
    already been reserved by another planned action, append a numeric suffix
    so an existing file is never overwritten.

    `reserved` holds the keys (see `_path_key`) of destinations already
    assigned; the chosen destination is added to it.
    """
    reserved = reserved if reserved is not None else set()

    def available(candidate: Path) -> bool:
        return not candidate.exists() and _path_key(candidate) not in reserved

    if available(dest):
        reserved.add(_path_key(dest))
        return dest

    stem, suffix, parent = dest.stem, dest.suffix, dest.parent
    counter = 1
    while True:
        candidate = parent / f"{stem} ({counter}){suffix}"
        if available(candidate):
            reserved.add(_path_key(candidate))
            return candidate
        counter += 1


def category_for(path: Path, ext_map: dict[str, str], layout: str = "type") -> str:
    """Return the destination folder for a file."""
    if layout == "date":
        try:
            timestamp = path.stat().st_mtime
        except OSError:
            return OTHERS_DIRNAME
        return datetime.fromtimestamp(timestamp).strftime("%Y-%m")

    ext = path.suffix.lower().lstrip(".")
    return ext_map.get(ext, OTHERS_DIRNAME)


# --------------------------------------------------------------------------
# File selection
# --------------------------------------------------------------------------

def iter_candidate_files(
    target_dir: Path,
    categories: dict[str, list[str]],
    recursive: bool,
    exclude: set[str] | None = None,
    include_hidden: bool = False,
):
    """
    Yield files to process without descending into folders that are already
    organized (categories, _Duplicates) or into excluded folders.

    Hidden files (starting with a dot) are ignored by default: essential to
    avoid moving .bashrc, .config, etc. when running the script on a home
    directory.
    """
    exclude = exclude or set()
    organized_names = set(categories) | {OTHERS_DIRNAME, DUPLICATES_DIRNAME}
    skipped_names = {LOG_FILENAME, UNDO_LOG_FILENAME}

    for dirpath, dirnames, filenames in os.walk(target_dir, topdown=True):
        if recursive:
            dirnames[:] = [
                d for d in dirnames
                if d not in organized_names
                and d not in exclude
                and (include_hidden or not d.startswith("."))
            ]
        else:
            dirnames[:] = []

        for name in sorted(filenames, key=str.casefold):
            if name in skipped_names:
                continue
            if not include_hidden and name.startswith("."):
                continue
            path = Path(dirpath) / name
            try:
                if not path.is_file():
                    continue
            except OSError:
                continue
            yield path


# --------------------------------------------------------------------------
# Action plan (pure computation, no side effects — reused by the CLI and TUI)
# --------------------------------------------------------------------------

@dataclass
class Action:
    kind: str          # "move" (categorization) or "duplicate"
    src: Path
    dest: Path
    category: str       # category name ("_Duplicates" for duplicates)


def plan_actions(
    target_dir: Path,
    categories: dict[str, list[str]],
    dedupe: bool,
    recursive: bool,
    exclude: set[str] | None = None,
    layout: str = "type",
    include_hidden: bool = False,
) -> list[Action]:
    """Compute the list of actions to perform without touching the disk."""
    if layout not in VALID_LAYOUTS:
        raise ValueError(f"Unknown layout: {layout!r} (expected: {', '.join(VALID_LAYOUTS)})")

    ext_map = build_extension_map(categories) if layout == "type" else {}
    all_files = sorted(
        iter_candidate_files(target_dir, categories, recursive, exclude, include_hidden),
        key=lambda p: str(p).casefold(),
    )

    actions: list[Action] = []
    reserved: set[str] = set()
    files_to_categorize = all_files

    if dedupe:
        duplicate_groups = find_duplicates(all_files)
        files_marked_as_duplicate: set[Path] = set()
        for group in duplicate_groups:
            _original, *dupes = group
            for dupe in dupes:
                files_marked_as_duplicate.add(dupe)
                dest_dir = target_dir / DUPLICATES_DIRNAME
                dest = unique_destination(dest_dir / dupe.name, reserved)
                actions.append(Action("duplicate", dupe, dest, DUPLICATES_DIRNAME))
        files_to_categorize = [f for f in all_files if f not in files_marked_as_duplicate]

    for f in files_to_categorize:
        category = category_for(f, ext_map, layout)
        dest_dir = target_dir / category
        if dest_dir == f.parent:
            continue
        dest = unique_destination(dest_dir / f.name, reserved)
        actions.append(Action("move", f, dest, category))

    return actions


def _read_undo_entries(undo_log_path: Path) -> list[dict]:
    """Read the existing undo log, silently ignoring a corrupted file."""
    if not undo_log_path.exists():
        return []
    try:
        data = json.loads(undo_log_path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            raise ValueError("the log is not a list")
        return [
            entry for entry in data
            if isinstance(entry, dict)
            and isinstance(entry.get("src"), str)
            and isinstance(entry.get("dest"), str)
        ]
    except (OSError, ValueError) as e:
        logging.warning("Unreadable undo log (%s): %s", undo_log_path, e)
        return []


def _write_undo_log(undo_log_path: Path, entries: list[dict]) -> None:
    """Write the log atomically (temporary file, then replace)."""
    if not entries:
        return
    undo_log_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = undo_log_path.with_name(undo_log_path.name + ".tmp")
    tmp_path.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp_path, undo_log_path)


def apply_actions(actions: list[Action], undo_log_path: Path | None = None) -> list[str]:
    """
    Perform the moves for real and update the undo log.

    An error on one file does not stop the other moves: successful actions
    remain undoable. Return the list of errors.
    """
    executed: list[dict] = []
    errors: list[str] = []
    reserved: set[str] = set()

    for action in actions:
        try:
            action.dest.parent.mkdir(parents=True, exist_ok=True)
            if action.dest.exists() or _path_key(action.dest) in reserved:
                action.dest = unique_destination(action.dest, reserved)
            else:
                reserved.add(_path_key(action.dest))

            shutil.move(str(action.src), str(action.dest))
            executed.append({"src": str(action.src), "dest": str(action.dest)})
        except OSError as e:
            errors.append(f"{action.src} -> {action.dest}: {e}")

    if undo_log_path is not None and executed:
        # Keep entries from previous runs that were not undone, so an undo
        # restores every action that is still in place.
        previous = _read_undo_entries(undo_log_path)
        _write_undo_log(undo_log_path, previous + executed)

    return errors


def undo_last_run(undo_log_path: Path) -> tuple[int, list[str]]:
    """
    Replay the undo log backwards: move each file from `dest` back to `src`.
    Return (number of restored files, list of errors encountered).
    """
    try:
        entries = json.loads(undo_log_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ValueError(f"Unreadable undo log: {e}") from e

    if not isinstance(entries, list):
        raise ValueError("Invalid undo log: a list of entries is expected.")
    for entry in entries:
        if (
            not isinstance(entry, dict)
            or not isinstance(entry.get("src"), str)
            or not isinstance(entry.get("dest"), str)
        ):
            raise ValueError("Invalid undo log: entry without 'src'/'dest'.")

    restored = 0
    errors: list[str] = []

    for entry in reversed(entries):
        src, dest = Path(entry["src"]), Path(entry["dest"])
        try:
            if not dest.exists():
                errors.append(f"Missing (already moved/deleted?): {dest}")
                continue
            src.parent.mkdir(parents=True, exist_ok=True)
            final_src = unique_destination(src)  # in case a file was recreated meanwhile
            shutil.move(str(dest), str(final_src))
            restored += 1
        except OSError as e:
            errors.append(f"{dest} -> {src}: {e}")

    # Remove category folders that became empty after restoring
    dest_dirs = {Path(entry["dest"]).parent for entry in entries}
    for dest_dir in sorted(dest_dirs, key=lambda p: len(p.parts), reverse=True):
        try:
            if dest_dir.exists() and dest_dir.is_dir() and not any(dest_dir.iterdir()):
                dest_dir.rmdir()
        except OSError:
            pass

    if not errors:
        undo_log_path.unlink(missing_ok=True)

    return restored, errors


# --------------------------------------------------------------------------
# Program core (CLI) — built on plan_actions() / apply_actions()
# --------------------------------------------------------------------------

def organize(
    target_dir: Path,
    categories: dict[str, list[str]],
    apply: bool,
    dedupe: bool,
    recursive: bool,
    exclude: set[str] | None = None,
    layout: str = "type",
    include_hidden: bool = False,
) -> list[str]:
    actions = plan_actions(
        target_dir, categories, dedupe, recursive, exclude, layout, include_hidden
    )

    if not actions:
        logging.info("No files to process in %s.", target_dir)
        return []

    counts = Counter(action.category for action in actions)
    logging.info(
        "Summary: %s",
        ", ".join(f"{category}={count}" for category, count in sorted(counts.items())),
    )

    for action in actions:
        label = "MOVE (duplicate)" if action.kind == "duplicate" else "MOVE"
        logging.info("%s: %s -> %s", label, action.src, action.dest)

    moved_count = sum(1 for a in actions if a.kind == "move")
    duplicate_count = sum(1 for a in actions if a.kind == "duplicate")

    errors: list[str] = []
    if apply:
        undo_log_path = target_dir / UNDO_LOG_FILENAME
        errors = apply_actions(actions, undo_log_path=undo_log_path)
        for error in errors:
            logging.error("Failure: %s", error)

    mode = "APPLIED" if apply else "DRY-RUN (no files changed — rerun with --apply)"
    suffix = f" — {len(errors)} failure(s)" if errors else ""
    logging.info(
        "Done [%s]: %d file(s) organized, %d duplicate(s) handled%s.",
        mode, moved_count, duplicate_count, suffix,
    )
    return errors


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def setup_logging(target_dir: Path) -> None:
    root = logging.getLogger()
    if getattr(root, "_orgalazy_configured", False):
        return

    log_path = target_dir / LOG_FILENAME
    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )

    root.setLevel(logging.INFO)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    root.addHandler(console_handler)

    try:
        file_handler = logging.FileHandler(log_path, encoding="utf-8")
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)
    except OSError as e:
        logging.warning("Could not write log to %s: %s", log_path, e)

    root._orgalazy_configured = True  # type: ignore[attr-defined]


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Automatically organize a folder by category (or date) and handle duplicates.",
    )
    parser.add_argument("directory", type=str, help="Folder to organize (e.g. ~/Downloads)")
    action_group = parser.add_mutually_exclusive_group()
    action_group.add_argument(
        "--apply", action="store_true",
        help="Apply changes for real (default: preview only).",
    )
    action_group.add_argument(
        "--undo", action="store_true",
        help="Undo the moves recorded in the folder's undo log.",
    )
    parser.add_argument(
        "--dedupe", action="store_true",
        help="Detect duplicate content and move copies to the _Duplicates folder.",
    )
    parser.add_argument(
        "--recursive", action="store_true",
        help="Also scan subfolders (default: top-level folder only).",
    )
    parser.add_argument(
        "--by-date", action="store_true",
        help="Group files by modification month (2026-11) instead of file type.",
    )
    parser.add_argument(
        "--include-hidden", action="store_true",
        help="Also process hidden files and folders (skipped by default to protect .bashrc, .config, etc.).",
    )
    parser.add_argument(
        "--exclude", type=str, nargs="+", default=[],
        help="Subfolder name(s) to ignore completely, e.g. --exclude ProjectX Archive",
    )
    parser.add_argument(
        "--config", type=str, default=None,
        help="Path to a custom JSON config {\"Category\": [\"ext1\", \"ext2\"]}.",
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv if argv is not None else sys.argv[1:])

    target_dir = Path(args.directory).expanduser().resolve()
    if not target_dir.exists():
        print(f"Error: folder {target_dir} does not exist.", file=sys.stderr)
        return 1
    if not target_dir.is_dir():
        print(f"Error: {target_dir} is not a folder.", file=sys.stderr)
        return 1

    config_path = Path(args.config).expanduser().resolve() if args.config else None
    if config_path is not None and not config_path.is_file():
        print(f"Error: config file {config_path} does not exist.", file=sys.stderr)
        return 1

    undo_log_path = target_dir / UNDO_LOG_FILENAME
    if args.undo and not undo_log_path.exists():
        print(f"Error: no undo log found in {target_dir}.", file=sys.stderr)
        return 1

    setup_logging(target_dir)
    categories = load_categories(config_path)

    logging.info("=== orgalazy.py %s — starting (%s) ===", __version__, datetime.now().isoformat(timespec="seconds"))
    logging.info("Target folder: %s", target_dir)

    if args.undo:
        try:
            restored, undo_errors = undo_last_run(undo_log_path)
        except (OSError, ValueError) as e:
            logging.error("Undo failed: %s", e)
            return 1
        logging.info("Undo: %d file(s) restored.", restored)
        for error in undo_errors:
            logging.error("Failure: %s", error)
        return 1 if undo_errors else 0

    logging.info(
        "Mode: %s | layout=%s | dedupe=%s | recursive=%s | hidden=%s | exclude=%s",
        "APPLY" if args.apply else "DRY-RUN",
        "date" if args.by_date else "type",
        args.dedupe, args.recursive, args.include_hidden,
        args.exclude or "none",
    )

    try:
        errors = organize(
            target_dir=target_dir,
            categories=categories,
            apply=args.apply,
            dedupe=args.dedupe,
            recursive=args.recursive,
            exclude=set(args.exclude),
            layout="date" if args.by_date else "type",
            include_hidden=args.include_hidden,
        )
    except KeyboardInterrupt:
        logging.warning("Interrupted by user.")
        return 130
    except Exception as e:
        logging.exception("Unexpected error: %s", e)
        return 1

    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
