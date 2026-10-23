"""配置加载 — 默认配置、settings.json 合并、权限持久化。

配置目录约定见 `config/paths.py`；本模块不持有全局状态，Engine 每次启动
调用 `load_config()` 得到一份独立的 dict。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional


def default_config(cwd: Path) -> dict:
    """一份完整的默认配置（与 .oh/settings.json 同构）。"""
    return {
        "cwd": str(cwd),
        # provider: deepseek（云端，默认）| lmstudio（本地 127.0.0.1:1234）
        # base_url / api_key / model 留空时按 provider 预设解析（见 api/registry.py）
        "provider": "deepseek",
        "base_url": "",
        "api_key": "",
        "model": "",
        "max_turns": 30,
        "permissions": {"mode": "default", "deny_tools": [], "deny_paths": [], "deny_commands": []},
        "hooks": {},
        "mcp_servers": {},
        # 相对路径一律以配置目录 .oh/ 为根
        "skills_dirs": ["skills"],
        "memory_dir": "memory",
        "plugins_dir": "plugins",
    }


def deep_update(base: dict, extra: dict) -> None:
    """就地把 extra 合并进 base；嵌套 dict 递归，其余值直接覆盖。"""
    for key, value in extra.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            deep_update(base[key], value)
        else:
            base[key] = value


def config_candidates(cwd: Path, oh_dir: Path,
                      config_path: Optional[str] = None) -> list[Path]:
    """配置读取顺序：显式路径 > .oh/settings.json > 旧位置 ./settings.json。"""
    if config_path:
        return [Path(config_path)]
    return [oh_dir / "settings.json", cwd / "settings.json"]


def load_config(cwd: Path, oh_dir: Path,
                config_path: Optional[str] = None) -> dict:
    """默认配置 + 第一个存在的 settings.json。"""
    cfg = default_config(cwd)
    for path in config_candidates(cwd, oh_dir, config_path):
        if path.exists():
            user = json.loads(path.read_text(encoding="utf-8"))
            deep_update(cfg, user)
            break
    return cfg


def save_permissions(settings_path: Path, permissions: dict) -> Path:
    """把 permissions 段合并进 settings.json，保留其它配置。"""
    data: dict = {}
    if settings_path.exists():
        try:
            data = json.loads(settings_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {}
    if not isinstance(data, dict):
        data = {}
    current = data.get("permissions")
    if not isinstance(current, dict):
        current = {}
    current.update(permissions)
    data["permissions"] = current
    settings_path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n",
                             encoding="utf-8")
    return settings_path
