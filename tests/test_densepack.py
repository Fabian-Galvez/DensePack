"""Checks for fixes that must not come back. Run: python -m unittest discover tests"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugin" / "scripts"))

import bash_image  # noqa: E402
import drop_read_gate  # noqa: E402


class WorktreeReads(unittest.TestCase):
    # 2.0.1 fix of issue #1: Reads in Claude Code worktrees get images.
    def test_worktree_files_are_not_scratch(self):
        self.assertFalse(drop_read_gate.is_scratch_or_temp("/repo/.claude/worktrees/x/app.py"))
        self.assertFalse(drop_read_gate.is_scratch_or_temp(r"C:\repo\.claude\worktrees\x\src\app.py"))

    def test_other_claude_folders_stay_text(self):
        self.assertTrue(drop_read_gate.is_scratch_or_temp("/repo/.claude/tmp/notes.md"))
        self.assertTrue(drop_read_gate.is_scratch_or_temp("/repo/.claude/worktrees/x/.claude/tmp/a.md"))


class DenseTextSetting(unittest.TestCase):
    def test_fold_repeats(self):
        text = "start\n" + "a\nb\n" * 5 + "end"
        self.assertEqual(bash_image.fold_repeats(text),
                         "start\na\nb\n[DensePack: the 2 line(s) above repeat 4 more times]\nend")
        self.assertEqual(bash_image.fold_repeats("a\nb\nc"), "a\nb\nc")

    def test_wide_ids(self):
        text = "ok task 4QAWsB3fVc5z\nMakefile2 Android14 build\ncommit " + "1a2b3c4d" * 5
        self.assertEqual(bash_image.risky_rows(text, wide=True), [0, 2])
        self.assertEqual(bash_image.risky_rows(text), [])

    def test_short_file_only_with_the_setting(self):
        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as f:
            f.write("x = 1\n" * 10)
        try:
            drop_read_gate.dense_text = lambda: False
            self.assertFalse(drop_read_gate.short_file(f.name))
            drop_read_gate.dense_text = lambda: True
            self.assertTrue(drop_read_gate.short_file(f.name))
        finally:
            os.unlink(f.name)


if __name__ == "__main__":
    unittest.main()
