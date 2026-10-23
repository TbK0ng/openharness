"""自主 Agent（s17）：inbox 优先、任务板认领、idle 轮询。"""
import tempfile
import unittest

from openharness.swarm.autonomous import (
    Inbox, Teammate, claim_task, idle_poll,
    run_until_done, scan_unclaimed_tasks,
)
from openharness.tasks.board import TaskBoard, TaskBlockedError


def _board():
    return TaskBoard(tempfile.mkdtemp())


class TestInbox(unittest.TestCase):
    def test_send_consume_pending(self):
        box = Inbox()
        self.assertEqual(box.pending("a"), 0)
        box.send("a", "m1")
        box.send("a", "m2")
        box.send("b", "x")
        self.assertEqual(box.pending("a"), 2)
        self.assertEqual(box.consume("a"), ["m1", "m2"])
        self.assertEqual(box.pending("a"), 0)
        self.assertEqual(box.consume("a"), [])  # 二次消费为空
        self.assertEqual(box.consume("b"), ["x"])


class TestScanAndClaim(unittest.TestCase):
    def test_scan_returns_only_unblocked_unclaimed(self):
        b = _board()
        t1 = b.create("t1")
        t2 = b.create("t2", blocked_by=[t1["id"]])
        self.assertEqual([t["id"] for t in scan_unclaimed_tasks(b)], [t1["id"]])
        b.claim(t1["id"], assignee="alice")
        self.assertEqual(scan_unclaimed_tasks(b), [])  # 被认领后不可见
        b.complete(t1["id"])
        self.assertEqual([t["id"] for t in scan_unclaimed_tasks(b)], [t2["id"]])

    def test_claim_conflict_raises(self):
        b = _board()
        t = b.create("t")
        claim_task(b, t["id"], "alice")
        with self.assertRaises(TaskBlockedError):
            claim_task(b, t["id"], "bob")


class _FakeWork:
    """记录执行顺序的假 work_fn。"""

    def __init__(self):
        self.order = []

    def __call__(self, task):
        self.order.append(task["id"])


class TestIdlePoll(unittest.TestCase):
    def test_inbox_wins_over_board(self):
        b = _board()
        t = b.create("t")
        inbox = Inbox()
        inbox.send("tm", "hi")
        tm = Teammate(name="tm", board=b, inbox=inbox)
        work = idle_poll(tm)
        self.assertEqual(work["kind"], "inbox")
        self.assertEqual(work["messages"], ["hi"])
        # 任务没被认领
        self.assertIsNone(b._load(t["id"])["assignee"])

    def test_claims_first_unclaimed(self):
        b = _board()
        t = b.create("t")
        tm = Teammate(name="tm", board=b, inbox=Inbox())
        work = idle_poll(tm)
        self.assertEqual(work["kind"], "task")
        self.assertEqual(work["task"]["id"], t["id"])
        self.assertEqual(b._load(t["id"])["assignee"], "tm")

    def test_no_work_returns_none(self):
        tm = Teammate(name="tm", board=_board(), inbox=Inbox())
        self.assertIsNone(idle_poll(tm))


class TestRunUntilDone(unittest.TestCase):
    def test_full_lifecycle_and_shutdown(self):
        b = _board()
        t1 = b.create("t1")
        t2 = b.create("t2")
        tm = Teammate(name="tm", board=b, inbox=Inbox())
        work = _FakeWork()
        done = run_until_done(tm, work)
        self.assertEqual(done, 2)
        self.assertEqual(sorted(work.order), sorted([t1["id"], t2["id"]]))
        self.assertEqual(tm.state, "shutdown")
        self.assertIsNone(tm.current_task)
        self.assertTrue(all(b._load(x)["status"] == "completed"
                            for x in (t1["id"], t2["id"])))

    def test_blocked_task_skipped_then_done_after_unblock(self):
        b = _board()
        t1 = b.create("t1")
        t2 = b.create("t2", blocked_by=[t1["id"]])
        tm = Teammate(name="tm", board=b, inbox=Inbox())
        work = _FakeWork()

        def stepping(task):
            work(task)
            if task["id"] == t1["id"]:
                pass  # t1 完成，t2 解锁

        done = run_until_done(tm, stepping)
        self.assertEqual(done, 2)
        self.assertEqual(work.order[0], t1["id"])  # 先做解锁者
        self.assertEqual(b._load(t2["id"])["status"], "completed")
        self.assertEqual(tm.state, "shutdown")

    def test_two_teammates_never_double_claim(self):
        b = _board()
        t = b.create("only")
        a = Teammate(name="a", board=b, inbox=Inbox())
        c = Teammate(name="c", board=b, inbox=Inbox())
        wa, wc = _FakeWork(), _FakeWork()
        da = run_until_done(a, wa)
        dc = run_until_done(c, wc)
        self.assertEqual(da + dc, 1)  # 只有一个真正干到活
        self.assertEqual(b._load(t["id"])["status"], "completed")


class TestIdentityReinject(unittest.TestCase):
    def test_short_messages_get_identity(self):
        from openharness.swarm.autonomous import reinject_identity
        msgs = [{"role": "user", "content": "summary"}]
        reinject_identity(msgs, "alice", "backend")
        self.assertEqual(msgs[0]["content"],
                         "<identity>You are 'alice', role: backend. Continue your work.</identity>")

    def test_long_messages_untouched(self):
        from openharness.swarm.autonomous import reinject_identity
        msgs = [{"role": "user", "content": f"m{i}"} for i in range(5)]
        reinject_identity(msgs, "alice", "backend")
        self.assertEqual(len(msgs), 5)  # 未注入


class TestShutdownRequest(unittest.TestCase):
    def test_shutdown_in_idle(self):
        b = _board()
        inbox = Inbox()
        inbox.send("tm", {"type": "shutdown_request"})
        tm = Teammate(name="tm", board=b, inbox=inbox)
        work = idle_poll(tm)
        self.assertEqual(work["kind"], "shutdown")
        self.assertEqual(tm.state, "shutdown")

    def test_run_until_done_stops_on_shutdown(self):
        b = _board()
        t = b.create("t")
        inbox = Inbox()
        inbox.send("tm", {"type": "shutdown_request"})
        tm = Teammate(name="tm", board=b, inbox=inbox)
        work = _FakeWork()
        done = run_until_done(tm, work)
        self.assertEqual(done, 0)  # 没干任何活
        self.assertEqual(tm.state, "shutdown")
        self.assertIsNone(b._load(t["id"])["assignee"])  # 任务没被认领


class TestConsumeLeadInbox(unittest.TestCase):
    def test_injects_into_history(self):
        from openharness.swarm.autonomous import consume_lead_inbox
        inbox = Inbox()
        inbox.send("lead", "alice done: schema.sql")
        inbox.send("lead", {"type": "result", "content": "bob done: api.py"})
        history = []
        msgs = consume_lead_inbox(inbox, "lead", history)
        self.assertEqual(len(msgs), 2)
        self.assertEqual(len(history), 2)
        self.assertEqual(history[0]["content"], "alice done: schema.sql")
        self.assertEqual(history[1]["content"], "bob done: api.py")

if __name__ == "__main__":
    unittest.main()
