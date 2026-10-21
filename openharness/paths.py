"""配置目录约定 — 所有运行时状态集中在项目根目录的 `.oh/`。

此前各子系统各写各的路径（`settings.json`、`data/cron.json`、`memory/`、
`MEMORY.md`、`.tasks/`、`.openharness_worktrees/`），散落在项目根目录。
现在统一到：

    .oh/
    ├── settings.json      # 配置
    ├── data/cron.json     # 定时任务
    ├── memory/            # 记忆条目
    ├── MEMORY.md          # 记忆索引
    ├── .tasks/            # 任务看板
    ├── worktrees/         # 隔离工作区
    └── hooks.log          # hook 日志

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


def package_root() -> Path:
    """仓库根（openharness 包的父目录）；安装成 site-packages 时退回包目录。"""
    return Path(__file__).resolve().parent.parent


def example_path(name: str, workspace: Path | str | None = None) -> Path | None:
    """查找随仓库分发的示例文件，优先给定的工作区，其次仓库根。"""
    bases = ([Path(workspace)] if workspace is not None else []) + [package_root()]
    for base in bases:
        candidate = base / "examples" / name
        if candidate.exists():
            return candidate
    fallback = Path.cwd() / "examples" / name
    return fallback if fallback.exists() else None
