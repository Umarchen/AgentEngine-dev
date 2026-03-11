"""
Skill 增量刷新定时器
定期触发 SkillMgr 增量刷新，用于接收外部（如 Pivot）写入的新 skill。
"""

import asyncio
import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from loguru import logger

from src.skills.skillmgr import SkillMgr, get_skill_manager


class SkillRefreshTimer:
    _instance: Optional["SkillRefreshTimer"] = None

    def __init__(
        self,
        skill_manager: Optional[SkillMgr] = None,
        refresh_interval_seconds: int = 600,
    ):
        self._skill_manager = skill_manager or get_skill_manager()
        self._refresh_interval_seconds = max(int(refresh_interval_seconds), 1)

        self._running = False
        self._task: Optional[asyncio.Task] = None

        logger.info(
            "Skill 增量刷新定时器初始化完成，刷新间隔: {} 秒",
            self._refresh_interval_seconds,
        )

    @classmethod
    def get_instance(
        cls,
        skill_manager: Optional[SkillMgr] = None,
        refresh_interval_seconds: int = 600,
    ) -> "SkillRefreshTimer":
        if cls._instance is None:
            cls._instance = cls(skill_manager, refresh_interval_seconds)
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        cls._instance = None

    @property
    def is_running(self) -> bool:
        return self._running

    async def start(self) -> None:
        if self._running:
            logger.warning("Skill 增量刷新定时器已在运行")
            return

        self._running = True
        self._task = asyncio.create_task(self._refresh_loop())
        logger.info("Skill 增量刷新定时器已启动")

    async def stop(self) -> None:
        if not self._running:
            return

        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

        logger.info("Skill 增量刷新定时器已停止")

    async def _refresh_loop(self) -> None:
        logger.info("Skill 增量刷新循环开始")

        while self._running:
            try:
                await self._skill_manager.refresh_skills_incremental()
            except Exception as exc:
                logger.error("Skill 增量刷新失败: {}", exc)

            try:
                await asyncio.sleep(self._refresh_interval_seconds)
            except asyncio.CancelledError:
                break

        logger.info("Skill 增量刷新循环结束")


def _get_skill_refresh_interval_from_env(default_seconds: int = 600) -> int:
    env_file = Path(__file__).resolve().parents[2] / ".env"
    if env_file.exists():
        load_dotenv(dotenv_path=env_file, override=False)

    raw = str(os.getenv("SKILL_REFRESH_INTERVAL_SECONDS") or "").strip()
    if not raw:
        return default_seconds

    try:
        value = int(raw)
        return value if value > 0 else default_seconds
    except Exception:
        logger.warning("SKILL_REFRESH_INTERVAL_SECONDS 非法，使用默认值 {} 秒", default_seconds)
        return default_seconds


_skill_refresh_timer: Optional[SkillRefreshTimer] = None


def get_skill_refresh_timer() -> SkillRefreshTimer:
    global _skill_refresh_timer
    _skill_refresh_timer = SkillRefreshTimer.get_instance()
    return _skill_refresh_timer


async def init_skill_refresh_timer(
    skill_manager: Optional[SkillMgr] = None,
    refresh_interval_seconds: Optional[int] = None,
) -> SkillRefreshTimer:
    global _skill_refresh_timer

    interval = (
        int(refresh_interval_seconds)
        if refresh_interval_seconds is not None
        else _get_skill_refresh_interval_from_env(default_seconds=600)
    )

    _skill_refresh_timer = SkillRefreshTimer.get_instance(
        skill_manager=skill_manager,
        refresh_interval_seconds=interval,
    )
    await _skill_refresh_timer.start()
    return _skill_refresh_timer


async def stop_skill_refresh_timer() -> None:
    global _skill_refresh_timer
    if _skill_refresh_timer:
        await _skill_refresh_timer.stop()
        _skill_refresh_timer = None
