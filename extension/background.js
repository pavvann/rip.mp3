// rip.mp3 — background service worker
// Proxies messages from content script to the local server.

const DEFAULT_SERVER = "http://localhost:7823";

async function getConfig() {
  const { ripServer = DEFAULT_SERVER, ripSecret = "" } = await chrome.storage.sync.get(["ripServer", "ripSecret"]);
  return { server: ripServer, secret: ripSecret };
}

function authHeaders(secret) {
  const h = { "Content-Type": "application/json" };
  if (secret) h["X-Rip-Secret"] = secret;
  return h;
}

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg.action === "download") {
    getConfig().then(({ server, secret }) =>
      fetch(`${server}/download`, {
        method: "POST",
        headers: authHeaders(secret),
        body: JSON.stringify({
          spotify_url: msg.spotify_url,
          track_name: msg.track_name,
          artist: msg.artist,
        }),
      })
        .then((r) => r.json())
        .then((data) => sendResponse({ ok: true, ...data }))
        .catch((err) => sendResponse({ ok: false, error: err.message }))
    );
    return true;
  }

  if (msg.action === "status") {
    getConfig().then(({ server, secret }) =>
      fetch(`${server}/status/${msg.id}`, { headers: authHeaders(secret) })
        .then((r) => r.json())
        .then((data) => sendResponse({ ok: true, ...data }))
        .catch((err) => sendResponse({ ok: false, error: err.message }))
    );
    return true;
  }

  if (msg.action === "history") {
    getConfig().then(({ server, secret }) =>
      fetch(`${server}/history`, { headers: authHeaders(secret) })
        .then((r) => r.json())
        .then((data) => sendResponse({ ok: true, history: data }))
        .catch((err) => sendResponse({ ok: false, error: err.message }))
    );
    return true;
  }

  if (msg.action === "openFolder") {
    getConfig().then(({ server, secret }) =>
      fetch(`${server}/open-folder`, { headers: authHeaders(secret) })
        .then(() => sendResponse({ ok: true }))
        .catch((err) => sendResponse({ ok: false, error: err.message }))
    );
    return true;
  }
});
