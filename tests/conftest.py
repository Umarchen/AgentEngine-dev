"""
pytest 配置文件
"""

import pytest
import asyncio
import sys

# 添加项目路径
sys.path.insert(0, '/home/ubuntu/vrt-projects/projects/AgentEngine-dev/.staging/src')


def pytest_configure(config):
    """pytest 配置"""
    config.addinivalue_line(
        "markers", "asyncio: mark test as async"
    )


def pytest_collection_modifyitems(config, items):
    """修改测试项"""
    # 为所有异步测试添加 asyncio 标记
    for item in items:
        if asyncio.iscoroutinefunction(item.function):
            item.add_marker(pytest.mark.asyncio)


# 配置 asyncio 模式
pytest_plugins = ('pytest_asyncio',)


def pytest_addoption(parser):
    """添加命令行选项"""
    parser.addoption(
        "--run-slow",
        action="store_true",
        default=False,
        help="运行慢速测试"
    )


def pytest_ignore_collect(collection_path, config):
    """忽略特定文件"""
    # 可以在这里配置忽略某些测试文件
    return False
