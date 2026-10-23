"""任务看板（s12）：TaskBoard 状态机 + 5 个工具。"""
import asyncio
import re
import tempfile
import unittest
from openharness.tasks.board import (
    TaskBoard, TaskBlockedError, TaskNotFoundError,
)
from openharness.tools.claim_task_tool import ClaimTaskTool
from openharness.tools.complete_task_tool import CompleteTaskTool
from openharness.tools.create_task_tool import CreateTaskTool
from openharness.tools.get_task_tool import GetTaskTool
from openharness.tools.list_tasks_tool import ListTasksTool


class _Ctx:
    def __init__(self, cwd):
        self.cwd = str(cwd)
        self.task_board = None
        self.displayed = []

    def display(self, s):
        self.displayed.append(str(s))


class TestTaskBoard(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.board = TaskBoard(self.dir.name)

    def tearDown(self):
        self.dir.cleanup()

    def test_create_and_get(self):
        t = self.board.create("write tests", "desc")
        self.assertEqual(t["status"], "pending")
        got = self.board.get(t["id"])
        self.assertEqual(got["subject"], "write tests")

    def test_missing_task_raises(self):
        with self.assertRaises(TaskNotFoundError):
            self.board.get("nope")

    def test_claim_blocked_raises(self):
        a = self.board.create("a")
        b = self.board.create("b", blocked_by=[a["id"]])
        with self.assertRaises(TaskBlockedError):
            self.board.claim(b["id"], assignee="t1")

    def test_complete_unblocks(self):
        a = self.board.create("a")
        b = self.board.create("b", blocked_by=[a["id"]])
        self.assertEqual(self.board.unclaimed(), [a])
        self.board.complete(a["id"])
        self.assertEqual([t["id"] for t in self.board.unclaimed()], [b["id"]])

    def test_claimed_not_in_unclaimed(self):
        a = self.board.create("a")
        self.board.claim(a["id"], assignee="t1")
        self.assertEqual(self.board.unclaimed(), [])
        self.assertEqual(self.board.list()[0]["assignee"], "t1")

    def test_list_empty(self):
        self.assertEqual(self.board.list(), [])


class TestBoardTools(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.ctx = _Ctx(self.dir.name)

    def tearDown(self):
        self.dir.cleanup()

    def test_full_lifecycle_via_tools(self):
        async def go():
            created = await CreateTaskTool().execute(
                {"subject": "task A"}, self.ctx)
            tid = re.search(r"task (\w+):", created.output).group(1)
            await ClaimTaskTool().execute({"id": tid}, self.ctx)
            out = await GetTaskTool().execute({"id": tid}, self.ctx)
            self.assertIn("in_progress", out.output)
            await CompleteTaskTool().execute({"id": tid}, self.ctx)
            listing = await ListTasksTool().execute({}, self.ctx)
            self.assertIn("completed", listing.output)

        asyncio.run(go())

    def test_claim_blocked_reports_error(self):
        async def go():
            a = (await CreateTaskTool().execute({"subject": "a"}, self.ctx)).output
            aid = re.search(r"task (\w+):", a).group(1)
            b = (await CreateTaskTool().execute(
                {"subject": "b", "blocked_by": [aid]}, self.ctx)).output
            bid = re.search(r"task (\w+):", b).group(1)
            out = await ClaimTaskTool().execute({"id": bid}, self.ctx)
            self.assertTrue(out.is_error or "blocked" in out.output.lower())

        asyncio.run(go())


if __name__ == "__main__":
    unittest.main()
