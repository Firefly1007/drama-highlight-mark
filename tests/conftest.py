"""Pytest 全局配置与钩子。"""

from __future__ import annotations

import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    """注册 --integration 命令行选项。"""
    parser.addoption(
        "--integration",
        action="store_true",
        default=False,
        help="运行需要真实网络或外部 API 的集成测试",
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """当未指定 --integration 且未显式指定 -m integration 时，自动跳过标注为 integration 的测试。"""
    if config.getoption("--integration", default=False):
        return

    markexpr = config.option.markexpr or ""
    if "integration" in markexpr:
        return

    skip_integration = pytest.mark.skip(
        reason="集成测试需要真实外部环境，默认跳过（使用 --integration 或 -m integration 触发）"
    )
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip_integration)
