"""自动扫描 *_agent.py 并注册其中的 Agent 类。"""

import ast
import sys
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from typing import List

from loguru import logger

__all__: List[str] = []


def _get_decorated_classes(file_path: Path) -> List[str]:
    """解析文件中使用 @AgentRegistry.register 的类名。"""

    try:
        tree = ast.parse(file_path.read_text(encoding="utf-8"))
    except Exception as exc:  # pragma: no cover - 解析失败记录日志
        logger.error(f"解析 Agent 文件失败: {file_path} - {exc}")
        return []

    class_names: List[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        for decorator in node.decorator_list:
            if not isinstance(decorator, ast.Call):
                continue
            func = decorator.func
            if isinstance(func, ast.Attribute) and func.attr == "register":
                value = func.value
                if isinstance(value, ast.Name) and value.id == "AgentRegistry":
                    class_names.append(node.name)
                    break
    return class_names


def _load_module(module_name: str, file_path: Path) -> None:
    """按路径加载模块，执行后触发装饰器注册。"""

    spec = spec_from_file_location(module_name, file_path)
    if spec is None or spec.loader is None:
        logger.error(f"无法创建模块加载说明: {module_name} ({file_path})")
        return

    module = module_from_spec(spec)
    sys.modules[module_name] = module

    try:
        spec.loader.exec_module(module)
    except Exception as exc:  # pragma: no cover - 单个 Agent 导入失败不会阻断
        logger.error(f"注册 Agent 模块失败: {module_name} - {exc}")


def _auto_register_agents() -> None:
    """遍历 agents 目录下所有 *_agent.py 并导入包含注册装饰器的模块。"""

    package_dir = Path(__file__).resolve().parent
    package_name = __name__

    for agent_file in sorted(package_dir.rglob("*_agent.py")):
        relative_path = agent_file.relative_to(package_dir)
        if "__pycache__" in relative_path.parts:
            continue

        decorated_classes = _get_decorated_classes(agent_file)
        if not decorated_classes:
            continue

        module_stub = ".".join(relative_path.with_suffix("").parts)
        module_name = f"{package_name}.{module_stub}" if module_stub else f"{package_name}.{agent_file.stem}"
        _load_module(module_name, agent_file)
        __all__.extend(decorated_classes)

_auto_register_agents()
