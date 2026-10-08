import io

p = r"C:\Users\wocai\Desktop\agentPro\openharness\agents\team.py"
with io.open(p, "r", encoding="utf-8") as f:
    src = f.read()

old = """        task = SubTask(
            agent_id=agent.agent_id, subagent_type=agent.subagent_type,
            prompt=prompt or "",
        )
        ctx = build_sub_context(parent, task)
        if agent.on_event is not None:
            ctx.on_event = agent.on_event
"""

new = """        task = SubTask(
            agent_id=agent.agent_id, subagent_type=agent.subagent_type,
            prompt=prompt or "",
        )
        if agent.context is not None:
            ctx = agent.context  # 续跑：复用已有会话
        else:
            ctx = build_sub_context(parent, task)
        ctx.messages.append({"role": "user", "content": prompt or ""})
        if agent.on_event is not None:
            ctx.on_event = agent.on_event
"""

if old in src:
    src = src.replace(old, new, 1)
    print("replaced on_event block")
else:
    # try the variant without on_event line
    old2 = """        ctx = build_sub_context(parent, task)
        if agent.on_event is not None:
            ctx.on_event = agent.on_event
"""
    new2 = """        if agent.context is not None:
            ctx = agent.context  # 续跑：复用已有会话
        else:
            ctx = build_sub_context(parent, task)
        ctx.messages.append({"role": "user", "content": prompt or ""})
        if agent.on_event is not None:
            ctx.on_event = agent.on_event
"""
    if old2 in src:
        src = src.replace(old2, new2, 1)
        print("replaced on_event block (variant)")
    else:
        old3 = """        ctx = build_sub_context(parent, task)
"""
        new3 = """        if agent.context is not None:
            ctx = agent.context  # 续跑：复用已有会话
        else:
            ctx = build_sub_context(parent, task)
        ctx.messages.append({"role": "user", "content": prompt or ""})
"""
        if old3 in src:
            src = src.replace(old3, new3, 1)
            print("replaced base block")
        else:
            raise SystemExit("no matching block found")

with io.open(p, "w", encoding="utf-8", newline="") as f:
    f.write(src)
print("done")
