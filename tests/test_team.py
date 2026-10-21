"""Test agents/team.py sub-agent subsystem (ch.11 multi-agent).

Regression coverage: READONLY_TOOLS listed `LS` and `NotebookRead`, neither of
which is a registered tool, so the whitelist silently granted nothing extra and
nothing caught the drift. The subsystem previously had no tests at all.
"""
import unittest

from openharness.agents.team import (
    READONLY_TOOLS,
    SUBAGENT_SYSTEM,
    SUBAGENT_TYPES,
    SubTask,
    TeamRegistry,
    build_sub_context,
)
from openharness.engine.query_engine import Engine


def _context():
    # build_sub_context reads registry/cwd, so a real Context is the cheapest
    # faithful fixture; no LLM call happens during construction.
    return Engine(cwd=".").create_context()


class TestReadonlyWhitelist(unittest.TestCase):
    def test_every_whitelisted_tool_is_registered(self):
        registered = {t.name for t in _context().registry.list_tools()}
        missing = READONLY_TOOLS - registered

        self.assertEqual(missing, set(), f"whitelist names not in registry: {sorted(missing)}")

    def test_whitelist_contains_no_write_tools(self):
        reg = {t.name: t for t in _context().registry.list_tools()}
        write_tools = {name for name in READONLY_TOOLS
                       if name in reg and not reg[name].read_only}

        self.assertEqual(write_tools, set())


class TestBuildSubContext(unittest.TestCase):
    def test_explore_gets_readonly_tools_only(self):
        parent = _context()
        ctx = build_sub_context(parent, SubTask(agent_type="explore", description="d"))

        granted = {s["function"]["name"] for s in ctx.tool_schemas}
        self.assertTrue(granted, "explore sub-agent must receive some tools")
        self.assertLessEqual(granted, READONLY_TOOLS)
        self.assertNotIn("Bash", granted)
        self.assertNotIn("Write", granted)

    def test_plan_matches_explore_toolset(self):
        parent = _context()
        explore = build_sub_context(parent, SubTask(agent_type="explore", description="d"))
        plan = build_sub_context(parent, SubTask(agent_type="plan", description="d"))

        self.assertEqual({s["function"]["name"] for s in explore.tool_schemas},
                         {s["function"]["name"] for s in plan.tool_schemas})

    def test_general_purpose_gets_full_toolset(self):
        parent = _context()
        ctx = build_sub_context(parent, SubTask(agent_type="general-purpose", description="d"))

        self.assertEqual(len(ctx.tool_schemas), len(parent.registry.list_tools()))

    def test_sub_context_cannot_spawn_further_subagents(self):
        parent = _context()
        ctx = build_sub_context(parent, SubTask(agent_type="general-purpose", description="d"))

        self.assertIsNone(ctx.team)

    def test_sub_context_has_independent_history(self):
        parent = _context()
        parent.messages.append({"role": "user", "content": "parent"})
        ctx = build_sub_context(parent, SubTask(agent_type="explore", description="d"))

        self.assertEqual(ctx.messages, [])


class TestTeamRegistry(unittest.TestCase):
    def test_create_registers_without_running(self):
        team = TeamRegistry()
        agent = team.create(label="probe", subagent_type="explore")

        self.assertEqual(agent.status, "created")
        self.assertIs(team.get(agent.agent_id), agent)
        self.assertEqual(team.list(), [agent])

    def test_unknown_agent_id_returns_none(self):
        self.assertIsNone(TeamRegistry().get("agent-999"))

    def test_tools_for_matches_build_sub_context(self):
        engine = Engine(cwd=".")
        team = TeamRegistry(engine=engine)
        parent = engine.create_context()

        for agent_type in SUBAGENT_TYPES:
            ctx = build_sub_context(parent, SubTask(agent_type=agent_type, description="d"))
            self.assertEqual(
                {t.name for t in team.tools_for(agent_type)},
                {s["function"]["name"] for s in ctx.tool_schemas},
                f"tools_for disagrees with build_sub_context for {agent_type}",
            )

    def test_every_subagent_type_has_a_system_prompt(self):
        self.assertEqual(set(SUBAGENT_SYSTEM), set(SUBAGENT_TYPES))


if __name__ == "__main__":
    unittest.main()
