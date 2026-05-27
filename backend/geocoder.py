"""
geocoder.py — Nominatim геокодер с 3 стратегиями.
Всегда использует normalized_name (новое название) для лучшего попадания в OSM.
"""
from __future__ import annotations
import logging
import httpx

from config import get_settings
from street_names import normalize_street

logger = logging.getLogger(__name__)
settings = get_settings()

_URL    = "https://nominatim.openstreetmap.org/search"
_BOUNDS = {
    "format": "jsonv2", "limit": 1,
    "countrycodes": "ua",
    "viewbox": "30.55,46.60,31.10,46.25",
    "bounded": 1,
}


async def _get(query: str) -> tuple[float, float] | None:
    try:
        async with httpx.AsyncClient(timeout=10.0) as c:
            r = await c.get(_URL,
                            params={**_BOUNDS, "q": query},
                            headers={"User-Agent": settings.nominatim_user_agent})
            r.raise_for_status()
            hits = r.json()
    except httpx.HTTPError as e:
        logger.error("Nominatim: %s", e)
        return None
    if not hits:
        return None
    lat, lng = float(hits[0]["lat"]), float(hits[0]["lon"])
    logger.info("Nominatim: '%s' → (%.4f, %.4f)", query, lat, lng)
    return lat, lng


async def geocode(name: str) -> tuple[float, float] | None:
    """
    3 стратегии:
    1. normalized + ', Одеса, Україна'
    2. original   + ', Одеса, Україна'   (если отличается)
    3. normalized  без города            (для landmark-ов)
    """
    normalized, was_renamed = normalize_street(name)
    queries: list[str] = [f"{normalized}, Одеса, Україна"]
    if was_renamed and name.strip().lower() != normalized.strip().lower():
        queries.append(f"{name}, Одеса, Україна")
    queries.append(normalized)

    for q in queries:
        r = await _get(q)
        if r:
            return r
    logger.warning("Nominatim: no result for '%s'", name)
    return None


async def refine_coordinates(
    location_name: str,
    ai_lat: float,
    ai_lng: float,
    ai_confidence: float,
    normalized_name: str | None = None,
) -> tuple[float, float]:
    """
    Финальные координаты:
    - conf >= 0.80 и координаты есть → доверяем AI
    - иначе → пробуем Nominatim (с normalized_name)
    - Nominatim не нашёл → берём координаты AI
    - оба пустые → (0.0, 0.0) → caller пропустит запись
    """
    lookup = normalized_name or location_name
    no_coords = (ai_lat == 0.0 and ai_lng == 0.0)

    if ai_confidence >= 0.80 and not no_coords:
        return ai_lat, ai_lng

    result = await geocode(lookup)
    if result:
        return result
    if not no_coords:
        return ai_lat, ai_lng

    logger.warning("No coords for '%s' — record skipped", lookup)
    return 0.0, 0.0
