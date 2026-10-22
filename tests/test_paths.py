"""Test the .oh/ configuration-directory convention (openharness/paths.py).

All runtime state — config, memory, task board, cron, worktrees, plugins — must
live under <project>/.oh/ rather than scattered across the project root.
"""
import asyncio
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from openharness.engine.query_engine import Engine
from openharness.paths import DEFAULT_OH_DIRNAME, ensure_oh_dir, oh_dir, oh_path


class TestPathHelpers(unittest.TestCase):
    def test_default_dirname(self):
        self.assertEqual(DEFAULT_OH_DIRNAME, ".oh")

    def test_oh_dir_is_relative_to_root(self):
        root = Path(tempfile.mkdtemp(prefix="oh_test_"))
        self.assertEqual(oh_dir(root), root / ".oh")

    def test_oh_dir_is_not_created_implicitly(self):
        root = Path(tempfile.mkdtemp(prefix="oh_test_"))
        self.assertFalse(oh_dir(root).exists())

    def test_ensure_creates(self):
        root = Path(tempfile.mkdtemp(prefix="oh_test_"))
        created = ensure_oh_dir(root)
        self.assertTrue(created.is_dir())
        self.assertEqual(created, root / ".oh")

    def test_oh_path(self):
        root = Path(tempfile.mkdtemp(prefix="oh_test_"))
        self.assertEqual(oh_path("settings.json", root), root / ".oh" / "settings.json")

    def test_env_override(self):
        root = Path(tempfile.mkdtemp(prefix="oh_test_"))
        with mock.patch.dict(os.environ, {"OH_DIR": ".custom"}):
            self.assertEqual(oh_dir(root), root / ".custom")


class TestEngineLayout(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="oh_test_"))
        self.engine = Engine(cwd=str(self.root))

    def test_everything_under_oh(self):
        oh = self.root / ".oh"
        self.assertEqual(self.engine.oh_dir, oh)
        self.assertTrue(self.engine.memory.dir.is_relative_to(oh))
        self.assertTrue(self.engine.memory.index.is_relative_to(oh))
        self.assertTrue(self.engine.cron._file.is_relative_to(oh))
        for d in self.engine.skills.dirs:
            self.assertTrue(d.is_relative_to(oh), f"{d} escapes .oh")

    def test_project_root_stays_clean_on_init(self):
        # Constructing the engine must not scatter files into the project root.
        self.assertEqual([p.name for p in self.root.iterdir()], [".oh"])

    def test_oh_dir_survives_engine_construction(self):
        self.assertTrue((self.root / ".oh").is_dir())

    def test_context_carries_oh_dir(self):
        ctx = self.engine.create_context()
        self.assertEqual(Path(ctx.oh_dir), self.root / ".oh")

    def test_config_read_from_oh(self):
        root = Path(tempfile.mkdtemp(prefix="oh_test_"))
        (root / ".oh").mkdir()
        (root / ".oh" / "settings.json").write_text(
            json.dumps({"max_turns": 7, "provider": "deepseek"}), encoding="utf-8")

        engine = Engine(cwd=str(root))

        self.assertEqual(engine.config["max_turns"], 7)
        self.assertEqual(engine.config["provider"], "deepseek")

    def test_oh_config_wins_over_legacy_root_config(self):
        root = Path(tempfile.mkdtemp(prefix="oh_test_"))
        (root / "settings.json").write_text(json.dumps({"max_turns": 3}), encoding="utf-8")
        (root / ".oh").mkdir()
        (root / ".oh" / "settings.json").write_text(json.dumps({"max_turns": 9}), encoding="utf-8")

        self.assertEqual(Engine(cwd=str(root)).config["max_turns"], 9)

    def test_legacy_root_config_still_read(self):
        root = Path(tempfile.mkdtemp(prefix="oh_test_"))
        (root / "settings.json").write_text(json.dumps({"max_turns": 3}), encoding="utf-8")

        self.assertEqual(Engine(cwd=str(root)).config["max_turns"], 3)


class TestStateLivesInOh(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="oh_test_"))
        self.engine = Engine(cwd=str(self.root))
        self.ctx = self.engine.create_context()
        self.ctx.permissions.set_mode("full-auto")

    def test_memory_files_under_oh(self):
        path = self.engine.memory.save("k", "d", "user", "body")
        self.assertTrue(path.is_relative_to(self.root / ".oh"))
        self.assertTrue(self.engine.memory.index.exists())
        self.assertTrue(self.engine.memory.index.is_relative_to(self.root / ".oh"))

    def test_task_board_under_oh(self):
        from openharness.tools.task_board_tools import CreateTaskTool

        asyncio.run(CreateTaskTool().execute({"subject": "s"}, self.ctx))

        self.assertTrue((self.root / ".oh" / ".tasks").is_dir())
        self.assertFalse((self.root / ".tasks").exists())

    def test_cron_persists_under_oh(self):
        self.engine.cron.create("* * * * *", "command", command="echo hi")
        self.assertTrue((self.root / ".oh" / "data" / "cron.json").exists())
        self.assertFalse((self.root / "data").exists())

    def test_worktree_under_oh(self):
        from openharness.tools.meta_worktree import EnterWorktreeTool, ExitWorktreeTool

        asyncio.run(EnterWorktreeTool().execute({"name": "wt"}, self.ctx))
        self.assertTrue((self.root / ".oh" / "worktrees" / "wt").is_dir())
        self.assertFalse((self.root / ".openharness_worktrees").exists())
        asyncio.run(ExitWorktreeTool().execute({}, self.ctx))

    def test_plugins_read_from_oh(self):
        root = Path(tempfile.mkdtemp(prefix="oh_test_"))
        plugin_dir = root / ".oh" / "plugins"
        plugin_dir.mkdir(parents=True)
        (plugin_dir / "p.py").write_text(
            "PLUGIN = {'name': 'p'}\ndef register(ctx):\n    pass\n", encoding="utf-8")

        self.assertEqual(Engine(cwd=str(root)).plugin_names, ["p"])


class TestInitCommand(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="oh_test_"))
        self.engine = Engine(cwd=str(self.root))
        self.engine.create_context()

    def test_creates_settings_in_oh(self):
        out = self.engine.commands.get("init").fn("")

        target = self.root / ".oh" / "settings.json"
        self.assertTrue(target.exists())
        self.assertIn(".oh", out)

    def test_does_not_overwrite_existing(self):
        target = self.root / ".oh" / "settings.json"
        target.write_text('{"max_turns": 5}', encoding="utf-8")

        out = self.engine.commands.get("init").fn("")

        self.assertIn("未覆盖", out)
        self.assertEqual(json.loads(target.read_text(encoding="utf-8"))["max_turns"], 5)

    def test_writes_builtin_defaults(self):
        out = self.engine.commands.get("init").fn("")

        target = self.root / ".oh" / "settings.json"
        self.assertIn("默认配置", out)
        config = json.loads(target.read_text(encoding="utf-8"))
        self.assertEqual(config["provider"], "deepseek")
        self.assertIn("permissions", config)


if __name__ == "__main__":
    unittest.main()
