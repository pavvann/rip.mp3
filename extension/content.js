// Downlist — content script for open.spotify.com
// Injects download buttons into track rows and the now-playing bar.

const INJECTED_ATTR = "data-downlist";
const SERVER = "http://localhost:7823";

// SVG icons
const ICON_DOWNLOAD = `<svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor">
  <path d="M8 1a.75.75 0 0 1 .75.75v6.69l1.97-1.97a.75.75 0 1 1 1.06 1.06L8 11.31l-3.78-3.78a.75.75 0 1 1 1.06-1.06L7.25 8.44V1.75A.75.75 0 0 1 8 1zM2 13.25A.75.75 0 0 1 2.75 12.5h10.5a.75.75 0 0 1 0 1.5H2.75A.75.75 0 0 1 2 13.25z"/>
</svg>`;

const ICON_DONE = `<svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor">
  <path d="M13.78 4.22a.75.75 0 0 1 0 1.06l-7.25 7.25a.75.75 0 0 1-1.06 0L2.22 9.28a.75.75 0 1 1 1.06-1.06L6 10.94l6.72-6.72a.75.75 0 0 1 1.06 0z"/>
</svg>`;

const ICON_ERROR = `<svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor">
  <path d="M8 1a7 7 0 1 1 0 14A7 7 0 0 1 8 1zm0 1.5a5.5 5.5 0 1 0 0 11 5.5 5.5 0 0 0 0-11zM8 4.75a.75.75 0 0 1 .75.75v3a.75.75 0 0 1-1.5 0v-3A.75.75 0 0 1 8 4.75zm0 6.5a.875.875 0 1 1 0-1.75.875.875 0 0 1 0 1.75z"/>
</svg>`;

function createButton(extraClass = "") {
  const btn = document.createElement("button");
  btn.className = `downlist-btn dl-active ${extraClass}`;
  btn.title = "Download track";
  btn.innerHTML = ICON_DOWNLOAD;
  return btn;
}

function setButtonState(btn, state, progress = null) {
  btn.classList.remove("dl-loading", "dl-done", "dl-error");
  if (state === "loading") {
    btn.classList.add("dl-loading");
    const pct = (progress !== null && progress > 0) ? `${Math.round(progress)}%` : "…";
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

function extractTrackInfoFromRow(row) {
  // Track link: <a href="/track/XXXX">
  const link = row.querySelector('a[href*="/track/"]');
  if (!link) return null;

  const href = link.getAttribute("href");
  const match = href.match(/\/track\/([A-Za-z0-9]+)/);
  if (!match) return null;

  const trackId = match[1];
  const spotifyUrl = `https://open.spotify.com/track/${trackId}`;

  // Track name: the text of the track link itself
  const trackName = link.textContent.trim() || "Unknown Track";

  // Artist: look for artist links (href contains /artist/)
  const artist = extractArtist(row);

  // Genre: not available in Spotify track rows — leave empty, server won't overwrite
  return { spotify_url: spotifyUrl, track_name: trackName, artist, genre: "" };
}

function extractArtist(container) {
  // Most reliable: play button aria-label is always "Play {title} by {artist(s)}"
  const playBtn = container.querySelector('button[aria-label^="Play "]');
  if (playBtn) {
    const label = playBtn.getAttribute("aria-label"); // "Play Indigo by Disguised"
    const match = label.match(/^Play .+ by (.+)$/i);
    if (match) return match[1].trim();
  }

  // Fallback: explicit artist page links
  const artistLinks = container.querySelectorAll('a[href*="/artist/"]');
  const fromLinks = Array.from(artistLinks)
    .map((a) => a.textContent.trim())
    .filter(Boolean)
    .join(", ");
  if (fromLinks) return fromLinks;

  return "";
}

function extractTrackInfoFromNowPlaying(widget) {
  const link = widget.querySelector('a[href*="/track/"]');
  if (!link) return null;

  const href = link.getAttribute("href");
  const match = href.match(/\/track\/([A-Za-z0-9]+)/);
  if (!match) return null;

  const trackId = match[1];
  const spotifyUrl = `https://open.spotify.com/track/${trackId}`;
  const trackName = link.textContent.trim() || "Unknown Track";
  const artist = extractArtist(widget);

  return { spotify_url: spotifyUrl, track_name: trackName, artist };
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

// --- Inject into tracklist rows ---

function injectTrackRows() {
  const rows = document.querySelectorAll(
    `[data-testid="tracklist-row"]:not([${INJECTED_ATTR}])`
  );

  rows.forEach((row) => {
    row.setAttribute(INJECTED_ATTR, "1");

    const info = extractTrackInfoFromRow(row);
    if (!info) return;

    const btn = createButton();
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      e.preventDefault();
      if (!btn.classList.contains("dl-done") && !btn.classList.contains("dl-loading")) {
        triggerDownload(info, btn);
      }
    });

    // Find the duration/last cell to append next to
    const lastCell = row.querySelector('[aria-colindex="5"], [aria-colindex="4"]') || row.lastElementChild;
    if (lastCell) {
      lastCell.style.display = "flex";
      lastCell.style.alignItems = "center";
      lastCell.appendChild(btn);
    } else {
      row.appendChild(btn);
    }
  });
}

// --- Inject into now-playing bar ---

let lastNowPlayingUrl = null;

function injectNowPlaying() {
  const widget = document.querySelector('[data-testid="now-playing-widget"]');
  if (!widget) return;

  const info = extractTrackInfoFromNowPlaying(widget);
  if (!info) return;

  // Only update if the track changed
  if (info.spotify_url === lastNowPlayingUrl) return;
  lastNowPlayingUrl = info.spotify_url;

  // Remove any old button
  const old = widget.querySelector(".downlist-nowplaying-btn");
  if (old) old.remove();

  const btn = createButton("downlist-nowplaying-btn");
  btn.addEventListener("click", (e) => {
    e.stopPropagation();
    e.preventDefault();
    if (!btn.classList.contains("dl-done") && !btn.classList.contains("dl-loading")) {
      triggerDownload(info, btn);
    }
  });

  widget.appendChild(btn);
}

// --- MutationObserver ---

let debounceTimer = null;

const observer = new MutationObserver(() => {
  clearTimeout(debounceTimer);
  debounceTimer = setTimeout(() => {
    injectTrackRows();
    injectNowPlaying();
  }, 300);
});

observer.observe(document.body, { childList: true, subtree: true });

// Initial pass
injectTrackRows();
injectNowPlaying();
