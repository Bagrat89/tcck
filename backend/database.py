"""
database.py — async SQLite через aiosqlite.
WAL mode + expires_at колонка + UNIQUE index на channel_message_id.
"""
from __future__ import annotations
import asyncio
import aiosqlite
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from config import get_settings
from models import LocationRecord

logger = logging.getLogger(__name__)
settings = get_settings()


def _now() -> str:
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat()

def _expires() -> str:
    return (datetime.now(timezone.utc).replace(tzinfo=None)
            + timedelta(seconds=settings.location_ttl_seconds)).isoformat()


async def init_db() -> None:
    async with aiosqlite.connect(settings.db_path) as db:
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute("PRAGMA synchronous=NORMAL")
        await db.execute("""
            CREATE TABLE IF NOT EXISTS locations (
                id                 INTEGER PRIMARY KEY AUTOINCREMENT,
                message_text       TEXT    NOT NULL,
                location_name      TEXT    NOT NULL,
                location_type      TEXT    NOT NULL DEFAULT 'point',
                lat                REAL    NOT NULL,
                lng                REAL    NOT NULL,
                confidence         REAL    NOT NULL DEFAULT 0.0,
                created_at         TEXT    NOT NULL,
                expires_at         TEXT    NOT NULL,
                channel_message_id INTEGER UNIQUE
            )
        """)
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_exp ON locations (expires_at)"
        )
        await db.commit()
    logger.info("DB ready: %s", settings.db_path)


async def insert_location(
    message_text: str,
    location_name: str,
    location_type: str,
    lat: float,
    lng: float,
    confidence: float,
    channel_message_id: Optional[int] = None,
) -> Optional[int]:
    try:
        async with aiosqlite.connect(settings.db_path) as db:
            cur = await db.execute(
                """INSERT OR IGNORE INTO locations
                   (message_text,location_name,location_type,lat,lng,
                    confidence,created_at,expires_at,channel_message_id)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (message_text, location_name, location_type, lat, lng,
                 confidence, _now(), _expires(), channel_message_id),
            )
            await db.commit()
            return cur.lastrowid if cur.rowcount else None
    except aiosqlite.IntegrityError:
        return None


async def get_active_locations() -> list[LocationRecord]:
    async with aiosqlite.connect(settings.db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT id,message_text,location_name,location_type,
                      lat,lng,confidence,created_at,expires_at,channel_message_id
               FROM   locations WHERE expires_at > ? ORDER BY created_at DESC""",
            (_now(),),
        ) as cur:
            rows = await cur.fetchall()
    return [
        LocationRecord(
            id=r["id"], message_text=r["message_text"],
            location_name=r["location_name"], location_type=r["location_type"],
            lat=r["lat"], lng=r["lng"], confidence=r["confidence"],
            created_at=datetime.fromisoformat(r["created_at"]),
            expires_at=datetime.fromisoformat(r["expires_at"]),
            channel_message_id=r["channel_message_id"],
        )
        for r in rows
    ]


async def message_id_exists(mid: int) -> bool:
    async with aiosqlite.connect(settings.db_path) as db:
        async with db.execute(
            "SELECT 1 FROM locations WHERE channel_message_id=? LIMIT 1", (mid,)
        ) as cur:
            return await cur.fetchone() is not None


async def purge_expired() -> int:
    async with aiosqlite.connect(settings.db_path) as db:
        cur = await db.execute("DELETE FROM locations WHERE expires_at<=?", (_now(),))
        await db.commit()
        n = cur.rowcount
    if n:
        logger.info("Purged %d expired rows", n)
    return n


async def run_cleanup_loop() -> None:
    logger.info("Cleanup loop started (%ds interval)", settings.cleanup_interval_seconds)
    while True:
        await asyncio.sleep(settings.cleanup_interval_seconds)
        try:
            await purge_expired()
        except Exception as e:
            logger.error("Cleanup error: %s", e)
