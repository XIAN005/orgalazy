# Orgalazy

> Automatically organize a folder by file type (or date), with zero dependencies and no deletions.

![Python](https://img.shields.io/badge/python-3.8%2B-blue)
![Tests](https://github.com/XIAN005/orgalazy/actions/workflows/tests.yml/badge.svg)
![License](https://img.shields.io/badge/license-MIT-green)

**English** | [Français](README.fr.md)
<img width="1366" height="768" alt="2026-11-22_13-37" src="https://github.com/user-attachments/assets/4797461b-0af2-4480-95a7-5787a892eba9" />

**Orgalazy** is a small command-line utility — with a text interface (TUI) — written using only the Python standard library. It moves cluttered files from a folder (`~/Downloads`, a desktop, etc.) into clear subfolders: `Images`, `Documents`, `Videos`, `Archives`…

The **dry-run mode is enabled by default**: nothing is moved until you add `--apply`.

---

## Table of contents

- [Features](#features)
- [Safety](#safety)
- [Requirements](#requirements)
- [Installation](#installation)
- [Quick start](#quick-start)
- [Command-line options](#command-line-options)
- [Organize by date](#organize-by-date)
- [Duplicates](#duplicates)
- [Undo a run](#undo-a-run)
- [Custom configuration](#custom-configuration)
- [Text interface (TUI)](#text-interface-tui)
- [Tests](#tests)
- [Project structure](#project-structure)
- [Contributing](#contributing)
- [License](#license)

---

## Features

- **Sort by type**: images, videos, audio, documents, spreadsheets, archives, code, fonts, ebooks…
- **Sort by date** with `--by-date`: folders such as `2026-11`, `2026-10`, etc.
- **Duplicate detection** using SHA-256, without deletion: copies are moved to `_Duplicates`.
- **Dry-run by default**: review the full plan before changing anything.
- **Undo** moves through the `.orgalazy_undo.json` journal.
- **Never overwrites**: on a name conflict, a suffix is added (`photo (1).jpg`).
- **Hidden files are skipped by default**: essential when running the tool on your home folder.
- **No external dependencies**: a single Python file to copy or clone.
- **Curses TUI** to browse, preview, and apply actions.

### Default categories

| Folder | Examples of extensions |
|---|---|
| `Images` | jpg, jpeg, png, gif, bmp, svg, webp, heic, tiff, raw… |
| `Videos` | mp4, mkv, avi, mov, webm, m4v… |
| `Audio` | mp3, wav, flac, aac, ogg, m4a, opus… |
| `Documents` | pdf, doc, docx, odt, txt, rtf, md… |
| `Spreadsheets` | xls, xlsx, ods, csv, tsv |
| `Presentations` | ppt, pptx, odp, key |
| `Archives` | zip, rar, 7z, tar, gz, xz, iso… |
| `Code` | py, js, ts, html, css, c, cpp, java, rs, go, json… |
| `Executables` | exe, msi, deb, rpm, appimage, bin… |
| `Fonts` | ttf, otf, woff, woff2 |
| `Ebooks` | epub, mobi, azw, azw3, fb2 |
| `Others` | anything else |

## Safety

Orgalazy is designed to be careful:

| Guarantee | Detail |
|---|---|
| Nothing is deleted | Duplicates are **moved**, never erased. |
| Nothing is overwritten | An existing destination becomes `name (1).ext`, `name (2).ext`, etc. |
| Dry-run by default | Without `--apply`, the program only prints the action plan. |
| Hidden files protected | `.bashrc`, `.config`, `.cache`… are skipped unless `--include-hidden` is used. |
| Errors do not stop the run | One unreadable file does not prevent other moves. |
| Undo journal | Successful moves remain undoable, even after a partial failure. |
| Validated configuration | Category names containing paths (`../`) are rejected. |

> Tip: always run it **without** `--apply` first and review the preview.

## Requirements

- Python **3.8 or newer**
- Linux or macOS for the TUI (`curses`). The command line also works on Windows.
- No package to install.

## Installation

```bash
git clone https://github.com/XIAN005/orgalazy.git
cd orgalazy
chmod +x orgalazy.py orgalazy_tui.py

python3 orgalazy.py --version
```

You can also download `orgalazy.py` on its own and run it directly:

```bash
python3 orgalazy.py ~/Downloads
```

To use it as a global command:

```bash
mkdir -p ~/.local/bin
ln -s "$PWD/orgalazy.py" ~/.local/bin/orgalazy
orgalazy ~/Downloads
```

## Quick start

```bash
# 1. Preview: show what would be moved, change nothing
python3 orgalazy.py ~/Downloads

# 2. Apply for real
python3 orgalazy.py ~/Downloads --apply

# 3. With duplicate detection
python3 orgalazy.py ~/Downloads --apply --dedupe

# 4. Group files by modification month
python3 orgalazy.py ~/Downloads --apply --by-date

# 5. Scan subfolders while excluding some folders
python3 orgalazy.py ~/Documents --apply --recursive --exclude Projects Archives

# 6. Include hidden files (use with care)
python3 orgalazy.py ~/Downloads --apply --include-hidden
```

A human-readable log is written to the target folder: `.orgalazy_log.txt`.

## Command-line options

```text
python3 orgalazy.py DIRECTORY [options]
```

| Option | Effect |
|---|---|
| `--apply` | Apply the moves for real. Without it: dry-run. |
| `--undo` | Undo the moves recorded in the folder's journal. |
| `--dedupe` | Detect duplicate content and move copies to `_Duplicates`. |
| `--recursive` | Also scan subfolders. |
| `--by-date` | Group by month (`YYYY-MM`) instead of by file type. |
| `--include-hidden` | Also process hidden files and folders. |
| `--exclude NAME [NAME ...]` | Completely ignore the listed subfolders. |
| `--config FILE.json` | Use a custom category configuration. |
| `--version` | Print the version. |

`--apply` and `--undo` are mutually exclusive.

## Organize by date

```bash
python3 orgalazy.py ~/Pictures --by-date          # preview
python3 orgalazy.py ~/Pictures --by-date --apply  # apply
```

Files are grouped by their last modification date:

```text
Pictures/
├── 2026-11/
├── 2026-10/
└── 2026-09/
```

Running the script again on a folder already organized by date does not move files again.

## Duplicates

```bash
python3 orgalazy.py ~/Downloads --dedupe
```

- Two files are considered identical when they have the **same content** (SHA-256), not merely the same name.
- The oldest file (by modification time) stays where it is.
- Copies are moved to `_Duplicates/`, never deleted.
- The `_Duplicates` folder is ignored on subsequent runs.

## Undo a run

```bash
python3 orgalazy.py ~/Downloads --undo
```

The `.orgalazy_undo.json` journal stores source/destination pairs. Undo restores files to their original folder and removes category folders that became empty.

The journal is **cumulative**: if you apply several runs without undoing, `--undo` restores every move that is still in place.

## Custom configuration

The file [`examples/config.json`](examples/config.json) shows how to define your own categories:

```json
{
  "Images": ["jpg", "jpeg", "png", "gif", "webp", "svg"],
  "Documents": ["pdf", "docx", "odt", "txt", "md"],
  "Archives": ["zip", "tar", "gz", "7z"],
  "Code": ["py", "js", "ts", "html", "css", "json"],
  "3D": ["blend", "obj", "fbx", "stl"],
  "Projects": ["psd", "ai", "fig"]
}
```

```bash
python3 orgalazy.py ~/Downloads --config examples/config.json
```

Keys are folder names; values are extensions (with or without a leading dot). If the file is invalid, Orgalazy falls back to the default categories and says so in the log.

## Text interface (TUI)

```bash
python3 orgalazy_tui.py
```

The interface lets you:

1. choose the target folder;
2. enable recursive scanning, duplicate detection, date grouping, and hidden files;
3. exclude folders and load a JSON configuration;
4. preview actions grouped by category;
5. apply with `a` after confirmation;
6. undo the last run from the main menu.

| Key | Action |
|---|---|
| `↑` `↓` or `j` `k` | Move |
| `Enter` | Confirm / expand a category |
| `Space` | Toggle an option |
| `a` | Apply the displayed plan |
| `q` / `Escape` | Back / quit |

The TUI requires `curses` (Linux, macOS, and WSL). On native Windows, use the command line.

## Tests

The test suite only touches temporary folders:

```bash
python3 -m unittest -v test_orgalazy.py
```

It covers categorization, name collisions, duplicates, undo, partial failures, hidden files, and date mode.

GitHub Actions runs these tests on several Python versions on every `push` and `pull request`.

## Project structure

```text
.
├── orgalazy.py                  # CLI + organization logic
├── orgalazy_tui.py              # text interface (curses)
├── test_orgalazy.py             # unit tests (unittest)
├── examples/
│   └── config.json              # example configuration
├── .github/
│   └── workflows/
│       └── tests.yml            # continuous integration
├── .gitignore
├── LICENSE
├── README.md
└── README.fr.md                 # French documentation
```

## Contributing

Issues and pull requests are welcome. Before submitting a change, run:

```bash
python3 -m unittest -v test_orgalazy.py
```

Please keep the project dependency-free and preserve the dry-run-by-default behavior.

## License

Released under the [MIT License](LICENSE). You are free to use, modify, and redistribute it.
