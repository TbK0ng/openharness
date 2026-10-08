import io

p = r"C:\Users\wocai\Desktop\agentPro\openharness\agents\team.py"
with io.open(p, "r", encoding="utf-8") as f:
    src = f.read()

anchor = '        ctx.messages.append({"role": "user", "content": prompt or ""})\n'
addition = anchor + '        if agent.on_event is not None:\n            ctx.on_event = agent.on_event\n'

if "on_event is not None" in src:
    print("on_event already present")
elif anchor in src:
    src = src.replace(anchor, addition, 1)
    with io.open(p, "w", encoding="utf-8", newline="") as f:
        f.write(src)
    print("on_event added")
else:
    raise SystemExit("anchor not found")
