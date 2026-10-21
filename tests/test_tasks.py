"""Test tasks/manager.py background task subsystem.

Background command tasks were previously untested. These cover lifecycle,
output capture, truncation, and failure reporting.
"""
import sys
import tempfile
import unittest
from pathlib import Path

from openharness.tasks.manager import Task, TaskManager


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


if __name__ == "__main__":
    unittest.main()
