"""Test workflow tools that previously had no coverage:
CronCreate/CronDelete, TaskCreate/TaskStop/TaskUpdate, Enter/ExitWorktree.
"""
import asyncio
import tempfile
import unittest
from pathlib import Path

from openharness.engine.query_engine import Engine
from openharness.hooks.executor import execute_tool_with_hooks
from openharness.tools.enter_worktree_tool import EnterWorktreeTool
from openharness.tools.exit_worktree_tool import ExitWorktreeTool


class _EngineCase(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="oh_test_"))
        self.engine = Engine(cwd=str(self.dir))
        self.ctx = self.engine.create_context()
        self.ctx.permissions.set_mode("full-auto")

    def run_tool(self, name, args):
        return asyncio.run(execute_tool_with_hooks(
            self.ctx, {"name": name, "arguments": args}))


class TestCronTools(_EngineCase):
    def test_create_then_list_then_delete(self):
        created = self.run_tool("CronCreate", {
            "schedule": "*/5 * * * *", "kind": "command", "command": "echo hi"})
        self.assertFalse(created.is_error)
        job_id = created.output.split()[3].rstrip(":")

        listed = self.run_tool("CronList", {})
        self.assertIn("echo hi", listed.output)

        deleted = self.run_tool("CronDelete", {"job_id": job_id})
        self.assertFalse(deleted.is_error)
        self.assertEqual(self.engine.cron.list(), [])

    def test_delete_unknown_job(self):
        result = self.run_tool("CronDelete", {"job_id": "cron-999"})
        self.assertFalse(result.is_error)
        self.assertIn("cron-999", result.output)


class TestBackgroundTaskTools(_EngineCase):
    def test_create_requires_kind(self):
        result = self.run_tool("TaskCreate", {"description": "d"})
        self.assertTrue(result.is_error)
        self.assertIn("kind", result.error)

    def test_create_command_task_then_stop(self):
        created = self.run_tool("TaskCreate", {
            "description": "bg", "kind": "command", "command": "echo done"})
        self.assertFalse(created.is_error)
        task_id = created.output.split()[2]

        self.assertIsNotNone(self.engine.tasks.get(task_id))
        task = self.engine.tasks.get(task_id)
        if task.thread:
            task.thread.join(timeout=30)

        stopped = self.run_tool("TaskStop", {"task_id": task_id})
        self.assertFalse(stopped.is_error)

    def test_update_task_status(self):
        created = self.run_tool("TaskCreate", {
            "description": "bg", "kind": "command", "command": "echo x"})
        task_id = created.output.split()[2]
        task = self.engine.tasks.get(task_id)
        if task.thread:
            task.thread.join(timeout=30)

        result = self.run_tool("TaskUpdate", {"task_id": task_id, "status": "paused"})
        self.assertFalse(result.is_error)
        self.assertEqual(self.engine.tasks.get(task_id).status, "paused")


class TestWorktreeTools(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="oh_test_"))
        (self.dir / "a.txt").write_text("main", encoding="utf-8")
        self.engine = Engine(cwd=str(self.dir))
        self.ctx = self.engine.create_context()
        self.ctx.permissions.set_mode("full-auto")

    def test_enter_copies_workspace_and_switches_cwd(self):
        result = asyncio.run(EnterWorktreeTool().execute({"name": "wt"}, self.ctx))

        self.assertFalse(result.is_error)
        worktree = Path(self.ctx.cwd)
        self.assertEqual(worktree.name, "wt")
        self.assertTrue((worktree / "a.txt").exists())
        # The worktree root must not be copied into itself.
        self.assertFalse((worktree / ".openharness_worktrees").exists())

    def test_exit_restores_original_cwd(self):
        asyncio.run(EnterWorktreeTool().execute({"name": "wt"}, self.ctx))
        result = asyncio.run(ExitWorktreeTool().execute({}, self.ctx))

        self.assertFalse(result.is_error)
        self.assertEqual(Path(self.ctx.cwd), self.dir)

    def test_exit_without_entering_is_an_error(self):
        result = asyncio.run(ExitWorktreeTool().execute({}, self.ctx))

        self.assertTrue(result.is_error)
        self.assertIn("Not currently inside a worktree", result.error)


if __name__ == "__main__":
    unittest.main()
