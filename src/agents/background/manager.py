"""BackgroundAgentManager

Lifecycle:
  1. On bot start, manager.start(bot) is called once.
  2. All enabled BackgroundAgentConfig rows are loaded from DB.
  3. For each, a pure-Python watcher loop is spawned as an asyncio Task.
  4. Watcher loops never touch an LLM. They call watcher.check() every
     interval_seconds and push WakeSignals to a shared async queue.
  5. A separate WakeProcessor task consumes the queue. For each signal it:
       - If needs_ai_analysis=False: sends the raw summary directly to the user.
       - If needs_ai_analysis=True: makes one LLM call for a short analysis,
         then sends the result to the user.
  6. Users register new watchers via /watch. The manager persists the config,
     starts the watcher task, and acknowledges.
"""
from __future__ import annotations

import asyncio
import json
from typing import Dict, Optional

from src.agents.agent_models import BackgroundAgentConfig, WakeSignal
from src.agents.background.watchers import (
    CronWatcher,
    LogPatternWatcher,
    PortWatcher,
    ProcessWatcher,
    SystemWatcher,
    URLWatcher,
    WatcherBase,
)
from src.config import Config
from src.db.background_store import (
    disable_background_agent,
    list_user_background_agents,
    load_all_background_agents,
    save_background_agent,
    save_wake_event,
    update_agent_trigger_count,
)
from src.providers.provider_pool import get_pool
from src.utils.logger import logger


class BackgroundAgentManager:
    """Singleton. One instance per bot process."""

    _instance: Optional[BackgroundAgentManager] = None

    # ------------------------------------------------------------------
    # Construction / singleton
    # ------------------------------------------------------------------

    def __init__(self, bot) -> None:
        self._bot = bot
        self._tasks: Dict[str, asyncio.Task] = {}
        self._wake_queue: asyncio.Queue[WakeSignal] = asyncio.Queue(maxsize=256)
        self._processor: Optional[asyncio.Task] = None
        self._started = False

    @classmethod
    def initialize(cls, bot) -> BackgroundAgentManager:
        cls._instance = cls(bot)
        return cls._instance

    @classmethod
    def get(cls) -> Optional[BackgroundAgentManager]:
        return cls._instance

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def start(self) -> None:
        if self._started:
            return
        self._started = True
        self._processor = asyncio.create_task(
            self._wake_processor_loop(), name="wake_processor"
        )
        agents = await load_all_background_agents()
        for cfg in agents:
            if cfg.enabled:
                await self._spawn_watcher(cfg)
        logger.info("background_manager_started", active=len(self._tasks))

    async def register(self, cfg: BackgroundAgentConfig) -> None:
        """Persist a new watcher config and start its loop immediately."""
        await save_background_agent(cfg)
        await self._spawn_watcher(cfg)
        logger.info("background_agent_registered", id=cfg.id, type=cfg.watcher_type)

    async def stop_agent(self, agent_id: str) -> bool:
        task = self._tasks.pop(agent_id, None)
        if task is None:
            return False
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        await disable_background_agent(agent_id)
        logger.info("background_agent_stopped", id=agent_id)
        return True

    async def list_for_user(self, user_id: int) -> list:
        return await list_user_background_agents(user_id)

    # ------------------------------------------------------------------
    # Internal — watcher spawning
    # ------------------------------------------------------------------

    def _build_watcher(self, cfg: BackgroundAgentConfig) -> Optional[WatcherBase]:
        c = cfg.config
        t = cfg.watcher_type
        try:
            if t == "system":
                return SystemWatcher(
                    cpu_threshold=float(c.get("cpu_threshold", 85)),
                    mem_threshold=float(c.get("mem_threshold", 90)),
                    disk_threshold=float(c.get("disk_threshold", 90)),
                    load_threshold=float(c.get("load_threshold", 4.0)),
                )
            if t == "process":
                return ProcessWatcher(process_name=c["process_name"])
            if t == "url":
                return URLWatcher(
                    url=c["url"],
                    expected_status=int(c.get("expected_status", 200)),
                    timeout=int(c.get("timeout", 10)),
                )
            if t == "port":
                return PortWatcher(
                    host=c.get("host", "localhost"),
                    port=int(c["port"]),
                )
            if t == "log":
                return LogPatternWatcher(
                    file_path=c["file_path"],
                    pattern=c["pattern"],
                    cooldown_seconds=int(c.get("cooldown_seconds", 300)),
                )
            if t == "cron":
                return CronWatcher(task_description=c.get("task_description", cfg.description))
        except (KeyError, ValueError, TypeError) as exc:
            logger.error("watcher_build_failed", agent_id=cfg.id, type=t, error=str(exc))
        return None

    async def _spawn_watcher(self, cfg: BackgroundAgentConfig) -> None:
        watcher = self._build_watcher(cfg)
        if watcher is None:
            return
        # Cancel any existing task for this id (re-registration)
        old = self._tasks.pop(cfg.id, None)
        if old and not old.done():
            old.cancel()

        task = asyncio.create_task(
            self._watcher_loop(cfg, watcher),
            name=f"watcher_{cfg.id}",
        )
        self._tasks[cfg.id] = task

    async def _watcher_loop(self, cfg: BackgroundAgentConfig, watcher: WatcherBase) -> None:
        logger.info("watcher_loop_started", id=cfg.id, type=cfg.watcher_type, interval=cfg.interval_seconds)
        while True:
            try:
                signal = await watcher.check()
                if signal is not None:
                    signal.agent_id = cfg.id
                    signal.user_id = cfg.user_id
                    signal.chat_id = cfg.chat_id
                    signal.ai_context = cfg.description
                    try:
                        self._wake_queue.put_nowait(signal)
                    except asyncio.QueueFull:
                        logger.warning("wake_queue_full_dropping_signal", agent_id=cfg.id)
                    await update_agent_trigger_count(cfg.id)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("watcher_loop_error", agent_id=cfg.id, error=str(exc))
            await asyncio.sleep(cfg.interval_seconds)

    # ------------------------------------------------------------------
    # Internal — wake signal processing
    # ------------------------------------------------------------------

    async def _wake_processor_loop(self) -> None:
        logger.info("wake_processor_started")
        while True:
            try:
                signal = await self._wake_queue.get()
                # Fire-and-forget so one slow LLM call doesn't block others
                asyncio.create_task(self._handle_signal(signal))
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("wake_processor_error", error=str(exc))

    async def _handle_signal(self, signal: WakeSignal) -> None:
        severity_tag = {"info": "INFO", "warning": "WARN", "critical": "CRIT"}.get(
            signal.severity, "WARN"
        )

        if not signal.needs_ai_analysis:
            raw = "\n".join(f"{k}: {v}" for k, v in signal.raw_data.items())
            text = f"<b>[{severity_tag}] {signal.agent_id}</b>\n\n{raw}"
            await self._send(signal.chat_id, text)
            await save_wake_event(signal, raw)
            return

        # AI analysis turn (one LLM call, short output)
        cfg = Config.get()
        pool = get_pool()
        context_str = json.dumps(signal.raw_data, indent=2)

        payload = {
            "model": cfg.default_model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        cfg.system_prompt
                        + "\n\nYou are a background sentinel agent. A monitoring script detected "
                        "an anomaly. Write a concise notification (max 120 words): state what happened, "
                        "what it likely means, and one concrete remediation suggestion if applicable."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Agent: {signal.agent_id}\n"
                        f"Purpose: {signal.ai_context}\n"
                        f"Event: {signal.event_type} [{signal.severity}]\n\n"
                        f"Raw data:\n{context_str}"
                    ),
                },
            ],
        }

        analysis = ""
        for provider in (cfg.default_provider_priority or ["gemini", "groq", "openrouter"]):
            try:
                resp = await pool.request_with_key(signal.user_id, provider, payload)
                analysis = resp.get("output", "").strip()
                if analysis:
                    break
            except Exception as exc:
                logger.warning("wake_ai_failed", provider=provider, error=str(exc))
                continue

        if not analysis:
            analysis = context_str[:400]

        text = f"<b>[{severity_tag}] {signal.agent_id}</b>\n\n{analysis}"
        await self._send(signal.chat_id, text)
        await save_wake_event(signal, analysis)

    async def _send(self, chat_id: int, text: str) -> None:
        try:
            await self._bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML")
        except Exception as exc:
            logger.error("wake_send_failed", chat_id=chat_id, error=str(exc))
