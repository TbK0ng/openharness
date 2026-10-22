"""配置目录约定 — 所有运行时状态集中在项目根目录的 `.oh/`。

此前各子系统各写各的路径（`settings.json`、`data/cron.json`、`memory/`、
`MEMORY.md`、`.tasks/`、`.openharness_worktrees/`），散落在项目根目录。
现在统一到：

    .oh/
    ├── settings.json      # 配置
    ├── mcp.json           # MCP 服务器
    ├── data/cron.json     # 定时任务
    ├── data/cron.log      # 定时任务触发日志
    ├── sessions/          # 已保存会话（每轮自动落盘）
    ├── memory/            # 记忆条目
    ├── MEMORY.md          # 记忆索引
    ├── .tasks/            # 任务看板（依赖 DAG）
    ├── tasks/             # 后台任务历史
    ├── worktrees/         # 隔离工作区
    ├── plugins/           # 插件
    └── skills/            # 技能

`OH_DIR` 环境变量可覆盖目录名（默认 ".oh"），便于测试隔离。
"""
from __future__ import annotations

import os
from pathlib import Path

DEFAULT_OH_DIRNAME = ".oh"


def oh_dir(root: Path | str | None = None) -> Path:
    """返回配置目录（不创建）。根目录默认取当前工作目录。"""
    base = Path(root) if root is not None else Path.cwd()
    name = os.environ.get("OH_DIR") or DEFAULT_OH_DIRNAME
    return base / name


def ensure_oh_dir(root: Path | str | None = None) -> Path:
    """返回配置目录并确保存在。"""
    d = oh_dir(root)
    d.mkdir(parents=True, exist_ok=True)
    return d


def oh_path(name: str, root: Path | str | None = None) -> Path:
    """配置目录下的子路径。"""
    return oh_dir(root) / name


def example_path(name: str, workspace: Path | str | None = None) -> Path | None:
    """查找 `<workspace>/examples/<name>`（未指定工作区时用当前目录）。

    仓库不再分发示例文件；找不到时由调用方回退到内置默认配置。
    """
    base = Path(workspace) if workspace is not None else Path.cwd()
    candidate = base / "examples" / name
    return candidate if candidate.exists() else None
