# rip.mp3

A Chrome extension for DJs. Injects a download button on Spotify Web and Beatport — click any track to download it as a 320kbps MP3, volume-normalized to -14 LUFS with metadata and cover art embedded. Keeps a history of everything you've grabbed.

---

## How it works

```
Spotify / Beatport (browser)
  └── content script extracts track name + artist
        │
        ▼
  local server (Flask + yt-dlp)
        │  searches YouTube Music for best match
        │  downloads 320kbps MP3
        │  normalizes to -14 LUFS (ffmpeg loudnorm)
        │  embeds metadata + cover art + genre
        ▼
  ~/Music/DJ Downloads/
```

The extension talks to a lightweight local server that does the actual downloading. No data leaves your machine except to search YouTube Music.

---

## Prerequisites

- macOS (uses `open` to reveal files in Finder)
- Python 3.10+
- [ffmpeg](https://ffmpeg.org/) — `brew install ffmpeg`
- Google Chrome

---

## Setup

**1. Install Python dependencies**

```bash
cd server
bash start.sh
```

The script auto-installs `flask`, `flask-cors`, `yt-dlp`, `ytmusicapi`, `rapidfuzz`, and `mutagen` on first run, then starts the server on `localhost:7823`. Keep this terminal open.

**2. Load the Chrome extension**

1. Go to `chrome://extensions`
2. Enable **Developer mode** (toggle, top right)
3. Click **Load unpacked** → select the `extension/` folder
4. Pin the rip.mp3 icon from the extensions menu

---

## Usage

### Spotify Web (`open.spotify.com`)

Download buttons appear on every track row when you hover. There's also a button in the now-playing bar for whatever's currently playing.

### Beatport (`beatport.com`)

Download buttons appear on track rows in charts, releases, artist pages, and search results. Genre is automatically extracted from Beatport and embedded in the MP3.

### Button states

| State | Meaning |
|-------|---------|
| `⬇` | Ready to download |
| `47%` | Downloading |
| `~` | Normalizing volume |
| `✓` | Done — file saved |
| `✗` | Error — click to retry |

### Extension popup

Click the rip.mp3 icon in the Chrome toolbar to see your full download history and open the downloads folder.

---

## Output

Files land in `~/Music/DJ Downloads/` as:

```
Artist - Title.mp3
```

Every file is:
- **320 kbps MP3**
- **-14 LUFS** loudness normalized (EBU R128, `-1 dBTP` true peak) — consistent gain across your whole library
- Full ID3 metadata: title, artist, album, cover art, genre (where available)

---

## Project structure

```
rip.mp3/
├── extension/
│   ├── manifest.json       # Chrome MV3 manifest
│   ├── content.js          # Spotify injection
│   ├── beatport.js         # Beatport injection
│   ├── content.css         # Button styles
│   ├── background.js       # Service worker
│   ├── popup.html          # History UI
│   ├── popup.js            # History logic
│   ├── generate_icons.py   # Regenerate PNG icons
│   └── icons/
└── server/
    ├── server.py           # Flask API
    ├── requirements.txt
    └── start.sh            # One-command startup
```

---

## Matching algorithm

Track resolution goes through three layers:

1. **YouTube Music search** via `ytmusicapi` — structured metadata, much more accurate than generic YouTube search
2. **Fuzzy scoring** — `token_set_ratio` for title (handles "Torsion Original Mix" → "Torsion" correctly) + `partial_ratio` for artist
3. **Fallback** — `ytsearch1:` query via yt-dlp if YouTube Music search fails

---

## Troubleshooting

**Buttons not appearing on Spotify/Beatport**
→ Reload the extension at `chrome://extensions`, then hard-reload the tab (`Cmd+Shift+R`)

**Download turns red**
→ Check the server terminal for the error. Common causes: yt-dlp needs updating (`pip install -U yt-dlp`), or no YouTube Music match found

**Wrong track downloaded**
→ The server logs `Downloading: Title — Artist` — verify what it matched. YouTube Music search is generally accurate but niche tracks may need a retry
