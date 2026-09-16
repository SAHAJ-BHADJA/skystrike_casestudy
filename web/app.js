"use strict";

const form = document.getElementById("search-form");
const results = document.getElementById("results");
const banner = document.getElementById("banner");
const meta = document.getElementById("meta");
const searchBtn = form.querySelector(".search-btn");

const fmtDate = (iso) => {
  if (!iso) return "Date TBA";
  const d = new Date(iso);
  if (isNaN(d)) return "Date TBA";
  return d.toLocaleDateString(undefined, {
    weekday: "short", month: "short", day: "numeric",
    hour: "numeric", minute: "2-digit",
  });
};

const priceLabel = (ev) => {
  if (ev.is_free) return '<span class="free">Free</span>';
  if (!ev.price || ev.price.min == null) return '<span style="color:var(--muted)">Price TBA</span>';
  const cur = ev.price.currency && ev.price.currency !== "USD" ? ev.price.currency + " " : "$";
  if (ev.price.max != null && ev.price.max > ev.price.min) {
    return `${cur}${ev.price.min.toFixed(0)}–${ev.price.max.toFixed(0)}`;
  }
  return `${cur}${ev.price.min.toFixed(0)}`;
};

const esc = (s) => (s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

function eventCard(ev) {
  const chips = (ev.highlight || "")
    .split(" · ")
    .filter(Boolean)
    .map((h) => `<span class="chip">${esc(h)}</span>`)
    .join("");
  const genres = (ev.genres || [])
    .slice(0, 3)
    .map((g) => `<span class="genre-tag">${esc(g.replace(/-/g, " "))}</span>`)
    .join("");
  const img = ev.image
    ? `<img src="${esc(ev.image)}" alt="" loading="lazy" onerror="this.style.display='none'" />`
    : "";
  const freeBadge = ev.is_free ? '<span class="badge free">Free</span>' : "";
  const venueLine = [ev.venue?.name, ev.venue?.city && `${ev.venue.city}${ev.venue.region ? ", " + ev.venue.region : ""}`]
    .filter(Boolean)
    .join(" · ");

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
        ${genres ? `<div class="genres">${genres}</div>` : ""}
        <div class="foot">
          <span class="price">${priceLabel(ev)}</span>
          ${ev.url ? `<a class="tickets" href="${esc(ev.url)}" target="_blank" rel="noopener">Details ↗</a>` : ""}
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
    const payload = await resp.json();
    render(payload);
  } catch (e) {
    showState("⚠️ Could not reach the server. Is it running?");
  } finally {
    searchBtn.disabled = false;
  }
}

function render(payload) {
  if (payload.sample_data) {
    banner.hidden = false;
    banner.textContent =
      "Showing bundled sample data — set JAMBASE_API_KEY in .env for live events.";
  }

  const failed = (payload.sources || []).filter((s) => !s.ok);
  meta.hidden = false;
  meta.innerHTML =
    `<span class="pill">${payload.events.length} events · ${esc(payload.query_location)}</span>` +
    failed.map((s) => `<span class="pill err">${esc(s.source)} unavailable</span>`).join("");

  if (!payload.events.length) {
    showState("No events found for this search. Try widening the dates or removing the genre filter.");
    return;
  }
  results.innerHTML = payload.events.map(eventCard).join("");
}

form.addEventListener("submit", (e) => {
  e.preventDefault();
  search();
});

// Load an initial search so the page isn't empty on first paint.
search();
