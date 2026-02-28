import asyncio
from datetime import datetime
from ..db import key_store


async def unblacklist_loop(interval_seconds: int = 60):
    """Periodically un-blacklist keys whose `quota_resets_at` has passed."""
    while True:
        try:
            rows = await key_store.list_blacklisted_due()
            for key_id in rows:
                await key_store.unblacklist_key(key_id)
        except Exception:
            # ignore errors to keep loop alive
            pass
        await asyncio.sleep(interval_seconds)
