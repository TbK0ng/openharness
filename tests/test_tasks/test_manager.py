"""Test tasks/manager.py background task subsystem.

Background command tasks were previously untested. These cover lifecycle,
output capture, truncation, and failure reporting.
"""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from openharness.tasks.manager import TaskManager
from openharness.tasks.types import Task


def _wait(task, timeout=60):
    task.thread.join(timeout=timeout)
    return task


class TestTaskTail(unittest.TestCase):
    def test_tail_returns_last_n_chars(self):
        task = Task(task_id="t1", kind="command", description="d", output="abcdef")
        self.assertEqual(task.tail(3), "def")

    def test_tail_of_short_output_returns_everything(self):
        task = Task(task_id="t1", kind="command", description="d", output="ab")
        self.assertEqual(task.tail(10), "ab")

    def test_tail_of_empty_output(self):
        task = Task(task_id="t1", kind="command", description="d")
        self.assertEqual(task.tail(), "")


class TestCommandTasks(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="oh_test_"))
        self.manager = TaskManager(str(self.dir))

    def _script(self, name, body):
        path = self.dir / name
        path.write_text(body, encoding="utf-8")
        return f'"{sys.executable}" "{path}"'

    def test_successful_command_finishes(self):
        task = _wait(self.manager.create_command(
            "hello", self._script("ok.py", "print('hi')")))

        self.assertEqual(task.status, "finished")
        self.assertIn("hi", task.output)
        self.assertIsNone(task.error)

    def test_failing_command_reports_exit_code(self):
        task = _wait(self.manager.create_command(
            "boom", self._script("bad.py", "import sys; sys.exit(3)")))

        self.assertEqual(task.status, "failed")
        self.assertIn("exit code 3", task.error)

    def test_output_is_capped(self):
        script = self._script(
            "flood.py",
            "line = 'y' * 999\nfor _ in range(400):\n    print(line)\n",
        )
        task = _wait(self.manager.create_command("flood", script))

        self.assertEqual(task.status, "finished")
        self.assertEqual(len(task.output), 200_000)
        # A self-copy inside the truncation branch would repeat a block.
        self.assertEqual({len(x) for x in task.output.splitlines()}, {999})

    def test_tasks_are_registered_and_listed(self):
        task = _wait(self.manager.create_command("one", self._script("a.py", "pass")))

        self.assertIs(self.manager.get(task.task_id), task)
        self.assertIn(task.task_id, [t.task_id for t in self.manager.list()])
        self.assertIn(task.task_id, self.manager.summary())

    def test_get_unknown_task_returns_none(self):
        self.assertIsNone(self.manager.get("task-999"))

    def test_summary_when_empty(self):
        self.assertEqual(self.manager.summary(), "(no background tasks)")

    def test_stop_unknown_task_returns_none(self):
        self.assertIsNone(self.manager.stop("task-999"))

    def test_stop_kills_running_process(self):
        import time

        script = self._script("slow.py", "import time\nprint('up', flush=True)\ntime.sleep(30)\n")
        task = self.manager.create_command("slow", script)
        time.sleep(1.5)
        self.assertIsNotNone(task.process)
        self.assertIsNone(task.process.poll(), "process should still be running")

        stopped = self.manager.stop(task.task_id)

        self.assertIs(stopped, task)
        self.assertEqual(task.status, "stopped")

        # kill() signals; the OS may need a moment to reap it.
        for _ in range(50):
            if task.process.poll() is not None:
                break
            time.sleep(0.1)
        self.assertIsNotNone(task.process.poll(), "process should be killed")

    def test_update_changes_status_and_appends_note(self):
        task = Task(task_id="t1", kind="command", description="d", output="base")
        self.manager._tasks[task.task_id] = task

        updated = self.manager.update("t1", status="paused", note="checkpoint")

        self.assertEqual(updated.status, "paused")
        self.assertIn("base", updated.output)
        self.assertIn("[note] checkpoint", updated.output)


class TestBackgroundAgent(unittest.TestCase):
    def test_agent_task_uses_its_own_llm(self):
        import openharness.engine.query_engine as qe
        from openharness.engine.query_engine import Engine

        with mock.patch.object(qe, "build_llm", return_value=object()):
            engine = Engine(cwd=str(Path(tempfile.mkdtemp(prefix="oh_test_"))))
            ctx = engine.create_context()
        parent_llm = ctx.llm
        seen = {}

        def fake_run(sub):
            seen["llm"] = sub.llm
            return "agent-done"

        with mock.patch("openharness.engine.query.run_sync", fake_run), \
             mock.patch("openharness.api.client.build_llm",
                        return_value=object()):
            task = engine.tasks.create_agent(ctx, "d", "p")
            _wait(task)

        self.assertEqual(task.output, "agent-done")
        self.assertIsNot(seen["llm"], parent_llm)


class TestTaskPersistence(unittest.TestCase):
    """Tasks are written to <root>/tasks/*.json so history survives restarts."""

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="oh_test_"))

    def _script(self, body):
        path = self.dir / "s.py"
        path.write_text(body, encoding="utf-8")
        return f'"{sys.executable}" "{path}"'

    def test_task_file_written_per_task(self):
        manager = TaskManager(str(self.dir))
        task = _wait(manager.create_command("one", self._script("print('x')")))

        path = self.dir / "tasks" / f"{task.task_id}.json"
        self.assertTrue(path.exists())
        self.assertEqual(path.parent.name, "tasks")

    def test_history_survives_new_manager(self):
        first = TaskManager(str(self.dir))
        task = _wait(first.create_command("persisted", self._script("print('kept')")))

        second = TaskManager(str(self.dir))

        reloaded = second.get(task.task_id)
        self.assertIsNotNone(reloaded)
        self.assertEqual(reloaded.status, "finished")
        self.assertIn("kept", reloaded.output)

    def test_counter_does_not_collide_after_reload(self):
        first = TaskManager(str(self.dir))
        a = _wait(first.create_command("a", self._script("pass")))

        second = TaskManager(str(self.dir))
        b = _wait(second.create_command("b", self._script("pass")))

        self.assertNotEqual(a.task_id, b.task_id)
        self.assertEqual(len(second.list()), 2)

    def test_running_task_from_dead_session_marked_interrupted(self):
        first = TaskManager(str(self.dir))
        # Simulate a task left "running" by a killed process.
        task = Task("task-7", "command", "orphan", status="running", output="partial")
        first.dir.mkdir(parents=True, exist_ok=True)
        first._persist(task)

        reloaded = TaskManager(str(self.dir)).get("task-7")

        self.assertEqual(reloaded.status, "interrupted")
        self.assertIn("partial", reloaded.output)

    def test_output_capped_on_disk(self):
        from openharness.tasks.manager import MAX_OUTPUT_CHARS

        manager = TaskManager(str(self.dir))
        task = Task("task-9", "command", "big", output="y" * (MAX_OUTPUT_CHARS + 5000))
        manager.dir.mkdir(parents=True, exist_ok=True)
        manager._persist(task)

        import json
        raw = json.loads((self.dir / "tasks" / "task-9.json").read_text(encoding="utf-8"))
        self.assertEqual(len(raw["output"]), MAX_OUTPUT_CHARS)

    def test_corrupt_task_file_is_skipped(self):
        (self.dir / "tasks").mkdir()
        (self.dir / "tasks" / "task-1.json").write_text("{not json", encoding="utf-8")

        manager = TaskManager(str(self.dir))

        self.assertEqual(manager.list(), [])


if __name__ == "__main__":
    unittest.main()
