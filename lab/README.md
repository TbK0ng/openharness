# lab/ — 实验工作区

用于安全试用 OpenHarness Agent 的沙盒。这里的 `.oh/` 归 lab 自己所有，
实验产生的记忆、任务、cron、worktree 都不会污染项目根。

## 用法

从**仓库根**运行（agent 的工作目录指向 lab）：

```bash
uv run python -m openharness.cli --cwd lab --mode full-auto "总结 lab/notes.md"
```

首次运行会自动创建 `lab/.oh/`。想先准备好配置：

```bash
uv run python -m openharness.cli --cwd lab --no-banner
# 进入交互后执行 /init
```

或手动复制模板：

```bash
mkdir -p lab/.oh && cp examples/settings.example.json lab/.oh/settings.json
```

## 目录

```
lab/
├── .oh/              # 本工作区独立的配置与运行时状态（gitignored）
│   └── skills/       # 测试用的技能（当前是 .agents/skills 的副本）
├── notes.md          # 供 Agent 读写的示例文件
├── src/              # 示例代码，供 Agent 分析/修改
└── README.md
```

`lab/` 本身入库，`lab/.oh/` 不入库。

技能只在 lab 里当测试素材用：项目根 `.oh/` 不放技能，免得开发用技能（`.agents/skills`）
被当成产品技能加载。需要时从 `.agents/skills` 复制到 `lab/.oh/skills`：
`uv run python -m openharness.cli --cwd lab "/skills"` 能看到它们。
