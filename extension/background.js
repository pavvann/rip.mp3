// rip.mp3 — background service worker
// Proxies messages from content script to the local server.
// (Content scripts can fetch localhost directly in MV3 unpacked extensions,
//  but routing through background keeps CSP clean and centralises error handling.)

const SERVER = "http://localhost:7823";

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg.action === "download") {
    fetch(`${SERVER}/download`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        spotify_url: msg.spotify_url,
        track_name: msg.track_name,
        artist: msg.artist,
      }),
    })
      .then((r) => r.json())
      .then((data) => sendResponse({ ok: true, ...data }))
      .catch((err) => sendResponse({ ok: false, error: err.message }));
    return true; // keep channel open for async response
  }

  if (msg.action === "status") {
    fetch(`${SERVER}/status/${msg.id}`)
      .then((r) => r.json())
      .then((data) => sendResponse({ ok: true, ...data }))
      .catch((err) => sendResponse({ ok: false, error: err.message }));
    return true;
  }

  if (msg.action === "history") {
    fetch(`${SERVER}/history`)
      .then((r) => r.json())
      .then((data) => sendResponse({ ok: true, history: data }))
      .catch((err) => sendResponse({ ok: false, error: err.message }));
    return true;
  }

  if (msg.action === "openFolder") {
    fetch(`${SERVER}/open-folder`)
      .then(() => sendResponse({ ok: true }))
      .catch((err) => sendResponse({ ok: false, error: err.message }));
    return true;
  }
});
