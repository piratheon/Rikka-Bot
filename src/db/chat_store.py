from src.db.connection import get_db
from typing import List, Dict, Optional
import asyncio
import json

async def add_chat_message(user_id: int, role: str, content: str, metadata: Optional[Dict] = None):
    async with get_db() as db:
        meta_json = json.dumps(metadata) if metadata else None
        await db.execute(
            "INSERT INTO chat_history (user_id, role, content, metadata) VALUES (?, ?, ?, ?)",
            (user_id, role, content, meta_json)
        )
        await db.commit()

async def get_chat_history(user_id: int, limit: int = 20, after_id: int = 0) -> List[Dict]:
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT role, content, id, metadata FROM chat_history WHERE user_id = ? AND id > ? ORDER BY id DESC LIMIT ?",
            (user_id, after_id, limit)
        )
        rows = await cursor.fetchall()
        # Return in chronological order
        return [{"role": r[0], "content": r[1], "id": r[2], "metadata": json.loads(r[3]) if r[3] else None} for r in reversed(rows)]

async def get_summary_data(user_id: int) -> Optional[Dict]:
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT summary, last_msg_id FROM chat_summaries WHERE user_id = ?",
            (user_id,)
        )
        row = await cursor.fetchone()
        if row:
            return {"summary": row[0], "last_msg_id": row[1]}
        return None

async def update_summary(user_id: int, summary: str, last_msg_id: int):
    async with get_db() as db:
        await db.execute(
            "INSERT OR REPLACE INTO chat_summaries (user_id, summary, last_msg_id, updated_at) VALUES (?, ?, ?, datetime('now'))",
            (user_id, summary, last_msg_id)
        )
        await db.commit()

# Memory functions
async def save_rikka_memory(user_id: int, key: str, value: str, mem_type: str = 'memory'):
    async with get_db() as db:
        await db.execute(
            "INSERT OR REPLACE INTO rikka_memory (user_id, mem_key, mem_value, mem_type) VALUES (?, ?, ?, ?)",
            (user_id, key, value, mem_type)
        )
        await db.commit()

async def get_rikka_memories(user_id: int, mem_type: str = 'memory') -> Dict[str, str]:
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT mem_key, mem_value FROM rikka_memory WHERE user_id = ? AND mem_type = ?",
            (user_id, mem_type)
        )
        rows = await cursor.fetchall()
        return {r[0]: r[1] for r in rows}

async def delete_rikka_memory(user_id: int, key: str, mem_type: str = 'memory'):
    async with get_db() as db:
        await db.execute(
            "DELETE FROM rikka_memory WHERE user_id = ? AND mem_key = ? AND mem_type = ?",
            (user_id, key, mem_type)
        )
        await db.commit()
