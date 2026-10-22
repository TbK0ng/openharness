"""Test repl.py: 斜杠命令补全、参数补全、输入降级。"""
import os
import shutil
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from prompt_toolkit.document import Document

from openharness.commands.registry import CommandRegistry
from openharness.engine.query_engine import Engine
from openharness.repl import (HINTS, LineReader, SlashCommandCompleter,
                              _rewind_bindings, _status_text,
                              match_choices, match_commands, wants_repl)

TMP_ROOT = Path(__file__).resolve().parents[1] / "_tmp_tests"


def _fresh_dir(name: str) -> Path:
    d = TMP_ROOT / name
    if d.exists():
        shutil.rmtree(d)
    d.mkdir(parents=True)
    return d


def _completions(registry: CommandRegistry, text: str) -> list:
    doc = Document(text, cursor_position=len(text))
    return list(SlashCommandCompleter(registry).get_completions(doc, None))


class TestMatching(unittest.TestCase):
    def setUp(self):
        self.registry = CommandRegistry()
        self.registry.register("help", "帮助", lambda a: a)
        self.registry.register("memory", "记忆", lambda a: a)
        self.registry.register("mode", "模式", lambda a: a,
                               choices={"default": "默认", "plan": "只读"})

    def test_empty_fragment_lists_all_sorted(self):
        names = [c.name for c in match_commands(self.registry.list(), "")]
        self.assertEqual(names, ["help", "memory", "mode"])

    def test_prefix_matches_rank_before_contains(self):
        names = [c.name for c in match_commands(self.registry.list(), "mo")]
        self.assertEqual(names, ["mode", "memory"])

    def test_leading_slash_tolerated(self):
        self.assertEqual([c.name for c in match_commands(self.registry.list(), "/mod")],
                         ["mode"])

    def test_no_match(self):
        self.assertEqual(match_commands(self.registry.list(), "zzz"), [])

    def test_choice_prefix(self):
        cmd = self.registry.get("mode")
        self.assertEqual([v for v, _ in match_choices(cmd, "p")], ["plan"])
        self.assertEqual(len(match_choices(cmd, "")), 2)


class TestCompleter(unittest.TestCase):
    def setUp(self):
        self.registry = CommandRegistry()
        self.registry.register("help", "列出命令", lambda a: a)
        self.registry.register("mode", "切换模式", lambda a: a,
                               choices={"default": "默认", "plan": "只读"})

    def test_slash_lists_all_commands_with_help(self):
        items = _completions(self.registry, "/")
        self.assertEqual([c.text for c in items], ["help", "mode "])
        self.assertEqual(items[1].display_meta_text, "切换模式")

    def test_prefix_filters_and_replaces_typed_text(self):
        items = _completions(self.registry, "/mo")
        self.assertEqual([c.text for c in items], ["mode "])
        self.assertEqual(items[0].start_position, -2)

    def test_arg_completion_after_command(self):
        items = _completions(self.registry, "/mode p")
        self.assertEqual([c.text for c in items], ["plan"])
        self.assertEqual(items[0].start_position, -1)

    def test_no_completion_for_plain_text_or_unknown_command(self):
        self.assertEqual(_completions(self.registry, "hello"), [])
        self.assertEqual(_completions(self.registry, "/nope "), [])
        self.assertEqual(_completions(self.registry, "/mode plan x"), [])

    def test_real_engine_commands_complete(self):
        engine = Engine(cwd=str(_fresh_dir("repl_engine")))
        items = _completions(engine.commands, "/sk")
        self.assertEqual(items[0].text, "skills")
        items = _completions(engine.commands, "/mode full")
        self.assertEqual(items[0].text, "full-auto")

    def test_help_argument_completes_command_names(self):
        engine = Engine(cwd=str(_fresh_dir("repl_help")))
        items = _completions(engine.commands, "/help mo")
        self.assertEqual([c.text for c in items], ["mode"])
        self.assertEqual(items[0].display_meta_text, "查看/切换权限模式")


class TestLineReader(unittest.TestCase):
    def setUp(self):
        self.engine = Engine(cwd=str(_fresh_dir("repl_reader")))

    def test_plain_input_fallback_reads_builtin_input(self):
        with mock.patch("openharness.repl.wants_repl", return_value=False), \
             mock.patch("builtins.input", return_value="hi") as inp:
            reader = LineReader(self.engine)
            self.assertIsNone(reader.session)
            self.assertEqual(reader.read(), "hi")
            self.assertEqual(inp.call_count, 1)

    def test_ctrl_c_returns_empty_string(self):
        reader = LineReader(self.engine)
        session = mock.Mock()
        session.prompt.side_effect = KeyboardInterrupt
        reader.session = session
        self.assertEqual(reader.read(), "")

    def test_rewind_prefill_is_passed_to_prompt(self):
        reader = LineReader(self.engine)
        session = mock.Mock()
        session.prompt.return_value = "edited"
        reader.session = session
        self.assertEqual(reader.read("original"), "edited")
        self.assertEqual(session.prompt.call_args.kwargs["default"], "original")

    def test_double_escape_binding_is_registered(self):
        from prompt_toolkit.keys import Keys
        bindings = _rewind_bindings().get_bindings_for_keys(
            (Keys.Escape, Keys.Escape))
        self.assertEqual(len(bindings), 1)
        self.assertIn("Esc Esc", HINTS)

    def test_eof_propagates(self):
        reader = LineReader(self.engine)
        session = mock.Mock()
        session.prompt.side_effect = EOFError
        reader.session = session
        with self.assertRaises(EOFError):
            reader.read()

    def test_wants_repl_off_when_disabled_by_env(self):
        with mock.patch.dict(os.environ, {"OPENHARNESS_PLAIN_INPUT": "1"}):
            self.assertFalse(wants_repl())

    def test_status_text_reports_mode_model_and_tools(self):
        text = _status_text(self.engine)
        self.assertIn(self.engine.permissions.mode, text)
        self.assertIn(f"{len(self.engine.registry.list_tools())} tools", text)


if __name__ == "__main__":
    unittest.main()
