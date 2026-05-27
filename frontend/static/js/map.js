/**
 * map.js — Leaflet-карта Одессы для Telegram Mini App.
 *
 * ЖЕСТЫ (ключевые настройки):
 *  - dragging: true          — перетаскивание пальцем
 *  - touchZoom: true         — pinch-to-zoom двумя пальцами
 *  - scrollWheelZoom: true   — зум колёсиком (десктоп)
 *  - tap: true               — тапы на iOS
 *  - tapTolerance: 15        — чуть большая зона тапа для мобильных
 *
 *  CSS-правило touch-action: pan-x pan-y на #map — не блокирует Leaflet,
 *  но сообщает браузеру что pan разрешён, что снимает 300ms задержку.
 *
 * ПЕРЕИМЕНОВАНИЯ УЛИЦ:
 *  popup показывает оба названия когда была замена:
 *  "Жукова  →  вул. Героїв Крут"
 */

const MapApp = (() => {

  const CENTER  = [46.4774, 30.7326];
  const ZOOM    = 13;
  const POLL_MS = 15_000;

  const FADE_START = 60 * 60 * 1000;   // 1 час — начинаем блекнуть
  const FADE_END   = 2  * 60 * 60 * 1000; // 2 часа — минимальная прозрачность

  let map;
  /** @type {Map<number, L.Marker>} */
  const markers = new Map();
  let pollTimer = null;
  let busy = false;

  // ── Утилиты ──────────────────────────────────────────────────────────────

  function opacity(createdAt) {
    const age = Date.now() - new Date(createdAt).getTime();
    if (age <= FADE_START) return 1.0;
    const t = (age - FADE_START) / (FADE_END - FADE_START);
    return Math.max(0.22, 1.0 - t * 0.78);
  }

  function relTime(iso) {
    const ms = Date.now() - new Date(iso).getTime();
    const m  = Math.floor(ms / 60000);
    if (m <  1) return 'щойно';
    if (m < 60) return `${m} хв тому`;
    const h = Math.floor(m / 60), rm = m % 60;
    return rm ? `${h} год ${rm} хв тому` : `${h} год тому`;
  }

  function minsLeft(expiresAt) {
    return Math.max(0, Math.round((new Date(expiresAt).getTime() - Date.now()) / 60000));
  }

  function fmtTime(iso) {
    return new Date(iso).toLocaleTimeString('uk-UA', { hour: '2-digit', minute: '2-digit' });
  }

  function esc(s) {
    const d = document.createElement('div');
    d.textContent = s;
    return d.innerHTML;
  }

  const TYPE_LABEL = { point: '📍 Об\'єкт', street: '🛣 Вулиця', district: '🏘 Район' };

  function plural(n) {
    const m10 = n % 10, m100 = n % 100;
    if (m10 === 1 && m100 !== 11) return 'точка';
    if (m10 >= 2 && m10 <= 4 && (m100 < 10 || m100 >= 20)) return 'точки';
    return 'точок';
  }

  // ── SVG-иконка маркера ────────────────────────────────────────────────────

  function buildIcon(op, isNew) {
    const anim = isNew
      ? 'style="animation:markerEntry .35s cubic-bezier(.34,1.56,.64,1) both"'
      : '';
    const p = op.toFixed(2);
    const p2 = (op * 0.45).toFixed(2);
    const p3 = (op * 0.28).toFixed(2);
    return L.divIcon({
      html: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 44 44"
               width="44" height="44" ${anim}>
        <circle cx="22" cy="22" r="13" fill="none"
          stroke="#ff2d2d" stroke-width="1.5" opacity="${p2}">
          <animate attributeName="r" values="13;21;13" dur="2.4s" repeatCount="indefinite"/>
          <animate attributeName="opacity"
            values="${p2};0;${p2}" dur="2.4s" repeatCount="indefinite"/>
        </circle>
        <circle cx="22" cy="22" r="9" fill="none"
          stroke="#ff2d2d" stroke-width="1" opacity="${p3}"/>
        <circle cx="22" cy="22" r="6" fill="#ff2d2d" opacity="${p}"/>
        <circle cx="22" cy="22" r="2.5" fill="#ff9090" opacity="${p}"/>
      </svg>`,
      className: 'tcck-icon',
      iconSize:   [44, 44],
      iconAnchor: [22, 22],
      popupAnchor: [0, -26],
    });
  }

  // ── Контент попапа ────────────────────────────────────────────────────────

  function popup(loc) {
    const conf   = Math.round(loc.confidence * 100);
    const color  = conf >= 80 ? '#00e676' : conf >= 50 ? '#ffd740' : '#ff7043';
    const mins   = minsLeft(loc.expires_at);
    const badge  = TYPE_LABEL[loc.location_type] || loc.location_type;
    const warn   = mins < 15 ? ' pu-ttl-warn' : '';

    return `<div class="pu">
  <div class="pu-head">
    <span class="pu-badge">${badge}</span>
    <span class="pu-time">${relTime(loc.created_at)}</span>
  </div>
  <div class="pu-name">${esc(loc.location_name)}</div>
  <div class="pu-msg">${esc(loc.message_text)}</div>
  <div class="pu-bar"><div class="pu-fill" style="width:${conf}%;background:${color}"></div></div>
  <div class="pu-meta">
    <span>${fmtTime(loc.created_at)}</span>
    <span class="pu-ttl${warn}">${mins > 0 ? '⏱ ще ' + mins + ' хв' : '⌛ закінчується'}</span>
  </div>
</div>`;
  }

  // ── Инициализация карты ───────────────────────────────────────────────────

  function initMap() {
    map = L.map('map', {
      center: CENTER,
      zoom:   ZOOM,
      // ── Жесты (все включены) ──────────────────────────────────────────
      dragging:        true,   // перетаскивание пальцем / мышью
      touchZoom:       true,   // pinch-to-zoom двумя пальцами
      scrollWheelZoom: true,   // колёсико мыши
      doubleClickZoom: true,   // двойной тап/клик
      boxZoom:         true,   // выделение прямоугольника (десктоп)
      tap:             true,   // iOS tap events
      tapTolerance:    15,     // px — чуть больше зоны тапа
      // ── UI ────────────────────────────────────────────────────────────
      zoomControl:       false,
      attributionControl: false,
      // ── Производительность ────────────────────────────────────────────
      preferCanvas:    true,   // быстрее на слабых телефонах
      inertia:         true,   // плавное замедление после свайпа
      inertiaDeceleration: 2000,
    });

    // Тёмные тайлы CartoDB — бесплатно, без API ключа
    L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
      subdomains:     'abcd',
      maxZoom:        19,
      tileSize:       256,
      updateWhenIdle: true,   // не грузим тайлы во время движения
      keepBuffer:     1,
      crossOrigin:    true,
    }).addTo(map);

    // Зум — снизу справа (удобнее для большого пальца)
    L.control.zoom({ position: 'bottomright' }).addTo(map);

    L.control.attribution({ position: 'bottomleft', prefix: false })
      .addAttribution('© <a href="https://carto.com/">CARTO</a>')
      .addTo(map);
  }

  // ── Маркеры ───────────────────────────────────────────────────────────────

  function addMarker(loc) {
    const op = opacity(loc.created_at);
    const m  = L.marker([loc.lat, loc.lng], { icon: buildIcon(op, true), riseOnHover: true })
      .bindPopup(popup(loc), { maxWidth: 300, className: 'tcck-popup', autoPanPadding: [20, 70] })
      .addTo(map);
    markers.set(loc.id, m);
  }

  function updateMarker(loc, m) {
    m.setIcon(buildIcon(opacity(loc.created_at), false));
    const p = m.getPopup();
    if (p) {
      m.isPopupOpen() ? m.setPopupContent(popup(loc)) : p.setContent(popup(loc));
    }
  }

  function removeMarker(id) {
    const m = markers.get(id);
    if (m) { map.removeLayer(m); markers.delete(id); }
  }

  // ── Цикл обновления ───────────────────────────────────────────────────────

  async function refresh() {
    if (busy) return;
    busy = true;
    setStatus('loading');
    try {
      const locs = await API.fetchLocations();
      const ids  = new Set(locs.map(l => l.id));

      for (const id of markers.keys()) {
        if (!ids.has(id)) removeMarker(id);
      }
      for (const loc of locs) {
        if (!loc.lat || !loc.lng) continue;
        const m = markers.get(loc.id);
        m ? updateMarker(loc, m) : addMarker(loc);
      }
      setStatus(locs.length ? 'ok' : 'empty', locs.length);
    } catch (e) {
      console.error('[Map]', e);
      setStatus('error');
    } finally {
      busy = false;
    }
  }

  // ── Статус HUD ────────────────────────────────────────────────────────────

  function setStatus(state, n = 0) {
    const el = document.getElementById('status-text');
    if (!el) return;
    const MAP = {
      loading: ['⟳ Оновлення…',          'st-loading'],
      ok:      [`● ${n} ${plural(n)}`,    'st-ok'],
      empty:   ['○ Сигналів немає',       'st-empty'],
      error:   ['✕ Помилка зв\'язку',     'st-error'],
    };
    const [text, cls] = MAP[state] || MAP.empty;
    el.textContent = text;
    el.className   = cls;
  }

  // ── Поллинг ───────────────────────────────────────────────────────────────

  function startPoll() {
    stopPoll();
    pollTimer = setInterval(refresh, POLL_MS);
  }
  function stopPoll() {
    if (pollTimer !== null) { clearInterval(pollTimer); pollTimer = null; }
  }

  // ── Boot ──────────────────────────────────────────────────────────────────

  function init() {
    // Telegram Mini App: сообщаем что готовы, разворачиваем на весь экран
    if (window.Telegram?.WebApp) {
      Telegram.WebApp.ready();
      Telegram.WebApp.expand();
      // Отключаем вертикальный свайп закрытия Mini App — иначе мешает карте
      if (typeof Telegram.WebApp.disableVerticalSwipes === 'function') {
        Telegram.WebApp.disableVerticalSwipes();
      }
    }

    initMap();
    refresh().then(startPoll);

    // Пауза поллинга когда приложение скрыто (экономия батареи)
    document.addEventListener('visibilitychange', () => {
      if (document.hidden) {
        stopPoll();
      } else {
        refresh();
        startPoll();
      }
    });
  }

  return { init };
})();

document.addEventListener('DOMContentLoaded', MapApp.init);
