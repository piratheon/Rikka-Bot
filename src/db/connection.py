import aiosqlite
import os
from pathlib import Path
from contextlib import asynccontextmanager

DB_PATH = os.environ.get("DATABASE_PATH", "./data/rikka.db")


@asynccontextmanager
async def get_db():
    """Async context manager for database connections."""
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute("PRAGMA foreign_keys = ON;")
        yield conn
