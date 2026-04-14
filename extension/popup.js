const SERVER = "http://localhost:7823";

const trackList = document.getElementById("track-list");
const emptyState = document.getElementById("empty-state");
const statusBar = document.getElementById("status-bar");
const countLabel = document.getElementById("count-label");
const openFolderBtn = document.getElementById("open-folder-btn");

function formatDate(iso) {
  const d = new Date(iso);
  const now = new Date();
  const diffMs = now - d;
  const diffMin = Math.floor(diffMs / 60000);
  const diffHr = Math.floor(diffMin / 60);
  const diffDay = Math.floor(diffHr / 24);

  if (diffMin < 1) return "just now";
  if (diffMin < 60) return `${diffMin}m ago`;
  if (diffHr < 24) return `${diffHr}h ago`;
  if (diffDay < 7) return `${diffDay}d ago`;
  return d.toLocaleDateString();
}

function renderHistory(history) {
  // Remove existing track items (keep empty state)
  trackList.querySelectorAll(".track-item").forEach((el) => el.remove());

  if (!history || history.length === 0) {
    emptyState.style.display = "block";
    countLabel.textContent = "0 tracks downloaded";
    return;
  }

  emptyState.style.display = "none";
  countLabel.textContent = `${history.length} track${history.length === 1 ? "" : "s"} downloaded`;

  history.forEach((entry) => {
    const item = document.createElement("div");
    item.className = "track-item";
    item.innerHTML = `
      <div class="track-check">
        <svg width="10" height="10" viewBox="0 0 16 16" fill="white">
          <path d="M13.78 4.22a.75.75 0 0 1 0 1.06l-7.25 7.25a.75.75 0 0 1-1.06 0L2.22 9.28a.75.75 0 1 1 1.06-1.06L6 10.94l6.72-6.72a.75.75 0 0 1 1.06 0z"/>
        </svg>
      </div>
      <div class="track-info">
        <div class="track-name">${escHtml(entry.track_name)}</div>
        <div class="track-meta">${escHtml(entry.artist)}</div>
      </div>
      <div class="track-date">${formatDate(entry.downloaded_at)}</div>
    `;
    trackList.appendChild(item);
  });
}

function escHtml(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

async function loadHistory() {
  try {
    const res = await fetch(`${SERVER}/history`, { signal: AbortSignal.timeout(3000) });
    if (!res.ok) throw new Error("Server error");
    const history = await res.json();

    statusBar.className = "online";
    statusBar.textContent = "Server running";

    renderHistory(history);
  } catch {
    statusBar.className = "offline";
    statusBar.textContent = "Downlist server not running — start it with: cd server && bash start.sh";
    emptyState.style.display = "block";
    emptyState.innerHTML = `<strong>Server offline</strong>Start the server to use Downlist`;
  }
}

openFolderBtn.addEventListener("click", async () => {
  try {
    await fetch(`${SERVER}/open-folder`, { signal: AbortSignal.timeout(3000) });
  } catch {
    // ignore
  }
});

loadHistory();
