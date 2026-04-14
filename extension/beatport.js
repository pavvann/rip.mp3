// Downlist — Beatport content script
// Reuses the same server + CSS as the Spotify script.

const INJECTED_ATTR = "data-downlist";
const SERVER = "http://localhost:7823";

// Shared SVG icons (duplicated from content.js — no shared module in MV3 without bundler)
const ICON_DOWNLOAD = `<svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor">
  <path d="M8 1a.75.75 0 0 1 .75.75v6.69l1.97-1.97a.75.75 0 1 1 1.06 1.06L8 11.31l-3.78-3.78a.75.75 0 1 1 1.06-1.06L7.25 8.44V1.75A.75.75 0 0 1 8 1zM2 13.25A.75.75 0 0 1 2.75 12.5h10.5a.75.75 0 0 1 0 1.5H2.75A.75.75 0 0 1 2 13.25z"/>
</svg>`;
const ICON_DONE = `<svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor">
  <path d="M13.78 4.22a.75.75 0 0 1 0 1.06l-7.25 7.25a.75.75 0 0 1-1.06 0L2.22 9.28a.75.75 0 1 1 1.06-1.06L6 10.94l6.72-6.72a.75.75 0 0 1 1.06 0z"/>
</svg>`;
const ICON_ERROR = `<svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor">
  <path d="M8 1a7 7 0 1 1 0 14A7 7 0 0 1 8 1zm0 1.5a5.5 5.5 0 1 0 0 11 5.5 5.5 0 0 0 0-11zM8 4.75a.75.75 0 0 1 .75.75v3a.75.75 0 0 1-1.5 0v-3A.75.75 0 0 1 8 4.75zm0 6.5a.875.875 0 1 1 0-1.75.875.875 0 0 1 0 1.75z"/>
</svg>`;

function createButton() {
  const btn = document.createElement("button");
  btn.className = "downlist-btn dl-active";
  btn.title = "Download track";
  btn.innerHTML = ICON_DOWNLOAD;
  return btn;
}

function setButtonState(btn, state, progress = null) {
  btn.classList.remove("dl-loading", "dl-done", "dl-error");
  if (state === "loading") {
    btn.classList.add("dl-loading");
    const pct = progress !== null && progress > 0 ? `${Math.round(progress)}%` : "…";
    btn.innerHTML = `<span class="dl-pct">${pct}</span>`;
    btn.title = `Downloading ${pct}`;
  } else if (state === "done") {
    btn.classList.add("dl-done");
    btn.innerHTML = ICON_DONE;
    btn.title = "Downloaded!";
  } else if (state === "error") {
    btn.classList.add("dl-error");
    btn.innerHTML = ICON_ERROR;
    btn.title = "Download failed — click to retry";
  } else {
    btn.innerHTML = ICON_DOWNLOAD;
    btn.title = "Download track";
  }
}

function pollStatus(jobId, btn) {
  const interval = setInterval(async () => {
    try {
      const res = await fetch(`${SERVER}/status/${jobId}`);
      const data = await res.json();
      if (data.status === "done") {
        clearInterval(interval);
        setButtonState(btn, "done");
      } else if (data.status === "normalizing") {
        btn.classList.add("dl-loading");
        btn.innerHTML = `<span class="dl-pct">~</span>`;
        btn.title = "Normalizing volume…";
      } else if (data.status === "downloading") {
        setButtonState(btn, "loading", data.progress || 0);
      } else if (data.status === "error") {
        clearInterval(interval);
        setButtonState(btn, "error");
        btn.title = data.error || "Download failed";
      }
    } catch {
      clearInterval(interval);
      setButtonState(btn, "error");
      btn.title = "Server unreachable";
    }
  }, 2000);
}

async function triggerDownload(info, btn) {
  setButtonState(btn, "loading");
  try {
    const res = await fetch(`${SERVER}/download`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(info),
    });
    if (!res.ok) throw new Error(`Server error ${res.status}`);
    const data = await res.json();
    pollStatus(data.id, btn);
  } catch (err) {
    setButtonState(btn, "error");
    btn.title = err.message.includes("fetch") ? "Downlist server not running" : err.message;
  }
}

// --- Beatport track extraction ---
// Beatport's DOM uses data-testid attributes and aria-labels.
// Track rows appear in: charts, search results, release pages, artist pages.

function extractFromRow(row) {
  // Track title: data-testid="track-title" or links to /track/
  const titleEl =
    row.querySelector('[data-testid="track-title"]') ||
    row.querySelector('a[href*="/track/"]') ||
    row.querySelector('[class*="TrackTitle"]') ||
    row.querySelector('[class*="track-title"]');

  if (!titleEl) return null;
  const trackName = titleEl.textContent.trim();
  if (!trackName) return null;

  // Artist: data-testid="track-artists" or links to /artist/
  const artistEl =
    row.querySelector('[data-testid="track-artists"]') ||
    row.querySelector('[data-testid="artists"]');

  let artist = artistEl ? artistEl.textContent.trim() : "";

  if (!artist) {
    const artistLinks = row.querySelectorAll('a[href*="/artist/"]');
    artist = Array.from(artistLinks).map((a) => a.textContent.trim()).filter(Boolean).join(", ");
  }

  // Genre: Beatport shows genre as a link to /genre/
  const genreEl =
    row.querySelector('a[href*="/genre/"]') ||
    row.querySelector('[data-testid="genre"]') ||
    row.querySelector('[class*="genre" i]');
  const genre = genreEl ? genreEl.textContent.trim() : "";

  const spotify_url = "https://open.spotify.com/track/beatport-dummy";

  return { spotify_url, track_name: trackName, artist, genre };
}

// --- Inject buttons ---

function injectRows() {
  // Beatport track row selectors (covers charts, search, releases, artist pages)
  const rows = document.querySelectorAll(
    `[data-testid="tracks-table-row"]:not([${INJECTED_ATTR}]),
     [class*="TrackRow"]:not([${INJECTED_ATTR}]),
     [class*="track-row"]:not([${INJECTED_ATTR}]),
     li[class*="bucket-item"]:not([${INJECTED_ATTR}])`
  );

  rows.forEach((row) => {
    row.setAttribute(INJECTED_ATTR, "1");

    const info = extractFromRow(row);
    if (!info) return;

    const btn = createButton();
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      e.preventDefault();
      if (!btn.classList.contains("dl-done") && !btn.classList.contains("dl-loading")) {
        triggerDownload(info, btn);
      }
    });

    // Append to the last cell or the row itself
    const lastCell = row.lastElementChild;
    if (lastCell) {
      lastCell.style.display = "flex";
      lastCell.style.alignItems = "center";
      lastCell.appendChild(btn);
    } else {
      row.appendChild(btn);
    }
  });
}

// MutationObserver for Beatport's SPA
let debounce = null;
const observer = new MutationObserver(() => {
  clearTimeout(debounce);
  debounce = setTimeout(injectRows, 400);
});
observer.observe(document.body, { childList: true, subtree: true });
injectRows();
