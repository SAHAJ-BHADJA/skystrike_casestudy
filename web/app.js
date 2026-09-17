"use strict";

const form = document.getElementById("search-form");
const results = document.getElementById("results");
const mapEl = document.getElementById("map");
const banner = document.getElementById("banner");
const meta = document.getElementById("meta");
const searchBtn = form.querySelector(".search-btn");
const locateBtn = document.getElementById("locate-btn");
const cityInput = document.getElementById("city");
const stateInput = document.getElementById("state");
const latInput = document.getElementById("lat");
const lonInput = document.getElementById("lon");

let lastEvents = [];
let currentView = "list";
let map = null;
let markerLayer = null;

const esc = (s) => (s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

const fmtDate = (iso) => {
  if (!iso) return "Date TBA";
  const d = new Date(iso);
  if (isNaN(d)) return "Date TBA";
  return d.toLocaleDateString(undefined, {
    weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit",
  });
};

const priceLabel = (ev) => {
  if (ev.is_free) return '<span class="free">Free</span>';
  if (!ev.price || ev.price.min == null) return '<span style="color:var(--muted)">Price TBA</span>';
  const cur = ev.price.currency && ev.price.currency !== "USD" ? ev.price.currency + " " : "$";
  if (ev.price.max != null && ev.price.max > ev.price.min) return `${cur}${ev.price.min.toFixed(0)}–${ev.price.max.toFixed(0)}`;
  return `${cur}${ev.price.min.toFixed(0)}`;
};

function eventCard(ev) {
  const chips = (ev.highlight || "").split(" · ").filter(Boolean).map((h) => `<span class="chip">${esc(h)}</span>`).join("");
  const genres = (ev.genres || []).slice(0, 3).map((g) => `<span class="genre-tag">${esc(g.replace(/-/g, " "))}</span>`).join("");
  const artists = (ev.performers || [])
    .filter((p) => p.url)
    .slice(0, 3)
    .map((p) => `<a class="artist" href="${esc(p.url)}" target="_blank" rel="noopener">♪ ${esc(p.name)}</a>`)
    .join("");
  const img = ev.image ? `<img src="${esc(ev.image)}" alt="" loading="lazy" onerror="this.style.display='none'" />` : "";
  const freeBadge = ev.is_free ? '<span class="badge free">Free</span>' : "";
  const venueLine = [ev.venue?.name, ev.venue?.city && `${ev.venue.city}${ev.venue.region ? ", " + ev.venue.region : ""}`].filter(Boolean).join(" · ");
  const icsUrl = `/api/events/calendar.ics?id=${encodeURIComponent(ev.id)}`;

  return `
    <article class="card">
      <div class="thumb">
        ${img}
        ${freeBadge}
        <span class="badge date">${esc(fmtDate(ev.start_local))}</span>
      </div>
      <div class="body">
        <h3>${esc(ev.title)}</h3>
        <div class="venue">${esc(venueLine)}</div>
        ${chips ? `<div class="highlight">${chips}</div>` : ""}
        ${artists ? `<div class="artists">${artists}</div>` : ""}
        ${genres ? `<div class="genres">${genres}</div>` : ""}
        <div class="foot">
          <span class="price">${priceLabel(ev)}</span>
          <span class="actions">
            <a class="cal" href="${icsUrl}" title="Add to calendar">＋ Calendar</a>
            ${ev.url ? `<a class="tickets" href="${esc(ev.url)}" target="_blank" rel="noopener">Details ↗</a>` : ""}
          </span>
        </div>
      </div>
    </article>`;
}

function showState(html) {
  results.innerHTML = `<div class="state">${html}</div>`;
}

async function search() {
  const data = new FormData(form);
  const params = new URLSearchParams();
  for (const [k, v] of data.entries()) {
    if (v && String(v).trim()) params.set(k, String(v).trim());
  }
  // When searching by coordinates, don't also send a stale city.
  if (params.get("lat") && params.get("lon")) {
    params.delete("city");
    params.delete("state");
  }

  searchBtn.disabled = true;
  banner.hidden = true;
  meta.hidden = true;
  showState('<div class="spinner"></div>Searching for events…');

  try {
    const resp = await fetch(`/api/events?${params.toString()}`);
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({}));
      showState(`⚠️ ${esc(err.detail || "Something went wrong. Try a different search.")}`);
      return;
    }
    render(await resp.json());
  } catch (e) {
    showState("⚠️ Could not reach the server. Is it running?");
  } finally {
    searchBtn.disabled = false;
  }
}

function render(payload) {
  lastEvents = payload.events || [];

  if (payload.sample_data) {
    banner.hidden = false;
    banner.textContent = "Showing bundled sample data — set JAMBASE_API_KEY in .env for live events.";
  }

  const failed = (payload.sources || []).filter((s) => !s.ok);
  meta.hidden = false;
  meta.innerHTML =
    `<span class="pill">${lastEvents.length} events · ${esc(payload.query_location)}</span>` +
    failed.map((s) => `<span class="pill err">${esc(s.source)} unavailable</span>`).join("");

  if (!lastEvents.length) {
    showState("No events found. Try widening the dates, raising the price, or removing filters.");
    mapEl.innerHTML = "";
    return;
  }

  results.innerHTML = lastEvents.map(eventCard).join("");
  if (currentView === "map") renderMap();
}

function renderMap() {
  const located = lastEvents.filter((e) => e.venue && e.venue.geo);
  if (!located.length) {
    mapEl.innerHTML = '<div class="state">No mappable venues for this search.</div>';
    return;
  }
  if (!map) {
    map = L.map(mapEl, { scrollWheelZoom: false });
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      attribution: "© OpenStreetMap", maxZoom: 18,
    }).addTo(map);
    markerLayer = L.layerGroup().addTo(map);
  }
  markerLayer.clearLayers();
  const pts = [];
  located.forEach((e) => {
    const { latitude, longitude } = e.venue.geo;
    pts.push([latitude, longitude]);
    L.marker([latitude, longitude])
      .addTo(markerLayer)
      .bindPopup(
        `<strong>${esc(e.title)}</strong><br>${esc(e.venue.name || "")}<br>` +
        `${esc(fmtDate(e.start_local))}<br>${priceLabel(e)}`
      );
  });
  map.fitBounds(pts, { padding: [40, 40], maxZoom: 14 });
  setTimeout(() => map.invalidateSize(), 50);
}

function setView(view) {
  currentView = view;
  document.querySelectorAll(".toggle").forEach((b) => b.classList.toggle("active", b.dataset.view === view));
  const isMap = view === "map";
  results.hidden = isMap;
  mapEl.hidden = !isMap;
  if (isMap) renderMap();
}

// --- events ---
document.querySelectorAll(".view-toggle .toggle").forEach((btn) => {
  btn.addEventListener("click", () => setView(btn.dataset.view));
});

locateBtn.addEventListener("click", () => {
  if (!navigator.geolocation) {
    alert("Geolocation isn't available in this browser.");
    return;
  }
  locateBtn.disabled = true;
  locateBtn.textContent = "📍 Locating…";
  navigator.geolocation.getCurrentPosition(
    (pos) => {
      latInput.value = pos.coords.latitude.toFixed(5);
      lonInput.value = pos.coords.longitude.toFixed(5);
      cityInput.value = "";
      stateInput.value = "";
      cityInput.placeholder = "📍 Near you";
      locateBtn.disabled = false;
      locateBtn.textContent = "📍 Use my location";
      search();
    },
    () => {
      alert("Couldn't get your location. Enter a city instead.");
      locateBtn.disabled = false;
      locateBtn.textContent = "📍 Use my location";
    },
    { timeout: 8000 }
  );
});

// Typing a city invalidates a previously captured GPS fix.
[cityInput, stateInput].forEach((el) =>
  el.addEventListener("input", () => {
    latInput.value = "";
    lonInput.value = "";
  })
);

form.addEventListener("submit", (e) => {
  e.preventDefault();
  search();
});

search();
