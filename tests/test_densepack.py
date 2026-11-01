"""Checks for fixes that must not come back. Run: python -m unittest discover tests"""
import io
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugin" / "scripts"))

import bash_image  # noqa: E402
import brief_pack  # noqa: E402
import codepack  # noqa: E402
import common  # noqa: E402
import drop_read_gate  # noqa: E402
import edit_gate  # noqa: E402
import grep_gate  # noqa: E402
import pointer  # noqa: E402
import source_gate  # noqa: E402
import subagent_stop  # noqa: E402


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


class TextFilesList(unittest.TestCase):
    # Files that match ~/.claude/densepack-text-files.txt stay text in every project.
    def test_listed_pattern_stays_text_and_others_pack(self):
        home = tempfile.mkdtemp()
        os.makedirs(os.path.join(home, ".claude"))
        Path(home, ".claude", "densepack-text-files.txt").write_text("# my list\n*.kt\n", encoding="utf-8")
        code = "fun main() {\n    println(1)\n}\n" * 40
        try:
            with mock.patch.dict(os.environ, {"HOME": home, "USERPROFILE": home}):
                for name, stays in (("Main.kt", True), ("main.py", False)):
                    path = os.path.join(home, name)
                    Path(path).write_text(code, encoding="utf-8")
                    self.assertEqual(common.keeps_text(path), stays)
                    if stays:
                        self.assertIsNone(drop_read_gate._drawable_text(path))
        finally:
            shutil.rmtree(home)


class AskRuleConfigDir(unittest.TestCase):
    # Claude Code reads user rules from CLAUDE_CONFIG_DIR when it is set, so a hook must not miss an ask rule there.
    def test_ask_rule_in_config_dir_counts(self):
        root = tempfile.mkdtemp()
        cfg, home, proj = (os.path.join(root, n) for n in ("cfg", "home", "proj"))
        for d in (cfg, home, proj):
            os.makedirs(d)
        Path(cfg, "settings.json").write_text('{"permissions": {"ask": ["Read(./notes.txt)"]}}', encoding="utf-8")
        try:
            with mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": cfg, "HOME": home, "USERPROFILE": home,
                                              "CLAUDE_PROJECT_DIR": proj}), \
                    mock.patch.object(common, "_managed_settings_paths", return_value=[]):
                self.assertTrue(common.ask_rule_names("Read"))
                self.assertFalse(common.ask_rule_names("Bash"))
        finally:
            shutil.rmtree(root)


class RemoveMovedSetup(unittest.TestCase):
    # With CLAUDE_CONFIG_DIR set, /dense-remove also clears the keys that 2.0.5 wrote to ~/.claude/settings.json,
    # unless DensePack is installed in that second setup.
    def test_home_settings_cleaned_only_without_densepack(self):
        import dpctl
        for installed in (False, True):
            root = tempfile.mkdtemp()
            home, cfg = os.path.join(root, "home"), os.path.join(root, "cfg")
            os.makedirs(os.path.join(home, ".claude", "plugins"))
            os.makedirs(cfg)
            settings = Path(home, ".claude", "settings.json")
            settings.write_text('{"env": {"CLAUDE_CODE_THRIFTY_SONIC": "0", "MY_KEY": "1"}}', encoding="utf-8")
            if installed:
                Path(home, ".claude", "plugins", "installed_plugins.json").write_text(
                    '{"plugins": {"densepack@densepack-marketplace": []}}', encoding="utf-8")
            try:
                with mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": cfg, "HOME": home, "USERPROFILE": home,
                                                  "LOCALAPPDATA": root, "CLAUDE_PROJECT_DIR": root}), \
                        mock.patch("tempfile.gettempdir", return_value=root), mock.patch("builtins.print"):
                    dpctl.remove_everything()
                text = settings.read_text(encoding="utf-8")
                self.assertEqual("CLAUDE_CODE_THRIFTY_SONIC" in text, installed)
                self.assertIn("MY_KEY", text)
            finally:
                shutil.rmtree(root)

    def test_tmp_folder_through_a_link_is_left_alone(self):
        import json
        import dpctl
        root = tempfile.mkdtemp()
        cfg, project, outside = (os.path.join(root, n) for n in ("cfg", "project", "outside"))
        os.makedirs(os.path.join(cfg, "projects", "p"))
        os.makedirs(os.path.join(project, ".claude"))
        os.makedirs(outside)
        Path(outside, "densepack-x.txt").write_text("x", encoding="utf-8")
        Path(cfg, "projects", "p", "a.jsonl").write_text(json.dumps({"cwd": project}) + "\n", encoding="utf-8")
        link = os.path.join(project, ".claude", "tmp")
        if os.name == "nt":
            import _winapi
            _winapi.CreateJunction(outside, link)
        else:
            os.symlink(outside, link)
        try:
            with mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": cfg, "HOME": root, "USERPROFILE": root,
                                              "LOCALAPPDATA": root, "CLAUDE_PROJECT_DIR": root}), \
                    mock.patch("tempfile.gettempdir", return_value=root), mock.patch("builtins.print"):
                dpctl.remove_everything()
            self.assertTrue(Path(outside, "densepack-x.txt").exists())
        finally:
            os.unlink(link) if os.path.islink(link) else os.rmdir(link)
            shutil.rmtree(root)


class StyleOff(unittest.TestCase):
    # /style-off keeps the section on finding and reading files and drops the writing rules and the reminder line.
    def test_style_off_keeps_navigation_rules_only(self):
        import bootstrap
        import style_reminder
        root = tempfile.mkdtemp()
        os.makedirs(os.path.join(root, ".claude", "tmp"))
        try:
            with mock.patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": root}):
                for style in ("on", "off"):
                    Path(root, ".claude", "tmp", "densepack-settings.json").write_text(
                        '{"style": "%s"}' % style, encoding="utf-8")
                    text = bootstrap.rules_text()
                    self.assertIn("## Work in few turns", text)
                    self.assertEqual("## Write like a person" in text, style == "on")
                    out = io.StringIO()
                    with mock.patch("sys.stdin", io.StringIO('{"hook_event_name": "UserPromptSubmit"}')), \
                            mock.patch("sys.stdout", out):
                        style_reminder.main()
                    self.assertEqual(style_reminder.LINE in out.getvalue(), style == "on")
                # An edited rules file without the section keeps the project map.
                with mock.patch.object(bootstrap, "RULES_TEXT", str(Path(root, "rules.md"))), \
                        mock.patch("projectmap.build", return_value="MAP"):
                    Path(root, "rules.md").write_text("# Rules\n\n## Write like a person\n\nx\n", encoding="utf-8")
                    self.assertEqual(bootstrap.rules_line(root), "MAP")
        finally:
            shutil.rmtree(root)


class BakpackRename(unittest.TestCase):
    # /bakpack moves the original to <name>.bakpack, and moves it back when the pointer write fails.
    def test_original_moves_whole_and_comes_back_on_failure(self):
        import pack_instructions
        root = tempfile.mkdtemp()
        path = Path(root, "CLAUDE.md")
        original = "".join("Rule %d: keep it short.\r\n" % n for n in range(400)).encode("utf-8")
        path.write_bytes(original)
        args = (path, "CLAUDE", "CLAUDE.md", Path(root, "img"), "opus", {})
        try:
            with mock.patch.object(pack_instructions, "draw", return_value=([Path(root, "a.png")], 1)):
                with mock.patch("common.write_text_atomic", return_value=False):
                    self.assertTrue(pack_instructions.convert_one(*args).startswith("failed"))
                self.assertEqual(path.read_bytes(), original)
                self.assertFalse(Path(root, "CLAUDE.md.bakpack").exists())
                pack_instructions.convert_one(*args)
            self.assertEqual(Path(root, "CLAUDE.md.bakpack").read_bytes(), original)
            self.assertIn(pack_instructions.OPEN, path.read_text(encoding="utf-8"))
        finally:
            shutil.rmtree(root)

    def test_read_only_original_comes_back_and_leaves_no_bakpack(self):
        import pack_instructions
        import stat
        root = tempfile.mkdtemp()
        path = Path(root, "CLAUDE.md")
        original = "".join("Rule %d: keep it short.\n" % n for n in range(400)).encode("utf-8")
        path.write_bytes(original)
        os.chmod(path, stat.S_IREAD)
        state = {}
        try:
            with mock.patch.object(pack_instructions, "draw", return_value=([Path(root, "a.png")], 1)):
                pack_instructions.convert_one(path, "CLAUDE", "CLAUDE.md", Path(root, "img"), "opus", state)
            self.assertTrue(pack_instructions.restore(path, state))
            self.assertEqual(path.read_bytes(), original)
            self.assertFalse(Path(root, "CLAUDE.md.bakpack").exists())
        finally:
            shutil.rmtree(root)


class KeyRowFileName(unittest.TestCase):
    # Issue #3: a long file name drew over the "=same line" entry of the key row.
    @unittest.skipUnless(common.ensure_pillow(), "Pillow, freetype or NumPy is missing")
    def test_long_name_gets_its_own_row_and_short_name_shares(self):
        from PIL import ImageFont
        font = ImageFont.truetype(str(Path(codepack.__file__).parents[1] / "fonts" / "Inter-SemiBold.ttf"), 14)
        rows = lambda: [[p[0].strip() for p in row] for row in codepack.legend_rows(font, 700)]
        try:
            codepack._LEGEND_TITLE = "file=chapter_card_" + "x" * 120 + ".gd"
            self.assertEqual(rows()[0], [codepack._LEGEND_TITLE])
            codepack._LEGEND_TITLE = "file=a.gd"
            self.assertEqual(rows()[0][-1], "file=a.gd")
            self.assertEqual(len(rows()), 2)
        finally:
            codepack._LEGEND_TITLE = ""


class LookAlikeGrep(unittest.TestCase):
    # Issue #4: a model copies the Cyrillic ЕР-0042 from an image as the Latin EP-0042.
    def setUp(self):
        self.root = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.root, ".claude", "tmp"))
        self.env = mock.patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": self.root})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        shutil.rmtree(self.root)

    def search(self, rewrite=True):
        with mock.patch.object(grep_gate, "may_rewrite", lambda event: rewrite):
            return grep_gate.look_alike_search({}, {"pattern": "EP-0042", "path": "."})

    def test_twin_matches_both_spellings(self):
        # The Latin EP-0042 in files that no image showed must still match.
        common.note_look_alikes("Petrov | ЕР-0042 | open\n")
        pattern = self.search()["hookSpecificOutput"]["updatedInput"]["pattern"]
        self.assertEqual(pattern, "[EЕ][PР]-0042")

    def test_asking_mode_denies_once(self):
        common.note_look_alikes("Petrov ЕР-0042\n")
        self.assertEqual(self.search(rewrite=False)["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertIsNone(self.search(rewrite=False))

    def test_bash_search_gets_the_real_spelling(self):
        common.note_look_alikes("Petrov ЕР-0042\n")
        with mock.patch.object(grep_gate, "may_rewrite", lambda event: True):
            out = grep_gate.look_alike_search({}, {"command": 'grep -n "EP-0042" payments.md'}, "command")
        self.assertEqual(out["hookSpecificOutput"]["updatedInput"]["command"],
                         'grep -n "[EЕ][PР]-0042" payments.md')
        self.assertFalse(source_gate.FIXED_STRINGS.search('grep -n "EP-0042" /c/Users/x/payments.md'))
        self.assertTrue(source_gate.FIXED_STRINGS.search('grep -nF "EP-0042" payments.md'))

    def test_rejected_edit_gets_the_exact_line_after_the_batch(self):
        # Claude Code 2.1.300 rejects this Edit before the PreToolUse gate runs.
        path = os.path.join(self.root, "invoices.md")
        Path(path).write_text("| Petrov | ЕР-0042 | open |\n", encoding="utf-8")
        call = {"tool_name": "Edit", "tool_input": {"file_path": path, "old_string": "| Petrov | EP-0042 | open |"},
                "tool_response": "<tool_use_error>String to replace not found in file.</tool_use_error>"}
        reasons = edit_gate.failed_edit_reasons({"tool_calls": [call]})
        self.assertEqual(len(reasons), 1)
        self.assertIn("ЕР-0042", reasons[0])

    def test_latin_text_saves_nothing(self):
        common.note_look_alikes("Becker EP-0042 OK\n")
        self.assertIsNone(self.search())


class ExactTextForLookAlikes(unittest.TestCase):
    # Cyrillic "Ваш номер ЕР-0042 оплачен" holds В, а, Е, Р, о, р, с, which
    # look like Latin B, a, E, P, o, p, c in an image.
    CYRILLIC = ("\u0412\u0430\u0448 \u043d\u043e\u043c\u0435\u0440 \u0415\u0420-0042 "
                "\u043e\u043f\u043b\u0430\u0447\u0435\u043d\n") * 120

    def setUp(self):
        self.root = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.root, ".claude", "tmp"))
        self.env = mock.patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": self.root})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        shutil.rmtree(self.root)

    def log(self):
        path = Path(self.root, ".claude", "densepack-vault", "why-text.log")
        return path.read_text(encoding="utf-8") if path.is_file() else ""

    def test_bash_output_with_cyrillic_stays_text(self):
        event = {"tool_name": "Bash", "session_id": "s", "tool_response": {"stdout": self.CYRILLIC}}
        self.assertIsNone(bash_image.image_output(event))
        self.assertIn("bash holds Cyrillic letters", self.log())

    # The Read check runs after the font check, which needs Pillow.
    @unittest.skipUnless(common.ensure_pillow(), "Pillow, freetype or NumPy is missing")
    def test_read_of_cyrillic_file_stays_text(self):
        path = os.path.join(self.root, "notes.md")
        Path(path).write_text(self.CYRILLIC, encoding="utf-8")
        event = {"tool_name": "Read", "session_id": "s", "tool_input": {"file_path": path}}
        with mock.patch.object(drop_read_gate, "gets_images", lambda event: True):
            self.assertIsNone(drop_read_gate.route(event, post=True))
            self.assertFalse(drop_read_gate.draws_on_read(path, event))
        # With the default lines, the note of a file of Cyrillic lines costs more than its images save
        self.assertIn("read price", self.log())

    def test_brief_and_report_with_cyrillic_stay_text(self):
        brief = {"tool_name": "Agent", "session_id": "s", "tool_input": {"prompt": self.CYRILLIC}}
        with mock.patch.object(brief_pack, "read_event", lambda: brief), \
                mock.patch("sys.stdout", new_callable=io.StringIO) as out:
            brief_pack.main()
        self.assertEqual(out.getvalue(), "")
        report = {"session_id": "s", "agent_id": "a1", "last_assistant_message": self.CYRILLIC}
        with mock.patch.object(subagent_stop, "read_event", lambda: report):
            self.assertEqual(subagent_stop.main(), 0)
        self.assertFalse(common.report_swap_path("a1").exists())
        self.assertIn("brief holds Cyrillic letters", self.log())
        self.assertIn("report holds Cyrillic letters", self.log())

    def test_each_look_alike_kind(self):
        reason = common.exact_text_reason
        self.assertIn("Greek", reason("\u039a\u03b1\u03bb\u03b7\u03bc\u03ad\u03c1\u03b1"))
        self.assertIn("spaces", reason("total\u00a0100"))
        self.assertIn("dash", reason("total \u2212100"))
        self.assertIsNone(reason("2010\u20132020 \u2014 en and em dashes stay images"))
        self.assertIsNone(reason("plain ASCII output, as before - 0123 IlO0\n" * 40))

    def test_setting_off_gives_images_again(self):
        common.write_settings({"exacttext": "off"})
        self.assertIsNone(common.exact_text_reason(self.CYRILLIC))

    def test_long_markdown_table_stays_text(self):
        rows = ["| n | code |", "|---|---|"] + ["| %d | EP-%04d |" % (n, n) for n in range(10)]
        self.assertTrue(drop_read_gate.markdown_table(os.linesep.join(rows)))
        self.assertFalse(drop_read_gate.markdown_table(os.linesep.join(rows[:-1])))

    def test_utf8_bom_alone_keeps_images(self):
        self.assertIsNone(common.exact_text_reason("\ufeffplain ASCII, as before\n"))

    def test_lines_mode_notes_only_matching_lines(self):
        common.write_settings({"exacttext": "lines"})
        note = common.exact_lines_text("plain\n\u0412\u0430\u0448 EP-0042\nplain\n")
        self.assertIn("2: \u0412\u0430\u0448 EP-0042", note)
        self.assertNotIn("1: plain", note)
        self.assertNotIn("\r", common.exact_lines_text("plain\r\n\u0412\u0430\u0448 EP-0042\r\n"))

    def test_strict_keeps_en_and_em_dashes_as_text(self):
        common.write_settings({"exacttext": "strict"})
        self.assertIn("en and em", common.exact_text_reason("unit 12345\u2013A"))

    def test_relative_word_paths_are_found(self):
        found = lambda resp: [m.group(1) for m in pointer.WORD_REL_IN_OUTPUT.finditer(str(resp))]
        self.assertEqual(found({"filenames": ["docs/memo.docx"]}), ["docs/memo.docx"])
        self.assertEqual(found({"stdout": "a.txt\n./old/Notes.DOC\n"}), ["./old/Notes.DOC"])
        self.assertEqual(found({"stdout": "/home/u/docs/memo.docx"}), [])

    def test_subagent_transcript_found_in_custom_config_dir(self):
        with tempfile.TemporaryDirectory() as config:
            sub = Path(config, "projects", "p", "s", "subagents")
            sub.mkdir(parents=True)
            (sub / "agent-abc.jsonl").write_text("")
            with mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": config}):
                self.assertEqual(common.agent_transcript("abc"), sub / "agent-abc.jsonl")


if __name__ == "__main__":
    unittest.main()
