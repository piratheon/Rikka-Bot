from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from datetime import datetime
from typing import Dict
from .db import key_store
from .config import Config


def _schedule_unblacklist_for_provider(scheduler: AsyncIOScheduler, provider: str, hour_utc: int):
    # Schedule a daily job at `hour_utc` to unblacklist keys for this provider
    trigger = CronTrigger(hour=hour_utc, minute=0)

    async def job():
        # find blacklisted keys for this provider whose reset time is due
        rows = await key_store.list_blacklisted_due()
        for key_id in rows:
            await key_store.unblacklist_key(key_id)

    scheduler.add_job(job, trigger, id=f"unblacklist_{provider}")


def start_scheduler(config: Config) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler()
    # Provider reset hours in config
    mapping = {
        "gemini": getattr(config, "gemini_quota_reset_utc_hour", 8),
        "openrouter": getattr(config, "openrouter_quota_reset_utc_hour", 0),
        "groq": getattr(config, "groq_quota_reset_utc_hour", 0),
    }
    for provider, hour in mapping.items():
        try:
            _schedule_unblacklist_for_provider(scheduler, provider, int(hour))
        except Exception:
            continue

    scheduler.start()
    return scheduler
