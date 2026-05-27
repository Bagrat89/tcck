/**
 * api.js — обёртка над /locations.
 * 8-секундный таймаут + кеш для слабого интернета.
 * Нормализует UTC-строки из SQLite (добавляет 'Z').
 */
const API = (() => {
  const BASE = window.location.origin;
  let _cache = null;

  function _normISO(s) {
    if (!s) return s;
    return s.endsWith('Z') ? s : s + 'Z';
  }
  function _normLoc(loc) {
    return { ...loc, created_at: _normISO(loc.created_at), expires_at: _normISO(loc.expires_at) };
  }

  async function fetchLocations() {
    let resp;
    try {
      resp = await fetch(BASE + '/locations', {
        cache: 'no-store',
        signal: AbortSignal.timeout(8000),
      });
    } catch (e) {
      console.warn('[API] network error:', e.message);
      return _cache ? _cache.locations : [];
    }
    if (!resp.ok) {
      console.error('[API] HTTP', resp.status);
      return _cache ? _cache.locations : [];
    }
    try {
      const data = await resp.json();
      _cache = data;
      return (data.locations || []).map(_normLoc);
    } catch (e) {
      console.error('[API] JSON error:', e);
      return _cache ? _cache.locations : [];
    }
  }

  return { fetchLocations };
})();
