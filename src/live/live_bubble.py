import asyncio
import time
from typing import Dict


class LiveBubble:
    """Manage a single Telegram message bubble that is updated incrementally.

    This class stores agent sections and serialises updates through an internal
    asyncio.Queue. Call `start(flush_cb)` to begin the flush loop where `flush_cb`
    is an async callable receiving the rendered text and should perform the
    `edit_message_text` call.
    """

    def __init__(self, throttle_ms: int = 800):
        self.sections: Dict[str, str] = {}
        self.queue: asyncio.Queue = asyncio.Queue()
        self.throttle = throttle_ms / 1000.0
        self._task = None
        self._last_flush = 0.0
        self._icons = {
            "pending": "[ ]",
            "running": "[~]",
            "done": "[+]",
            "error": "[!]",
        }

    def update(self, agent_id: str, text: str):
        # text may include status prefix like 'running...' or 'done'
        self.sections[agent_id] = text
        # non-blocking enqueue
        try:
            self.queue.put_nowait(True)
        except asyncio.QueueFull:
            pass

    def render(self) -> str:
        parts = ["Rikka is assembling your team, Oni-San~", "", "Agents:"]
        for aid, txt in self.sections.items():
            # pick icon based on keywords
            icon = self._icons.get("pending")
            if "running" in txt.lower():
                icon = self._icons.get("running")
            if "done" in txt.lower() or "stored" in txt.lower():
                icon = self._icons.get("done")
            if "error" in txt.lower():
                icon = self._icons.get("error")
            parts.append(f"{icon} {aid} — {txt}")
        return "\n".join(parts)

    async def start(self, flush_cb):
        if self._task:
            return
        self._task = asyncio.create_task(self._loop(flush_cb))

    async def stop(self):
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _loop(self, flush_cb):
        while True:
            await self.queue.get()
            now = time.time()
            elapsed = now - self._last_flush
            if elapsed < self.throttle:
                await asyncio.sleep(self.throttle - elapsed)
            text = self.render()
            await flush_cb(text)
            self._last_flush = time.time()
