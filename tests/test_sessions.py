"""Test 会话管理：/new /fork /side /switch /rewind 与多轮上下文复用。"""
import shutil
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import openharness.engine.llm as llm_mod
import openharness.engine.query_engine as qe
from openharness.cli import interactive, run_once
from openharness.engine.query_engine import Engine
from openharness.repl import RewindRequest

TMP_ROOT = Path(__file__).resolve().parents[1] / "_tmp_tests"


def _fresh_dir(name: str) -> Path:
    d = TMP_ROOT / name
    if d.exists():
        shutil.rmtree(d)
    d.mkdir(parents=True)
    return d


class _EngineCase(unittest.TestCase):
    def setUp(self):
        # 会话命令不需要真实 LLM；避免依赖网络/API key。
        patcher = mock.patch.object(qe, "build_llm", return_value=object())
        patcher.start()
        self.addCleanup(patcher.stop)
        self.dir = _fresh_dir(f"sessions_{self._testMethodName}")
        self.engine = Engine(cwd=str(self.dir))


class TestSessionLifecycle(_EngineCase):
    def test_create_context_reuses_the_same_session(self):
        first = self.engine.create_context()
        first.messages.append({"role": "user", "content": "one"})
        second = self.engine.create_context()
        self.assertIs(first, second)
        self.assertEqual(second.messages, [{"role": "user", "content": "one"}])

    def test_new_keeps_old_session_and_switches(self):
        old = self.engine.current_session()
        old.context.messages.append({"role": "user", "content": "old"})
        self.engine.commands.get("new").fn("fresh")
        new = self.engine.current_session()
        self.assertIsNot(new, old)
        self.assertEqual(new.kind, "main")
        self.assertEqual(new.name, "fresh")
        self.assertEqual(new.messages, [])
        self.assertIn(old.id, self.engine.sessions)
        self.assertIn(old.id, self.engine.commands.get("sessions").fn(""))

    def test_fork_copies_history_but_not_mutations(self):
        parent = self.engine.current_session()
        parent.context.messages.append({"role": "user", "content": "shared"})
        self.engine.commands.get("fork").fn("branch")
        fork = self.engine.current_session()
        self.assertEqual(fork.kind, "fork")
        self.assertEqual(fork.parent_id, parent.id)
        self.assertEqual(fork.messages, parent.messages)

        fork.context.messages.append({"role": "user", "content": "only fork"})
        self.assertEqual(len(parent.messages), 1)
        self.assertEqual(len(fork.messages), 2)

    def test_side_is_snapshot_then_discarded(self):
        main = self.engine.current_session()
        main.context.messages.append({"role": "user", "content": "context"})
        out = self.engine.commands.get("side").fn("")
        side = self.engine.current_session()
        self.assertEqual(side.kind, "side")
        self.assertEqual(side.parent_id, main.id)
        self.assertEqual(side.messages, main.messages)
        self.assertIn("临时会话", out)

        side.context.messages.append({"role": "user", "content": "scratch"})
        self.assertEqual(len(main.messages), 1)
        self.engine.commands.get("side").fn("off")
        self.assertIs(self.engine.current_session(), main)
        self.assertNotIn(side.id, self.engine.sessions)
        self.assertEqual(main.messages[0]["content"], "context")

    def test_switch_by_prefix_and_name(self):
        main = self.engine.current_session()
        main.name = "main-session"
        self.engine.commands.get("new").fn("other")
        other = self.engine.current_session()

        switched = self.engine.commands.get("switch").fn(main.id[:6])
        self.assertIn(main.id, switched)
        self.assertIs(self.engine.current_session(), main)

        self.engine.commands.get("switch").fn("other")
        self.assertIs(self.engine.current_session(), other)
        self.assertIn("未知会话", self.engine.commands.get("switch").fn("nope"))

    def test_switching_away_from_side_discards_it(self):
        main = self.engine.current_session()
        self.engine.commands.get("side").fn("")
        side = self.engine.current_session()
        self.engine.commands.get("switch").fn(main.id)
        self.assertNotIn(side.id, self.engine.sessions)


class TestRewind(_EngineCase):
    def test_rewind_drops_user_turn_and_tool_exchange(self):
        ctx = self.engine.create_context()
        ctx.messages[:] = [
            {"role": "user", "content": "first"},
            {"role": "assistant", "content": "ok"},
            {"role": "user", "content": "second"},
            {"role": "assistant", "content": "", "tool_calls": [{"id": "c1"}]},
            {"role": "tool", "tool_call_id": "c1", "name": "Read", "content": "data"},
            {"role": "assistant", "content": "done"},
        ]
        prompt, note = self.engine.rewind_last_turn()
        self.assertEqual(prompt, "second")
        self.assertIn("回退", note)
        self.assertEqual([m.get("content") for m in ctx.messages], ["first", "ok"])

    def test_rewind_empty_session_reports_noop(self):
        self.engine.create_context()
        prompt, note = self.engine.rewind_last_turn()
        self.assertIsNone(prompt)
        self.assertIn("没有可回退", note)

    def test_rewind_command_exposes_restored_prompt(self):
        ctx = self.engine.create_context()
        ctx.messages.append({"role": "user", "content": "undo me"})
        out = self.engine.commands.get("rewind").fn("")
        self.assertIn("undo me", out)
        self.assertEqual(ctx.messages, [])

    def test_begin_turn_rebuilds_a_closed_llm(self):
        first, second = object(), object()
        with mock.patch.object(qe, "build_llm", side_effect=[first, second]):
            ctx = self.engine.begin_turn()
            self.assertIs(ctx.llm, first)
            ctx.llm_closed = True
            self.assertIs(self.engine.begin_turn().llm, second)


class TestSessionPersistence(_EngineCase):
    def test_saved_session_reloads_in_a_new_engine(self):
        ctx = self.engine.create_context()
        ctx.messages.append({"role": "user", "content": "saved turn"})
        session_id = self.engine.current_session().id
        self.engine.save_current_session()

        fresh = Engine(cwd=str(self.dir))
        loaded = fresh.switch_session(session_id)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.id, session_id)
        self.assertEqual(fresh.current_session().messages,
                         [{"role": "user", "content": "saved turn"}])

    def test_run_once_saves_history_after_each_turn(self):
        async def fake_stream(context, max_tokens=None):
            return llm_mod.LLMResponse(text="stored reply", stop_reason="end_turn")

        with mock.patch.object(llm_mod, "stream_response", fake_stream):
            run_once(self.engine, "persist me", None)

        path = self.engine.oh_dir / "sessions" / f"{self.engine.session.id}.json"
        self.assertTrue(path.exists())
        payload = __import__("json").loads(path.read_text(encoding="utf-8"))
        self.assertEqual(payload["messages"][-1]["content"], "stored reply")

    def test_side_session_is_not_persisted(self):
        self.engine.create_context()
        self.engine.commands.get("side").fn("")
        side_id = self.engine.current_session().id
        self.engine.save_current_session()
        self.assertFalse((self.engine.oh_dir / "sessions" / f"{side_id}.json").exists())

    def test_saved_session_switch_by_name(self):
        ctx = self.engine.create_context()
        ctx.messages.append({"role": "user", "content": "named"})
        self.engine.current_session().name = "named-session"
        self.engine.save_current_session()

        fresh = Engine(cwd=str(self.dir))
        loaded = fresh.switch_session("named-session")
        self.assertIsNotNone(loaded)
        self.assertEqual(fresh.current_session().messages[0]["content"], "named")

    def test_sessions_command_lists_saved_sessions_after_restart(self):
        ctx = self.engine.create_context()
        ctx.messages.append({"role": "user", "content": "x"})
        self.engine.save_current_session()

        fresh = Engine(cwd=str(self.dir))
        out = fresh.commands.get("sessions").fn("")
        self.assertIn(self.engine.session.id, out)
        self.assertIn("已保存", out)


class TestMultiTurn(_EngineCase):
    def test_run_once_sends_previous_turn_back_to_the_model(self):
        seen = []

        async def fake_stream(context, max_tokens=None):
            seen.append([dict(m) for m in context.messages])
            return llm_mod.LLMResponse(text=f"reply{len(seen)}",
                                       stop_reason="end_turn")

        with mock.patch.object(llm_mod, "stream_response", fake_stream):
            self.assertEqual(run_once(self.engine, "first", None), "reply1")
            self.assertEqual(run_once(self.engine, "second", None), "reply2")

        self.assertEqual([m["role"] for m in seen[1]],
                         ["user", "assistant", "user"])
        self.assertEqual([m["content"] for m in seen[1]],
                         ["first", "reply1", "second"])


class TestDoubleEscLoop(_EngineCase):
    def test_rewind_requests_prefill_the_next_prompt(self):
        ctx = self.engine.create_context()
        ctx.messages.append({"role": "user", "content": "restore me"})

        seen = []

        class FakeReader:
            def __init__(self, eng):
                pass

            def read(self, default=""):
                seen.append(default)
                if len(seen) == 1:
                    raise RewindRequest()
                return "exit"

        with mock.patch("openharness.cli.LineReader", FakeReader):
            rc = interactive(self.engine, None)

        self.assertEqual(rc, 0)
        self.assertEqual(seen, ["", "restore me"])
        self.assertEqual(ctx.messages, [])


if __name__ == "__main__":
    unittest.main()
