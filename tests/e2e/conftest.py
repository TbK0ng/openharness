"""e2e 用例的开关：默认只跑确定性部分，live 用例需显式开启。

    uv run pytest tests/e2e                # 确定性用例
    OH_E2E_LIVE=1 uv run pytest tests/e2e  # 加上真实 DeepSeek 用例
"""
from __future__ import annotations

import os

import pytest


def pytest_configure(config):
    config.addinivalue_line("markers",
                            "live: 需要真实 DeepSeek 凭据的端到端用例")


def pytest_collection_modifyitems(config, items):
    if os.environ.get("OH_E2E_LIVE") == "1":
        return
    skip = pytest.mark.skip(reason="live 用例：设置 OH_E2E_LIVE=1 后运行")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip)
