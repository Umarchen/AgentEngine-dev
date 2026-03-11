"""Skill 管理器。

负责系统中所有 skill 的扫描、注册、执行与内存索引管理。

说明：
- 对外统一通过 ``list_available_skills`` 返回 openjiuwen ``Model.tools`` 协议结构；
- skill 调用统一走 openjiuwen ``tool_calls`` 语义。
"""

from __future__ import annotations

import asyncio
import importlib.util
import inspect
import json
import os
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from dotenv import load_dotenv
from loguru import logger


SkillHandler = Callable[[Dict[str, Any]], Any]


@dataclass
class SkillRecord:
    name: str
    path: str
    source: str
    registered_at: str
    description: str = "已注册 skill"
    input_schema: Dict[str, Any] = field(default_factory=lambda: {"type": "object"})
    entry_module: str = ""
    entry_function: str = ""
    handler: Optional[SkillHandler] = None


class SkillMgr:
    _instance: Optional["SkillMgr"] = None

    def __init__(self, skills_root: Optional[Path] = None):
        self._explicit_skills_root = skills_root
        self.skills_root = skills_root or Path(__file__).resolve().parent
        self.registry_file = self.skills_root / "registry.json"
        self.env_file = Path(__file__).resolve().parents[2] / ".env"
        self._lock = asyncio.Lock()

        self._skill_records: Dict[str, SkillRecord] = {}
        self._skill_meta_cache: Dict[str, Dict[str, Any]] = {}
        self._initialized = False

    @classmethod
    def get_instance(cls) -> "SkillMgr":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    async def initialize(self) -> None:
        if self._initialized:
            return

        await self.refresh_skills_incremental()
        logger.info(
            "SkillMgr 初始化完成: records={}, executable={} (metadata lazy load enabled)",
            len(self._skill_records),
            len([record for record in self._skill_records.values() if record.handler is not None]),
        )

    async def refresh_skills_incremental(self) -> Dict[str, int]:
        self._refresh_skills_root_from_env()

        stats = {
            "added_from_registry": 0,
            "added_from_local_scan": 0,
            "total_records": 0,
            "total_executable": 0,
        }

        async with self._lock:
            self._refresh_skills_root_from_env()

            if not self._initialized:
                runtime_records = {
                    name: record
                    for name, record in self._skill_records.items()
                    if record.handler is not None
                }
                self._skill_records = dict(runtime_records)
                self._skill_meta_cache.clear()

            registry_payload = self._load_registry_file()
            for item in registry_payload.get("skills", []):
                record = self._build_record(item)
                if not record:
                    continue

                existed = self._skill_records.get(record.name)
                if existed:
                    existed.path = record.path
                    existed.source = record.source
                    existed.registered_at = record.registered_at
                    if record.entry_module:
                        existed.entry_module = record.entry_module
                    if record.entry_function:
                        existed.entry_function = record.entry_function
                else:
                    self._skill_records[record.name] = record
                    stats["added_from_registry"] += 1

            for skill_dir in self._scan_local_skill_dirs():
                skill_name = skill_dir.name
                if skill_name == "__pycache__":
                    continue
                if skill_name in self._skill_records:
                    continue
                self._skill_records[skill_name] = SkillRecord(
                    name=skill_name,
                    path=self._to_rel_path(skill_dir),
                    source="local-scan",
                    registered_at=datetime.now(timezone.utc).isoformat(),
                )
                stats["added_from_local_scan"] += 1

            self._auto_bind_executable_skills()
            self._flush_registry_file()
            self._initialized = True

            stats["total_records"] = len(self._skill_records)
            stats["total_executable"] = len([record for record in self._skill_records.values() if record.handler is not None])

        await self.sync_skill_execution_info()

        logger.debug(
            "SkillMgr 增量刷新完成: added_registry={}, added_scan={}, total={}, executable={}",
            stats["added_from_registry"],
            stats["added_from_local_scan"],
            stats["total_records"],
            stats["total_executable"],
        )
        return stats

    def register_builtin_skill(
        self,
        name: str,
        handler: SkillHandler,
        description: str,
        input_schema: Optional[Dict[str, Any]] = None,
    ) -> None:
        record = self._skill_records.get(name)
        now = datetime.now(timezone.utc).isoformat()
        if record is None:
            self._skill_records[name] = SkillRecord(
                name=name,
                path=f"src/skills/{name}",
                source="builtin",
                registered_at=now,
                description=description,
                input_schema=input_schema or {"type": "object"},
                entry_module="builtin",
                entry_function=handler.__name__,
                handler=handler,
            )
            return

        record.source = "builtin"
        record.description = description
        record.input_schema = input_schema or {"type": "object"}
        record.entry_module = "builtin"
        record.entry_function = handler.__name__
        record.handler = handler
        record.registered_at = now

    def list_available_skills(
        self,
        hydrate_meta: bool = False,
        executable_only: bool = True,
    ) -> List[Dict[str, Any]]:
        """按 openjiuwen ``Model.tools`` 协议输出可用工具列表。

        Returns:
            List[Dict[str, Any]]: 每项包含 ``type/name/description/parameters``。
        """
        records = list(self._skill_records.values())
        records.sort(key=lambda item: item.name)

        tools: List[Dict[str, Any]] = []
        for record in records:
            meta = self._get_or_load_skill_meta(record.name) if hydrate_meta else {}
            executable = record.handler is not None
            if executable_only and not executable:
                continue

            description = meta.get("description") or record.description or "已注册 skill"
            parameters = record.input_schema if isinstance(record.input_schema, dict) else {"type": "object"}
            if not parameters:
                parameters = meta.get("input_schema", {"type": "object"})
            if not isinstance(parameters, dict):
                parameters = {"type": "object", "properties": {}}

            tools.append(
                {
                    "type": "function",
                    "name": record.name,
                    "description": str(description),
                    "parameters": parameters,
                }
            )
        return tools

    async def sync_skill_execution_info(self) -> None:
        from src.database.database import upsert_skill_exe_info

        for record in self._skill_records.values():
            await upsert_skill_exe_info(
                skill_name=record.name,
                executable=record.handler is not None,
                entry_module=record.entry_module,
                entry_function=record.entry_function,
                input_schema=record.input_schema,
            )

    async def execute_skill(self, skill_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        from src.database.database import upsert_skill_exe_info

        record = self._skill_records.get(skill_name)
        handler = record.handler if record else None
        trace_id = str((arguments or {}).get("trace_id") or uuid.uuid4())
        arguments_preview = json.dumps(arguments or {}, ensure_ascii=False)[:1000]

        if not handler:
            if record:
                await upsert_skill_exe_info(
                    skill_name=skill_name,
                    executable=False,
                    entry_module=record.entry_module,
                    entry_function=record.entry_function,
                    input_schema=record.input_schema,
                    trace_id=trace_id,
                    arguments_preview=arguments_preview,
                    executed=False,
                    error_message=f"skill 未实现或不可执行: {skill_name}",
                )
            return {
                "executed": False,
                "trace_id": trace_id,
                "message": f"skill 未实现或不可执行: {skill_name}",
            }

        start = time.perf_counter()
        try:
            result = handler(arguments)
            if inspect.isawaitable(result):
                result = await result

            duration_ms = round((time.perf_counter() - start) * 1000, 3)
            result_size = len(json.dumps(result, ensure_ascii=False)) if result is not None else 0
            await upsert_skill_exe_info(
                skill_name=skill_name,
                executable=True,
                entry_module=record.entry_module,
                entry_function=record.entry_function,
                input_schema=record.input_schema,
                trace_id=trace_id,
                arguments_preview=arguments_preview,
                executed=True,
                duration_ms=duration_ms,
                result_size=result_size,
                error_message=None,
            )

            if isinstance(result, dict):
                result.setdefault("trace_id", trace_id)
                return result
            return {
                "executed": True,
                "trace_id": trace_id,
                "skill": skill_name,
                "result": result,
            }
        except Exception as exc:
            duration_ms = round((time.perf_counter() - start) * 1000, 3)
            await upsert_skill_exe_info(
                skill_name=skill_name,
                executable=True,
                entry_module=record.entry_module,
                entry_function=record.entry_function,
                input_schema=record.input_schema,
                trace_id=trace_id,
                arguments_preview=arguments_preview,
                executed=False,
                duration_ms=duration_ms,
                result_size=0,
                error_message=str(exc),
            )
            return {
                "executed": False,
                "trace_id": trace_id,
                "message": str(exc),
            }

    async def register_skill(self, target_skill_name: str, skill_dir: Path, source: str) -> None:
        async with self._lock:
            self._skill_records[target_skill_name] = SkillRecord(
                name=target_skill_name,
                path=self._to_rel_path(skill_dir),
                source=source,
                registered_at=datetime.now(timezone.utc).isoformat(),
                description=self._skill_records.get(target_skill_name).description
                if target_skill_name in self._skill_records
                else "已注册 skill",
                input_schema=self._skill_records.get(target_skill_name).input_schema
                if target_skill_name in self._skill_records
                else {"type": "object"},
                entry_module=self._skill_records.get(target_skill_name).entry_module
                if target_skill_name in self._skill_records
                else "",
                entry_function=self._skill_records.get(target_skill_name).entry_function
                if target_skill_name in self._skill_records
                else "",
                handler=self._skill_records.get(target_skill_name).handler if target_skill_name in self._skill_records else None,
            )
            self._skill_meta_cache.pop(target_skill_name, None)
            self._flush_registry_file()

    def _load_registry_file(self) -> Dict[str, Any]:
        if not self.registry_file.exists():
            return {"skills": []}
        try:
            payload = json.loads(self.registry_file.read_text(encoding="utf-8"))
            if isinstance(payload, dict) and isinstance(payload.get("skills"), list):
                return payload
        except Exception as exc:
            logger.warning("读取 registry.json 失败: {}", exc)
        return {"skills": []}

    def _flush_registry_file(self) -> None:
        data = {
            "skills": [
                {
                    "name": item.name,
                    "path": item.path,
                    "source": item.source,
                    "registered_at": item.registered_at,
                    "entry_module": item.entry_module,
                    "entry_function": item.entry_function,
                }
                for item in sorted(self._skill_records.values(), key=lambda i: i.name)
            ]
        }
        self.registry_file.parent.mkdir(parents=True, exist_ok=True)
        self.registry_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def _scan_local_skill_dirs(self) -> List[Path]:
        if not self.skills_root.exists():
            return []
        result: List[Path] = []
        for child in self.skills_root.iterdir():
            if not child.is_dir():
                continue
            if child.name.startswith("."):
                continue
            result.append(child)
        return result

    def _get_or_load_skill_meta(self, skill_name: str) -> Dict[str, Any]:
        if skill_name in self._skill_meta_cache:
            return self._skill_meta_cache[skill_name]

        record = self._skill_records.get(skill_name)
        if not record:
            return {}

        target_dir = self._resolve_path(record.path)
        skill_md = target_dir / "SKILL.md"
        meta: Dict[str, Any] = {}
        if skill_md.exists():
            meta = self._parse_skill_md(skill_md)
        self._skill_meta_cache[skill_name] = meta
        return meta

    def _parse_skill_md(self, skill_md: Path) -> Dict[str, Any]:
        try:
            content = skill_md.read_text(encoding="utf-8")
            lines = content.splitlines()
            if len(lines) < 3 or lines[0].strip() != "---":
                return {}

            result: Dict[str, Any] = {}
            for raw in lines[1:]:
                line = raw.strip()
                if line == "---":
                    break
                if ":" not in line:
                    continue
                key, value = line.split(":", 1)
                result[key.strip()] = value.strip()
            return result
        except Exception as exc:
            logger.debug("解析 SKILL.md 元数据失败: {} - {}", skill_md, exc)
            return {}

    @staticmethod
    def _normalize_directory_prefix(directory: Optional[str]) -> str:
        if not directory:
            return ""
        return str(directory).replace("\\", "/").strip("/")

    @staticmethod
    def _in_scope(path: str, prefix: str) -> bool:
        if not prefix:
            return True
        return path == prefix or path.startswith(f"{prefix}/")

    @staticmethod
    def _find_skill_dirs(files: List[Dict[str, Any]]) -> List[str]:
        result = set()
        for item in files:
            path = str(item.get("path", ""))
            if path.endswith("/SKILL.md"):
                result.add(path[: -len("/SKILL.md")])
        return list(result)

    def _auto_bind_executable_skills(self) -> None:
        for record in self._skill_records.values():
            if record.handler is not None:
                continue

            meta = self._get_or_load_skill_meta(record.name)
            record.description = meta.get("description") or record.description
            parsed_schema = self._parse_input_schema(meta.get("input_schema"))
            if parsed_schema is not None:
                record.input_schema = parsed_schema

            entry_module = str(meta.get("entry_module") or "run.py").strip() or "run.py"
            entry_function = str(meta.get("entry_function") or "run").strip() or "run"

            bound_handler = self._load_handler_from_record(record, entry_module, entry_function)
            if bound_handler:
                record.handler = bound_handler
                record.entry_module = entry_module
                record.entry_function = entry_function

    def _parse_input_schema(self, raw_schema: Any) -> Optional[Dict[str, Any]]:
        if isinstance(raw_schema, dict):
            return raw_schema
        if not isinstance(raw_schema, str) or not raw_schema.strip():
            return None
        try:
            parsed = json.loads(raw_schema)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            return None
        return None

    def _load_handler_from_record(
        self,
        record: SkillRecord,
        entry_module: str,
        entry_function: str,
    ) -> Optional[SkillHandler]:
        skill_dir = self._resolve_path(record.path)
        module_file = self._resolve_entry_module_file(skill_dir, entry_module)
        if not module_file.exists() or not module_file.is_file():
            return None

        try:
            module_name = f"skill_dynamic_{record.name}_{abs(hash(str(module_file)))}"
            spec = importlib.util.spec_from_file_location(module_name, module_file)
            if not spec or not spec.loader:
                return None
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            target = getattr(module, entry_function, None)
            if not callable(target):
                return None

            async def _runner(arguments: Dict[str, Any]) -> Any:
                try:
                    signature = inspect.signature(target)
                    params = list(signature.parameters.values())
                except Exception:
                    params = []

                if not params:
                    output = target()
                elif len(params) == 1:
                    output = target(arguments or {})
                else:
                    output = target(**(arguments or {}))

                if inspect.isawaitable(output):
                    output = await output
                return output

            return _runner
        except Exception as exc:
            logger.debug("自动绑定 skill 失败: {} -> {}.{} ({})", record.name, entry_module, entry_function, exc)
            return None

    @staticmethod
    def _resolve_entry_module_file(skill_dir: Path, entry_module: str) -> Path:
        normalized = str(entry_module).replace("\\", "/").strip()
        if normalized.endswith(".py"):
            return skill_dir / normalized
        return skill_dir / f"{normalized.replace('.', '/')}.py"

    def _build_record(self, item: Any) -> Optional[SkillRecord]:
        if not isinstance(item, dict):
            return None
        name = str(item.get("name") or "").strip()
        if not name:
            return None

        path = str(item.get("path") or f"src/skills/{name}").replace("\\", "/")
        source = str(item.get("source") or "registry")
        registered_at = str(item.get("registered_at") or datetime.now(timezone.utc).isoformat())
        return SkillRecord(
            name=name,
            path=path,
            source=source,
            registered_at=registered_at,
            entry_module=str(item.get("entry_module") or ""),
            entry_function=str(item.get("entry_function") or ""),
        )

    def _refresh_skills_root_from_env(self) -> None:
        if self._explicit_skills_root is not None:
            return

        if self.env_file.exists():
            load_dotenv(dotenv_path=self.env_file, override=False)

        env_root = str(os.getenv("SKILLS_ROOT") or "").strip()
        next_root = Path(env_root).expanduser() if env_root else Path(__file__).resolve().parent

        if next_root == self.skills_root:
            return

        self.skills_root = next_root
        self.registry_file = self.skills_root / "registry.json"
        self._initialized = False
        logger.info("SkillMgr 切换 skills_root 为: {}", self.skills_root)

    def _resolve_path(self, raw_path: str) -> Path:
        normalized = str(raw_path).replace("\\", "/")
        if normalized.startswith("src/skills/"):
            return self.skills_root / normalized.replace("src/skills/", "", 1)
        return Path(normalized)

    def _to_rel_path(self, path: Path) -> str:
        try:
            rel = path.resolve().relative_to(self.skills_root.resolve())
            return f"src/skills/{str(rel).replace('\\', '/')}"
        except Exception:
            return str(path).replace("\\", "/")


def get_skill_manager() -> SkillMgr:
    return SkillMgr.get_instance()


async def init_skill_manager() -> SkillMgr:
    manager = get_skill_manager()
    await manager.initialize()
    return manager
