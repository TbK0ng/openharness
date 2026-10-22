"""Test cli.py (ch.12 step 1): argument parsing, slash commands, interactive loop."""
import io
import os
import shutil
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from openharness.cli import _interactive_ask, build_parser, main, run_once
from openharness.engine.query_engine import Engine

TMP_ROOT = Path(__file__).resolve().parents[1] / "_tmp_tests"


def _fresh_dir(name: str) -> Path:
    d = TMP_ROOT / name
    if d.exists():
        shutil.rmtree(d)
    d.mkdir(parents=True)
    return d


class TestArgParsing(unittest.TestCase):
    def test_defaults(self):
        ns = build_parser().parse_args([])
        self.assertEqual(ns.prompt, [])
        self.assertIsNone(ns.mode)
        self.assertIsNone(ns.cwd)

    def test_positional_prompt_joined(self):
        ns = build_parser().parse_args(["读一下", "a.py"])
        self.assertEqual(ns.prompt, ["读一下", "a.py"])

    def test_mode_choices(self):
        for m in ("default", "plan", "full-auto"):
            self.assertEqual(build_parser().parse_args(["--mode", m]).mode, m)
        with self.assertRaises(SystemExit):
            build_parser().parse_args(["--mode", "bogus"])

    def test_cwd_and_max_turns(self):
        ns = build_parser().parse_args(["--cwd", "x", "--max-turns", "5"])
        self.assertEqual(ns.cwd, "x")
        self.assertEqual(ns.max_turns, 5)


class TestSlashCommands(unittest.TestCase):
    """斜杠命令走 CommandRegistry，不需要 LLM。"""

    def setUp(self):
        self.dir = _fresh_dir("cli")
        self.engine = Engine(cwd=str(self.dir))

    def test_help_lists_commands(self):
        out = self.engine.commands.get("help").fn("")
        self.assertIn("help", out)
        self.assertIn("mode", out)

    def test_mode_command_switches_permission_mode(self):
        cmd = self.engine.commands.get("mode")
        self.assertIn("full-auto", cmd.fn("full-auto"))
        self.assertEqual(self.engine.permissions.mode, "full-auto")

    def test_unknown_mode_reports_choices_and_keeps_mode(self):
        before = self.engine.permissions.mode
        out = self.engine.commands.get("mode").fn("bogus")
        self.assertIn("未知权限模式", out)
        self.assertIn("full-auto", out)
        self.assertEqual(self.engine.permissions.mode, before)

    def test_mode_without_args_lists_all_modes(self):
        out = self.engine.commands.get("mode").fn("")
        self.assertIn("当前权限模式: default", out)
        for mode in ("default", "plan", "full-auto"):
            self.assertIn(mode, out)
        self.assertIn("/mode <模式>", out)

    def test_mode_menu_number_switches_mode(self):
        with mock.patch("openharness.engine.query_engine.is_tty",
                        return_value=True), \
             mock.patch("builtins.input", return_value="2"):
            out = self.engine.commands.get("mode").fn("")
        self.assertIn("plan", out)
        self.assertEqual(self.engine.permissions.mode, "plan")

    def test_mode_menu_cancel_keeps_mode(self):
        with mock.patch("openharness.engine.query_engine.is_tty",
                        return_value=True), \
             mock.patch("builtins.input", return_value=""):
            out = self.engine.commands.get("mode").fn("")
        self.assertIn("未修改", out)
        self.assertEqual(self.engine.permissions.mode, "default")

    def test_permission_allow_adds_tool_to_session_allowlist(self):
        out = self.engine.commands.get("permission").fn("allow Write")
        self.assertIn("Write", out)
        decision = self.engine.permissions.check(
            "Write", {"file_path": "a", "content": "b"},
            type("C", (), {"registry": self.engine.registry})())
        self.assertEqual(decision.verdict, "allow")

    def test_permission_save_persists_and_keeps_other_settings(self):
        import json
        settings = self.engine.oh_dir / "settings.json"
        settings.write_text(json.dumps({"provider": "lmstudio"}), encoding="utf-8")
        self.engine.commands.get("mode").fn("plan")
        self.engine.commands.get("permission").fn("allow Write")

        self.engine.commands.get("permission").fn("save")

        saved = json.loads(settings.read_text(encoding="utf-8"))
        self.assertEqual(saved["provider"], "lmstudio")
        self.assertEqual(saved["permissions"]["mode"], "plan")
        self.assertEqual(saved["permissions"]["allow_tools"], ["Write"])

    def test_permission_reset_clears_session_allows(self):
        self.engine.commands.get("permission").fn("allow Write")
        self.engine.commands.get("permission").fn("reset")
        self.assertEqual(self.engine.permissions.allowed_tools, set())

    def test_saved_permissions_load_in_a_new_engine(self):
        self.engine.commands.get("permission").fn("allow Write")
        self.engine.commands.get("mode").fn("plan")
        self.engine.commands.get("permission").fn("save")

        fresh = Engine(cwd=str(self.dir))
        self.assertEqual(fresh.permissions.mode, "plan")
        self.assertIn("Write", fresh.permissions.allowed_tools)

    def test_tools_command_lists_all_tools(self):
        out = self.engine.commands.get("tools").fn("")
        self.assertIn("Read", out)
        self.assertIn(str(len(self.engine.registry.list_tools())), out)
        self.assertIn("MemorySave", out)

    def test_skills_and_memory_commands_render(self):
        self.assertTrue(self.engine.commands.get("skills").fn(""))
        self.assertTrue(self.engine.commands.get("memory").fn(""))

    def test_clear_command_empties_history(self):
        ctx = self.engine.create_context()
        ctx.messages.append({"role": "user", "content": "hi"})
        self.engine.commands.get("clear").fn("")
        self.assertEqual(ctx.messages, [])


class TestInteractiveLoop(unittest.TestCase):
    """用假的 input() / run_query_sync 驱动主循环。"""

    def setUp(self):
        self.dir = _fresh_dir("cli_loop")
        # 测试环境下禁用 prompt_toolkit，强制走 builtins.input 分支
        patcher = mock.patch.dict(os.environ, {"OPENHARNESS_PLAIN_INPUT": "1"})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_exit_keyword_ends_session(self):
        with mock.patch("builtins.input", side_effect=["exit"]), \
             mock.patch("openharness.cli.run_once", return_value="ok") as run:
            rc = main(["--cwd", str(self.dir), "--no-banner"])
        self.assertEqual(rc, 0)
        run.assert_not_called()

    def test_prompt_sent_to_agent_loop(self):
        with mock.patch("builtins.input", side_effect=["exit"]), \
             mock.patch("openharness.cli.run_once", return_value="DONE") as run:
            main(["--cwd", str(self.dir), "--no-banner", "hello"])
        self.assertEqual(run.call_count, 1)

    def test_slash_command_does_not_call_llm(self):
        with mock.patch("builtins.input", side_effect=["/help", "exit"]), \
             mock.patch("openharness.cli.run_once") as run:
            main(["--cwd", str(self.dir), "--no-banner"])
        run.assert_not_called()

    def test_agent_error_does_not_kill_session(self):
        """单轮失败应继续会话（第 5 章：错误是结果，不是崩溃）。"""
        with mock.patch("builtins.input", side_effect=["hi", "exit"]), \
             mock.patch("openharness.cli.run_once", side_effect=RuntimeError("boom")):
            rc = main(["--cwd", str(self.dir), "--no-banner"])
        self.assertEqual(rc, 0)

    def test_empty_input_ignored(self):
        with mock.patch("builtins.input", side_effect=["", "exit"]), \
             mock.patch("openharness.cli.run_once") as run:
            main(["--cwd", str(self.dir), "--no-banner"])
        run.assert_not_called()


class TestAskUserWiring(unittest.TestCase):
    """第 12 章：CLI 必须把权限审批接到真实输入，否则被静默拒绝。"""

    def setUp(self):
        self.dir = _fresh_dir("cli_ask")
        self.engine = Engine(cwd=str(self.dir))

    def _ctx_stub(self):
        from types import SimpleNamespace
        return SimpleNamespace(
            messages=[], max_turns=30,
            ask_user=lambda q: "", on_event=None,
        )

    def test_interactive_mode_wires_real_ask(self):
        with mock.patch.object(self.engine, "create_context",
                               return_value=self._ctx_stub()) as cc, \
             mock.patch("openharness.cli.run_query_sync", return_value="ok"):
            run_once(self.engine, "hi", None, ask_user=_interactive_ask)
        ctx = cc.return_value
        self.assertIs(ctx.ask_user, _interactive_ask)

    def test_one_shot_defaults_to_non_interactive_deny(self):
        with mock.patch.object(self.engine, "create_context",
                               return_value=self._ctx_stub()) as cc, \
             mock.patch("openharness.cli.run_query_sync", return_value="ok"):
            run_once(self.engine, "hi", None)
        self.assertEqual(cc.return_value.ask_user("q"), "")

    def test_interactive_ask_reads_input(self):
        with mock.patch("builtins.input", return_value="y"):
            self.assertEqual(_interactive_ask("允许 rm -rf?"), "y")

    def test_interactive_ask_eof_returns_empty(self):
        with mock.patch("builtins.input", side_effect=EOFError):
            self.assertEqual(_interactive_ask("q"), "")


if __name__ == "__main__":
    unittest.main()
