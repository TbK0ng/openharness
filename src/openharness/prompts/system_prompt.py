"""System prompt 组装 — 每轮 `begin_turn()` 重新生成。

拼装顺序：身份/环境 → 长期记忆索引 → 技能清单 → 行为准则。
记忆与技能只注入索引，正文按需加载（MemorySearch / Skill 工具）。
"""
from __future__ import annotations


def build_system_prompt(*, cwd, mode: str, memory, skills) -> str:
    """组装本轮 system prompt。memory / skills 允许为 None。"""
    parts = [
        "You are OpenHarness, an autonomous coding assistant "
        "(a 1:1 implementation of the OpenHarness tutorial architecture).",
        f"Working directory: {cwd}",
        f"Permission mode: {mode}",
    ]
    mem = memory.snapshot() if memory is not None else ""
    if mem:
        parts.append(mem)
    sk = skills.summary() if skills is not None else ""
    if sk:
        parts.append(sk)
    parts.append(
        "Guidelines:\n"
        "- Inspect files with Read/Glob/Grep before editing.\n"
        "- Use Write/Edit to change code; prefer minimal diffs.\n"
        "- Use Bash to run commands and tests.\n"
        "- Persist durable facts with the MemorySave tool "
        "(user preferences, project conventions, references); "
        "use MemorySearch to recall them.\n"
        "- Use CronCreate / CronList / CronDelete for recurring jobs; "
        "the scheduler runs while the CLI process is alive.\n"
        "- Load a skill with the Skill tool when a matching one exists.\n"
        "- For large or parallel work, delegate to sub-agents via the Agent tool "
        "(explore/plan/implement/review).\n"
        "- Be concise. End each turn with a short summary of what changed."
    )
    return "\n\n".join(parts)
