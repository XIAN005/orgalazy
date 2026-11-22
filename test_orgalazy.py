#!/usr/bin/env python3
"""Tests de non-régression pour orgalazy.py (bibliothèque standard uniquement).

Lancement :
    cd ~/file-organizer
    python3 -m unittest -v test_orgalazy.py
"""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

import orgalazy


class OrgalazyTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def write(self, relative: str, content: str = "x") -> Path:
        path = self.dir / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def plan(self, **kwargs) -> list[orgalazy.Action]:
        params = {
            "target_dir": self.dir,
            "categories": orgalazy.DEFAULT_CATEGORIES,
            "dedupe": False,
            "recursive": False,
        }
        params.update(kwargs)
        return orgalazy.plan_actions(**params)

    def apply(self, actions: list[orgalazy.Action]) -> list[str]:
        return orgalazy.apply_actions(
            actions, undo_log_path=self.dir / orgalazy.UNDO_LOG_FILENAME
        )


class TestCategorization(OrgalazyTestCase):
    def test_moves_files_by_extension(self) -> None:
        self.write("photo.jpg", "jpeg")
        self.write("report.pdf", "pdf")
        self.write("archive.zip", "zip")
        self.write("mystery.xyz", "?")

        actions = self.plan()
        self.assertEqual(len(actions), 4)
        self.assertEqual(self.apply(actions), [])

        self.assertTrue((self.dir / "Images" / "photo.jpg").is_file())
        self.assertTrue((self.dir / "Documents" / "report.pdf").is_file())
        self.assertTrue((self.dir / "Archives" / "archive.zip").is_file())
        self.assertTrue((self.dir / "Autres" / "mystery.xyz").is_file())
        self.assertFalse((self.dir / "photo.jpg").exists())

    def test_does_not_overwrite_existing_destination(self) -> None:
        existing = self.write("Documents/notes.txt", "old")
        new = self.write("notes.txt", "new")

        actions = self.plan()
        self.assertEqual(self.apply(actions), [])

        self.assertEqual(existing.read_text(encoding="utf-8"), "old")
        self.assertFalse(new.exists())
        self.assertTrue((self.dir / "Documents" / "notes (1).txt").is_file())

    def test_same_name_in_two_subdirs_gets_distinct_destinations(self) -> None:
        self.write("a/photo.jpg", "one")
        self.write("b/photo.jpg", "two")

        actions = self.plan(recursive=True)
        self.assertEqual(self.apply(actions), [])

        names = sorted(p.name for p in (self.dir / "Images").iterdir())
        self.assertEqual(names, ["photo (1).jpg", "photo.jpg"])
        contents = {
            p.name: p.read_text(encoding="utf-8")
            for p in (self.dir / "Images").iterdir()
        }
        self.assertEqual(contents, {"photo.jpg": "one", "photo (1).jpg": "two"})

    def test_already_organized_dirs_are_skipped(self) -> None:
        self.write("Images/old.jpg", "old")
        self.write("fresh.jpg", "new")

        actions = self.plan(recursive=True)
        self.assertEqual([a.src.name for a in actions], ["fresh.jpg"])

    def test_log_files_are_never_moved(self) -> None:
        self.write(orgalazy.LOG_FILENAME, "log")
        self.write(orgalazy.UNDO_LOG_FILENAME, "[]")

        self.assertEqual(self.plan(include_hidden=True), [])


class TestHiddenFiles(OrgalazyTestCase):
    def test_hidden_files_are_ignored_by_default(self) -> None:
        self.write(".bashrc", "secret")
        self.write("visible.txt", "visible")

        actions = self.plan(recursive=True)
        self.assertEqual([a.src.name for a in actions], ["visible.txt"])

    def test_hidden_files_can_be_included(self) -> None:
        self.write(".bashrc", "secret")
        self.write("visible.txt", "visible")

        actions = self.plan(recursive=True, include_hidden=True)
        self.assertEqual({a.src.name for a in actions}, {".bashrc", "visible.txt"})

    def test_hidden_directories_are_pruned(self) -> None:
        self.write(".config/app.txt", "secret")
        self.write("visible.txt", "visible")

        actions = self.plan(recursive=True)
        self.assertEqual([a.src.name for a in actions], ["visible.txt"])

    def test_excluded_directories_are_pruned(self) -> None:
        self.write("Projects/app.txt", "project")
        self.write("visible.txt", "visible")

        actions = self.plan(recursive=True, exclude={"Projects"})
        self.assertEqual([a.src.name for a in actions], ["visible.txt"])


class TestDuplicates(OrgalazyTestCase):
    def test_keeps_oldest_and_moves_newer_duplicate(self) -> None:
        old = self.write("old.txt", "same content")
        new = self.write("sub/new.txt", "same content")
        os.utime(old, (1_000_000_000, 1_000_000_000))
        os.utime(new, (2_000_000_000, 2_000_000_000))

        actions = self.plan(dedupe=True, recursive=True)
        duplicates = [a for a in actions if a.kind == "duplicate"]
        self.assertEqual(len(duplicates), 1)
        self.assertEqual(duplicates[0].src, new)

        self.assertEqual(self.apply(actions), [])
        self.assertTrue((self.dir / "Documents" / "old.txt").is_file())
        self.assertTrue((self.dir / "_Doublons" / "new.txt").is_file())

    def test_different_content_same_size_is_not_a_duplicate(self) -> None:
        self.write("a.txt", "AAAA")
        self.write("b.txt", "BBBB")

        actions = self.plan(dedupe=True)
        self.assertFalse([a for a in actions if a.kind == "duplicate"])


class TestUndo(OrgalazyTestCase):
    def test_undo_restores_original_paths(self) -> None:
        original = self.write("photo.jpg", "jpeg")
        actions = self.plan()
        self.assertEqual(self.apply(actions), [])
        self.assertTrue((self.dir / "Images" / "photo.jpg").is_file())

        restored, errors = orgalazy.undo_last_run(
            self.dir / orgalazy.UNDO_LOG_FILENAME
        )

        self.assertEqual(restored, 1)
        self.assertEqual(errors, [])
        self.assertTrue(original.is_file())
        self.assertFalse((self.dir / "Images").exists())
        self.assertFalse((self.dir / orgalazy.UNDO_LOG_FILENAME).exists())

    def test_undo_is_cumulative_across_runs(self) -> None:
        first = self.write("first.jpg", "one")
        self.assertEqual(self.apply(self.plan()), [])

        second = self.write("second.pdf", "two")
        self.assertEqual(self.apply(self.plan()), [])

        restored, errors = orgalazy.undo_last_run(
            self.dir / orgalazy.UNDO_LOG_FILENAME
        )
        self.assertEqual(restored, 2)
        self.assertEqual(errors, [])
        self.assertTrue(first.is_file())
        self.assertTrue(second.is_file())
        self.assertFalse((self.dir / "Images").exists())
        self.assertFalse((self.dir / "Documents").exists())

    def test_partial_failure_still_allows_undo_of_successful_moves(self) -> None:
        first = self.write("a.txt", "a")
        second = self.write("b.txt", "b")
        actions = self.plan()

        real_move = shutil.move
        calls = {"count": 0}

        def flaky_move(src, dst):
            calls["count"] += 1
            if calls["count"] == 2:
                raise OSError("simulated failure")
            return real_move(src, dst)

        with mock.patch("orgalazy.shutil.move", side_effect=flaky_move):
            errors = self.apply(actions)

        self.assertEqual(len(errors), 1)
        moved = [p for p in (first, second) if not p.exists()]
        self.assertEqual(len(moved), 1)

        restored, undo_errors = orgalazy.undo_last_run(
            self.dir / orgalazy.UNDO_LOG_FILENAME
        )
        self.assertEqual(restored, 1)
        self.assertEqual(undo_errors, [])
        self.assertTrue(first.is_file())
        self.assertTrue(second.is_file())


class TestDateLayout(OrgalazyTestCase):
    def test_groups_by_modification_month(self) -> None:
        photo = self.write("photo.jpg", "jpeg")
        timestamp = datetime(2026, 3, 15, 12, 0).timestamp()
        os.utime(photo, (timestamp, timestamp))

        actions = self.plan(layout="date")
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0].category, "2026-03")

        self.assertEqual(self.apply(actions), [])
        self.assertTrue((self.dir / "2026-03" / "photo.jpg").is_file())

    def test_rerun_on_date_dirs_is_idempotent(self) -> None:
        photo = self.write("2026-03/photo.jpg", "jpeg")
        timestamp = datetime(2026, 3, 15, 12, 0).timestamp()
        os.utime(photo, (timestamp, timestamp))

        actions = self.plan(layout="date", recursive=True)
        self.assertEqual(actions, [])

    def test_invalid_layout_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self.plan(layout="nonsense")


class TestConfigValidation(unittest.TestCase):
    def test_normalizes_and_lowercases_extensions(self) -> None:
        result = orgalazy.validate_categories({"Docs": [".TXT", "PDF"]})
        self.assertEqual(result, {"Docs": ["txt", "pdf"]})

    def test_rejects_path_traversal_category(self) -> None:
        with self.assertRaises(ValueError):
            orgalazy.validate_categories({"../evil": ["txt"]})

    def test_rejects_reserved_duplicate_dir(self) -> None:
        with self.assertRaises(ValueError):
            orgalazy.validate_categories({orgalazy.DUPLICATES_DIRNAME: ["txt"]})

    def test_rejects_non_list_extensions(self) -> None:
        with self.assertRaises(ValueError):
            orgalazy.validate_categories({"Docs": "txt"})


class TestCli(OrgalazyTestCase):
    def test_by_date_flag_sets_layout(self) -> None:
        args = orgalazy.parse_args([str(self.dir), "--by-date"])
        self.assertTrue(args.by_date)

    def test_version_flag_exits_cleanly(self) -> None:
        with self.assertRaises(SystemExit) as context, mock.patch("sys.stdout"):
            orgalazy.parse_args(["--version"])
        self.assertEqual(context.exception.code, 0)

    def test_dry_run_changes_nothing(self) -> None:
        original = self.write("photo.jpg", "jpeg")
        exit_code = orgalazy.main([str(self.dir)])
        self.assertEqual(exit_code, 0)
        self.assertTrue(original.is_file())
        self.assertFalse((self.dir / "Images").exists())

    def test_undo_flag_restores_files(self) -> None:
        original = self.write("photo.jpg", "jpeg")
        self.assertEqual(orgalazy.main([str(self.dir), "--apply"]), 0)
        self.assertTrue((self.dir / "Images" / "photo.jpg").is_file())

        self.assertEqual(orgalazy.main([str(self.dir), "--undo"]), 0)
        self.assertTrue(original.is_file())
        self.assertFalse((self.dir / "Images").exists())

    def test_undo_without_log_fails_cleanly(self) -> None:
        self.assertEqual(orgalazy.main([str(self.dir), "--undo"]), 1)

    def test_apply_and_undo_are_mutually_exclusive(self) -> None:
        with self.assertRaises(SystemExit) as context, mock.patch("sys.stderr"):
            orgalazy.parse_args([str(self.dir), "--apply", "--undo"])
        self.assertEqual(context.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
