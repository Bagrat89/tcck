"""
telethon_listener.py — слушатель Telegram-канала.

Особенности:
  - StringSession (не нужен .session файл на сервере)
  - Работает с ЗАКРЫТЫМИ / ПРИВАТНЫМИ каналами через user account
  - Автоматическое переподключение с exponential backoff
  - FloodWaitError — ждём ровно сколько требует Telegram
  - Дедупликация: memory cache + DB UNIQUE index
  - Graceful shutdown при CancelledError
"""
from __future__ import annotations
import asyncio
import logging

from telethon import TelegramClient, events
from telethon.errors import FloodWaitError, AuthKeyUnregisteredError, UserDeactivatedError

from config import get_settings
from ai_parser import parse_location
from geocoder import refine_coordinates
from database import insert_location, message_id_exists

logger = logging.getLogger(__name__)
settings = get_settings()

# ── In-memory dedup cache ─────────────────────────────────────────────────────
_CACHE_MAX = 500
_seen: set[int] = set()
_seen_q: list[int] = []


def _mark(mid: int) -> None:
    if mid in _seen:
        return
    _seen.add(mid)
    _seen_q.append(mid)
    if len(_seen_q) > _CACHE_MAX:
        _seen.discard(_seen_q.pop(0))


def _is_seen(mid: int) -> bool:
    return mid in _seen


# ── Client factory ────────────────────────────────────────────────────────────

def _make_client() -> TelegramClient:
    return TelegramClient(
        settings.get_session(),
        settings.telegram_api_id,
        settings.telegram_api_hash,
        connection_retries=None,
        retry_delay=1,
        auto_reconnect=True,
        request_retries=5,
    )


# ── Pipeline ──────────────────────────────────────────────────────────────────

async def _process(text: str, mid: int) -> None:
    if _is_seen(mid):
        return
    if await message_id_exists(mid):
        _mark(mid)
        return
    _mark(mid)

    logger.info("msg #%d: %.80s", mid, text)

    parsed = await parse_location(text)
    if not parsed:
        return

    normalized = getattr(parsed, "normalized_name", parsed.location_name)
    lat, lng = await refine_coordinates(
        location_name=parsed.location_name,
        ai_lat=parsed.lat,
        ai_lng=parsed.lng,
        ai_confidence=parsed.confidence,
        normalized_name=normalized,
    )

    if lat == 0.0 and lng == 0.0:
        logger.warning("No coords for '%s' — skipped", parsed.location_name)
        return

    rid = await insert_location(
        message_text=text,
        location_name=parsed.location_name,
        location_type=parsed.type,
        lat=lat, lng=lng,
        confidence=parsed.confidence,
        channel_message_id=mid,
    )
    if rid:
        logger.info("✓ #%d '%s' (%.4f,%.4f)", rid, parsed.location_name, lat, lng)


# ── Core listen ───────────────────────────────────────────────────────────────

async def _listen_once(client: TelegramClient) -> None:
    await client.connect()

    if not await client.is_user_authorized():
        raise AuthKeyUnregisteredError(
            "Сессия не авторизована. Запусти tools/gen_session.py"
        )

    try:
        channel = await client.get_entity(settings.target_channel)
        logger.info("Слушаем канал: '%s' (id=%s)",
                    getattr(channel, "title", "?"), channel.id)
    except FloodWaitError as e:
        logger.warning("FloodWait при resolve канала: %ds", e.seconds)
        await asyncio.sleep(e.seconds + 5)
        raise
    except Exception as e:
        logger.error("Не удалось получить канал '%s': %s", settings.target_channel, e)
        raise

    @client.on(events.NewMessage(chats=channel))
    async def _on_msg(event: events.NewMessage.Event) -> None:
        text = (event.message.text or "").strip()
        if text:
            asyncio.create_task(_process(text, event.message.id))

    await client.run_until_disconnected()


# ── Reconnect loop ────────────────────────────────────────────────────────────

async def run_listener() -> None:
    attempt = 0
    delay = settings.reconnect_base_delay
    max_att = settings.reconnect_max_attempts

    while True:
        attempt += 1
        client = _make_client()
        logger.info("Listener попытка #%d", attempt)

        try:
            await _listen_once(client)
            logger.warning("Отключился — переподключаемся")

        except asyncio.CancelledError:
            logger.info("Listener: shutdown")
            try:
                await client.disconnect()
            except Exception:
                pass
            return

        except (AuthKeyUnregisteredError, UserDeactivatedError) as e:
            logger.critical("Критическая ошибка авторизации: %s", e)
            return

        except FloodWaitError as e:
            await asyncio.sleep(e.seconds + 5)
            delay = settings.reconnect_base_delay

        except Exception as e:
            logger.error("Ошибка #%d: %s", attempt, e, exc_info=True)

        finally:
            try:
                if client.is_connected():
                    await client.disconnect()
            except Exception:
                pass

        if max_att > 0 and attempt >= max_att:
            logger.error("Достигнут лимит попыток — останавливаемся")
            return

        logger.info("Переподключение через %.0f с...", delay)
        await asyncio.sleep(delay)
        delay = min(delay * 2, settings.reconnect_max_delay)
