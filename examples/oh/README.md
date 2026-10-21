# .oh/ 布局说明

运行时执行 `uv run python -m openharness.cli --cwd <工作区>` 会在该工作区
创建 `.oh/`。典型内容：

```
.oh/
├── settings.json      # 配置（/init 生成）
├── mcp.json           # MCP 服务器（可选）
├── memory/            # 记忆条目
├── MEMORY.md          # 记忆索引
├── .tasks/            # 任务看板（依赖 DAG）
├── tasks/             # 后台任务历史
├── data/cron.json     # 定时任务
├── worktrees/         # 隔离工作区
├── plugins/           # 插件
└── skills/            # 技能
```

这些都由代码按需创建，无需手工准备。本目录仅作文档参考。
