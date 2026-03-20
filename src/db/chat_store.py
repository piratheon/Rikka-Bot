from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Dict, List, Optional

from src.db.connection import get_db
from src.db.vector_store import vector_store


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


async def add_chat_message(
    user_id: int,
    role: str,
    content: str,
    metadata: Optional[Dict] = None,
) -> None:
    async with get_db() as db:
        await db.execute(
            "INSERT INTO chat_history (user_id, role, content, metadata) VALUES (?, ?, ?, ?)",
            (user_id, role, content, json.dumps(metadata) if metadata else None),
        )
        await db.commit()

    # Persist to vector store asynchronously (fire-and-forget)
    if role in ("user", "assistant"):
        asyncio.create_task(
            vector_store.add_memory(
                user_id=user_id,
                text=content,
                metadata={"role": role, "timestamp": _utcnow()},
            )
        )


async def get_chat_history(
    user_id: int, limit: int = 20, after_id: int = 0
) -> List[Dict]:
    async with get_db() as db:
        cur = await db.execute(
            "SELECT role, content, id, metadata FROM chat_history "
            "WHERE user_id = ? AND id > ? ORDER BY id DESC LIMIT ?",
            (user_id, after_id, limit),
        )
        rows = await cur.fetchall()
    return [
        {
            "role": r[0],
            "content": r[1],
            "id": r[2],
            "metadata": json.loads(r[3]) if r[3] else None,
        }
        for r in reversed(rows)
    ]


async def get_summary_data(user_id: int) -> Optional[Dict]:
    async with get_db() as db:
        cur = await db.execute(
            "SELECT summary, last_msg_id FROM chat_summaries WHERE user_id = ?",
            (user_id,),
        )
        row = await cur.fetchone()
    if row:
        return {"summary": row[0], "last_msg_id": row[1]}
    return None


async def update_summary(user_id: int, summary: str, last_msg_id: int) -> None:
    async with get_db() as db:
        await db.execute(
            "INSERT OR REPLACE INTO chat_summaries (user_id, summary, last_msg_id, updated_at) "
            "VALUES (?, ?, ?, datetime('now'))",
            (user_id, summary, last_msg_id),
        )
        await db.commit()


# ---------------------------------------------------------------------------
# Persistent memory (key-value per user)
# ---------------------------------------------------------------------------

async def save_rika_memory(
    user_id: int, key: str, value: str, mem_type: str = "memory"
) -> None:
    async with get_db() as db:
        await db.execute(
            "INSERT OR REPLACE INTO rika_memory (user_id, mem_key, mem_value, mem_type) "
            "VALUES (?, ?, ?, ?)",
            (user_id, key, value, mem_type),
        )
        await db.commit()


async def get_rika_memories(user_id: int, mem_type: str = "memory") -> Dict[str, str]:
    async with get_db() as db:
        cur = await db.execute(
            "SELECT mem_key, mem_value FROM rika_memory WHERE user_id = ? AND mem_type = ?",
            (user_id, mem_type),
        )
        rows = await cur.fetchall()
    return {r[0]: r[1] for r in rows}


async def delete_rika_memory(user_id: int, key: str, mem_type: str = "memory") -> None:
    async with get_db() as db:
        await db.execute(
            "DELETE FROM rika_memory WHERE user_id = ? AND mem_key = ? AND mem_type = ?",
            (user_id, key, mem_type),
        )
        await db.commit()


async def list_rika_memories(user_id: int) -> List[Dict]:
    """Return all memory and skill entries for a user (for /memory command)."""
    async with get_db() as db:
        cur = await db.execute(
            "SELECT mem_key, mem_value, mem_type, created_at FROM rika_memory "
            "WHERE user_id = ? ORDER BY mem_type, mem_key",
            (user_id,),
        )
        rows = await cur.fetchall()
    return [{"key": r[0], "value": r[1], "type": r[2], "created_at": r[3]} for r in rows]
