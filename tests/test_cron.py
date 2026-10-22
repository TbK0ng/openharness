"""Test cron/manager.py (ch.5 scheduling subsystem).

Regression coverage for two gaps: CronManager required a Path (a str cwd
raised TypeError), and the module had no tests at all.
"""
import tempfile
import time
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

from openharness.cron.manager import CronManager, cron_due


class TestCronDue(unittest.TestCase):
    def test_every_minute_matches(self):
        self.assertTrue(cron_due("* * * * *", datetime(2026, 10, 21, 12, 34)))

    def test_fixed_minute_only_matches_that_minute(self):
        self.assertTrue(cron_due("30 * * * *", datetime(2026, 10, 21, 12, 30)))
        self.assertFalse(cron_due("30 * * * *", datetime(2026, 10, 21, 12, 31)))

    def test_step_and_range_fields(self):
        self.assertTrue(cron_due("*/15 * * * *", datetime(2026, 10, 21, 12, 45)))
        self.assertFalse(cron_due("*/15 * * * *", datetime(2026, 10, 21, 12, 46)))
        self.assertTrue(cron_due("* 9-11 * * *", datetime(2026, 10, 21, 10, 0)))
        self.assertFalse(cron_due("* 9-11 * * *", datetime(2026, 10, 21, 12, 0)))

    def test_malformed_schedule_never_matches(self):
        self.assertFalse(cron_due("* * *", datetime(2026, 10, 21, 12, 0)))


class TestCronManagerPersistence(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="oh_test_"))

    def test_accepts_str_cwd(self):
        # Regression: previously `cwd / "data"` raised TypeError for a str.
        manager = CronManager(str(self.dir))
        self.assertEqual(manager.cwd, self.dir)

    def test_accepts_path_cwd(self):
        manager = CronManager(self.dir)
        self.assertEqual(manager.cwd, self.dir)

    def test_create_and_persist(self):
        manager = CronManager(str(self.dir))
        job = manager.create("* * * * *", "command", command="echo hi")

        self.assertEqual(job.kind, "command")
        self.assertEqual(len(manager.list()), 1)
        self.assertTrue((self.dir / "data" / "cron.json").exists())

        reloaded = CronManager(str(self.dir))
        self.assertEqual(len(reloaded.list()), 1)
        self.assertEqual(reloaded.list()[0].command, "echo hi")

    def test_delete_removes_and_persists(self):
        manager = CronManager(str(self.dir))
        job = manager.create("0 * * * *", "agent", prompt="check")

        self.assertTrue(manager.delete(job.job_id))
        self.assertEqual(manager.list(), [])
        self.assertEqual(CronManager(str(self.dir)).list(), [])

    def test_delete_unknown_returns_false(self):
        self.assertFalse(CronManager(str(self.dir)).delete("cron-999"))

    def test_corrupt_file_falls_back_to_empty(self):
        (self.dir / "data").mkdir()
        (self.dir / "data" / "cron.json").write_text("{not json", encoding="utf-8")
        self.assertEqual(CronManager(str(self.dir)).list(), [])

    def test_job_ids_do_not_collide_after_reload(self):
        first = CronManager(str(self.dir))
        first.create("0 0 1 1 *", "command", command="a")
        first.create("0 0 1 1 *", "command", command="b")

        reloaded = CronManager(str(self.dir))
        third = reloaded.create("0 0 1 1 *", "command", command="c")
        self.assertEqual(third.job_id, "cron-3")
        self.assertEqual(len({j.job_id for j in reloaded.list()}), 3)


class TestCronScheduler(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="oh_test_"))

    def test_due_job_fires_once_and_marks_last_fired(self):
        manager = CronManager(str(self.dir))
        job = manager.create("* * * * *", "command", command="echo hi")
        fired = []
        manager._fire = lambda j: fired.append(j.job_id)

        manager.start()
        self.addCleanup(manager.stop)
        deadline = time.time() + 3
        while not fired and time.time() < deadline:
            time.sleep(0.05)

        self.assertEqual(fired, [job.job_id])
        reloaded = CronManager(str(self.dir))
        self.assertGreater(reloaded.list()[0].last_fired, 0)

    def test_run_now_triggers_without_waiting_for_schedule(self):
        manager = CronManager(str(self.dir))
        job = manager.create("0 0 1 1 *", "command", command="never")
        fired = []
        manager._fire = lambda j: fired.append(j.job_id)

        self.assertTrue(manager.run_now(job.job_id))
        self.assertEqual(fired, [job.job_id])
        self.assertFalse(manager.run_now("cron-999"))


class TestEngineCronWiring(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="oh_test_"))

    def test_engine_passes_tasks_and_starts_scheduler(self):
        import openharness.engine.query_engine as qe
        from openharness.engine.query_engine import Engine

        with mock.patch.object(qe, "build_llm", return_value=object()):
            engine = Engine(cwd=str(self.dir))

        self.assertIs(engine.cron.tasks, engine.tasks)
        self.assertEqual(engine.cron.workdir, engine.cwd)
        ctx = engine.create_context()
        self.assertIs(engine.cron.context, ctx)
        with mock.patch.object(engine.cron, "start") as start:
            engine.start_background()
        start.assert_called_once()

    def test_start_background_provides_context_for_agent_jobs(self):
        import openharness.engine.query_engine as qe
        from openharness.engine.query_engine import Engine

        with mock.patch.object(qe, "build_llm", return_value=object()):
            engine = Engine(cwd=str(self.dir))
        engine.cron.create("0 0 1 1 *", "agent", prompt="check")
        with mock.patch.object(engine.cron, "start"):
            engine.start_background()

        self.assertIsNotNone(engine.session)
        self.assertIs(engine.cron.context, engine.session.context)

    def test_cron_create_tool_starts_scheduler(self):
        import asyncio
        import openharness.engine.query_engine as qe
        from openharness.engine.query_engine import Engine
        from openharness.hooks.executor import execute_tool_with_hooks

        with mock.patch.object(qe, "build_llm", return_value=object()):
            engine = Engine(cwd=str(self.dir))
        ctx = engine.create_context()
        ctx.permissions.set_mode("full-auto")
        with mock.patch.object(engine.cron, "start") as start:
            result = asyncio.run(execute_tool_with_hooks(ctx, {
                "name": "CronCreate", "id": "c1",
                "arguments": {"schedule": "0 0 1 1 *", "kind": "command",
                              "command": "echo hi"},
            }))
        self.assertFalse(result.is_error)
        start.assert_called_once()


class TestCronCommand(unittest.TestCase):
    def setUp(self):
        import openharness.engine.query_engine as qe
        from openharness.engine.query_engine import Engine
        with mock.patch.object(qe, "build_llm", return_value=object()):
            self.engine = Engine(cwd=str(Path(tempfile.mkdtemp(prefix="oh_test_"))))
        self.cmd = self.engine.commands.get("cron")
        self.addCleanup(self.engine.cron.stop)

    def test_add_list_run_delete(self):
        out = self.cmd.fn("add 0 0 1 1 * command echo tick")
        self.assertIn("已创建 cron-1", out)
        jobs = self.engine.cron.list()
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].command, "echo tick")
        self.assertTrue(self.engine.cron.running)

        listed = self.cmd.fn("list")
        self.assertIn("调度器: 运行中", listed)
        self.assertIn("cron-1", listed)

        fired = []
        self.engine.cron._fire = lambda j: fired.append(j.job_id)
        self.assertIn("已立即触发 cron-1", self.cmd.fn("run cron-1"))
        self.assertEqual(fired, ["cron-1"])

        self.assertIn("已删除 cron-1", self.cmd.fn("delete cron-1"))
        self.assertEqual(self.engine.cron.list(), [])

    def test_add_rejects_bad_schedule_and_kind(self):
        self.assertIn("参数不足", self.cmd.fn("add * * * command echo x"))
        self.assertIn("未知任务类型", self.cmd.fn("add * * * * * script echo x"))
        with self.assertRaises(ValueError):
            self.engine.cron.create("* * *", "command", command="x")

    def test_unknown_job_ids(self):
        self.assertIn("任务不存在", self.cmd.fn("run cron-9"))
        self.assertIn("任务不存在", self.cmd.fn("delete cron-9"))


if __name__ == "__main__":
    unittest.main()
