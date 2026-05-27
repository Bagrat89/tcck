"""
ai_parser.py — Claude API парсер локаций.
location_name сохраняется как есть (для показа пользователю),
normalized_name идёт в геокодер.
"""
from __future__ import annotations
import json
import logging
import re
import httpx

from config import get_settings
from models import ParsedLocation
from street_names import inject_rename_context, normalize_street, get_display_name

logger = logging.getLogger(__name__)
settings = get_settings()

_RENAMES = inject_rename_context()

SYSTEM_PROMPT = f"""You are a geolocation assistant for Odessa (Odesa), Ukraine.

Extract location from Ukrainian/Russian Telegram messages about ТЦК/ВКС sightings.

Respond with ONLY a JSON object — no markdown, no extra text:
{{
  "location_name": "<name exactly as written in the message>",
  "type": "point" | "district" | "street",
  "lat": <float or 0.0>,
  "lng": <float or 0.0>,
  "confidence": <0.0 to 1.0>
}}

type rules:
- "point"    — specific landmark, mall, market (Привоз, Ашан, Сіті Центр)
- "street"   — named street or intersection
- "district" — neighbourhood (Таїрове, Черьомушки, Молдаванка, Пересип)

{_RENAMES}

When assigning lat/lng — use the NEW (post-rename) street coordinates even if the
message uses the old name. If unsure about coordinates, return 0.0 — the geocoder
will handle it. Do not guess.

Reference coordinates (current, post-rename):
- Привоз ринок:                              46.4825, 30.7326
- City Center / Сіті Центр (Таїрове):        46.4274, 30.7153
- ТРЦ Атмосфера:                             46.4169, 30.7609
- River Mall:                                46.4593, 30.7383
- Sky Mall:                                  46.4189, 30.7561
- Залізничний вокзал:                        46.4849, 30.7403
- Аркадія:                                   46.4108, 30.7760
- Черьомушки:                                46.4340, 30.7050
- Таїрове:                                   46.4230, 30.7100
- Молдаванка:                                46.4940, 30.7200
- Пересип:                                   46.5050, 30.7500
- вул. Балківська:                           46.4770, 30.7430
- Думська площа (кол. пл. Леніна):           46.4860, 30.7340
- просп. Захисників України (кол. Котовського): 46.4310, 30.7020
- вул. Героїв Крут (кол. Жукова):            46.4720, 30.7280
- просп. Героїв Небесної Сотні (кол. Добровольського): 46.4290, 30.6950

If confidence < 0.3 or location unknown:
{{"location_name": "", "type": "point", "lat": 0.0, "lng": 0.0, "confidence": 0.0}}
"""


async def parse_location(text: str) -> ParsedLocation | None:
    if not text or len(text.strip()) < 5:
        return None

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": settings.anthropic_api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": "claude-sonnet-4-20250514",
                    "max_tokens": 300,
                    "system": SYSTEM_PROMPT,
                    "messages": [{"role": "user", "content": text.strip()}],
                },
            )
            resp.raise_for_status()
    except httpx.HTTPError as e:
        logger.error("Claude API: %s", e)
        return None

    try:
        raw = resp.json()["content"][0]["text"].strip()
        raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.MULTILINE).strip()
        loc = ParsedLocation(**json.loads(raw))
    except Exception as e:
        logger.error("Parse error: %s | raw=%s", e, resp.text[:200])
        return None

    if loc.confidence < 0.30 or not loc.location_name.strip():
        return None

    # Нормализация названия улицы
    original = loc.location_name
    normalized, was_renamed = normalize_street(original)
    loc.location_name = get_display_name(original, normalized, was_renamed)
    loc.normalized_name = normalized  # type: ignore[attr-defined]

    logger.info("Parsed: '%s' [%s] (%.4f,%.4f) conf=%.0f%%",
                loc.location_name, loc.type, loc.lat, loc.lng, loc.confidence * 100)
    return loc