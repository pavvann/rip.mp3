import json
import os
import re
import subprocess
import threading
import unicodedata
import uuid
from datetime import datetime
from pathlib import Path

import yt_dlp
from flask import Flask, jsonify, request
from flask_cors import CORS
from mutagen.id3 import ID3, TCON, error as ID3Error
from rapidfuzz import fuzz
from ytmusicapi import YTMusic

ytmusic = YTMusic()
app = Flask(__name__)
CORS(app, origins=["chrome-extension://*", "http://localhost:*", "https://open.spotify.com", "https://www.beatport.com"])

DOWNLOADS_DIR = Path.home() / "Music" / "DJ Downloads"
HISTORY_FILE = Path.home() / ".ripmp3_history.json"

jobs = {}


def ensure_dirs():
    DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)


def load_history():
    if HISTORY_FILE.exists():
        with open(HISTORY_FILE) as f:
            return json.load(f)
    return []


def save_history(entry):
    history = load_history()
    history.insert(0, entry)
    with open(HISTORY_FILE, "w") as f:
        json.dump(history, f, indent=2)


UNKNOWN_ARTIST_PLACEHOLDERS = {"unknown artist", "unknown", ""}

# Beatport and Spotify tack these onto titles; they describe the same recording,
# so they must not count against a match.
NEUTRAL_MIX_TERMS = (
    "original mix", "extended mix", "extended version", "extended",
    "radio edit", "radio mix", "club mix", "original version",
    "vocal mix", "instrumental mix", "full version", "remastered", "remaster",
    "original",
)
# These DO mean a different recording — only penalise when we didn't ask for one.
ALT_VERSION_WORDS = ("cover", "remix", "karaoke", "tribute", "bootleg", "mashup", "live")
FEATURED_RE = re.compile(r"\((?:feat|ft|featuring)\.?[^)]*\)|\b(?:feat|ft|featuring)\.?\s.*$")
# NFKD leaves these alone because they are distinct letters rather than accented
# forms, so the punctuation strip would silently delete them ('TØDV' -> 't dv').
TRANSLITERATIONS = str.maketrans({
    "ø": "o", "æ": "ae", "œ": "oe", "ð": "d", "þ": "th", "ß": "ss",
    "ł": "l", "đ": "d", "ħ": "h", "ı": "i", "ŋ": "n", "ĸ": "k", "å": "a",
})
MIN_MATCH_SCORE = 55


def normalize_for_match(text):
    """Fold case, accents and punctuation so 'OTAK' == 'ÖTAK' and 'O.B.I.' == 'obi'."""
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = FEATURED_RE.sub(" ", text.lower()).translate(TRANSLITERATIONS)
    text = " ".join(re.sub(r"[^a-z0-9]+", " ", text).split())
    trimmed = True
    while trimmed:
        trimmed = False
        for term in NEUTRAL_MIX_TERMS:
            if text.endswith(f" {term}"):
                text = text[: -len(term) - 1].strip()
                trimmed = True
    return text


def title_similarity(query, candidate):
    """0-100: exact beats leading phrase beats contiguous beats scattered tokens."""
    q, c = normalize_for_match(query), normalize_for_match(candidate)
    if not q or not c:
        return 0.0
    if q == c:
        return 100.0
    # token_set_ratio on its own returns 100 for any title that merely contains the
    # query's tokens, which tied 'The Sound Of Hardtechno' with 'Sound of the Sioux'.
    blend = (0.35 * fuzz.token_set_ratio(q, c)
             + 0.40 * fuzz.token_sort_ratio(q, c)
             + 0.25 * fuzz.ratio(q, c))
    if c.startswith(f"{q} "):
        return max(blend, 85.0)
    if q in c:
        return max(blend, 75.0)
    return blend


def artist_similarity(query, candidate):
    """0-100. token_set tolerates YouTube crediting extra collaborators."""
    q, c = normalize_for_match(query), normalize_for_match(candidate)
    if not q or not c:
        return 0.0
    # partial_ratio is far too loose here: it scored 'mirko meex' vs 'mirage' at 67.
    return float(max(fuzz.token_set_ratio(q, c), fuzz.token_sort_ratio(q, c)))


def find_youtube_url(track_name, artist):
    """Search YouTube Music, score all results, return (url, match_info)."""
    primary_artist = artist.split(",")[0].strip()
    artist_known = primary_artist.lower() not in UNKNOWN_ARTIST_PLACEHOLDERS

    search_query = f"{track_name} {primary_artist}" if artist_known else track_name
    query_norm = normalize_for_match(track_name)
    try:
        results = ytmusic.search(search_query, filter="songs", limit=10)
        best = None
        for position, r in enumerate(results):
            if not r.get("videoId"):
                continue
            r_title = r.get("title", "")
            r_artists = ", ".join(a["name"] for a in r.get("artists", []))

            title_score = title_similarity(track_name, r_title)
            candidate_norm = normalize_for_match(r_title)
            penalty = 25.0 if any(
                w in candidate_norm and w not in query_norm for w in ALT_VERSION_WORDS
            ) else 0.0

            if artist_known:
                # Score against every credited artist, not just the primary: Beatport
                # lists 'Grüv, Kuss' where YouTube credits only 'KUSS'.
                artist_score = artist_similarity(artist, r_artists)
                score = title_score * 0.60 + artist_score * 0.40 - penalty
            else:
                score = title_score - penalty

            # Break ties on title length then result order, so the pick is stable.
            # The old code let YTMusic's ordering silently decide between equals.
            rank = (-score, abs(len(candidate_norm) - len(query_norm)), position)
            if best is None or rank < best[0]:
                best = (rank, r["videoId"], r_title, r_artists, score)

        if best and best[4] >= MIN_MATCH_SCORE:
            _, video_id, r_title, r_artists, score = best
            return f"https://music.youtube.com/watch?v={video_id}", {
                "title": r_title,
                "artists": r_artists,
                "score": round(score, 1),
            }
        if best:
            print(f"Weak match rejected ({best[4]:.0f} < {MIN_MATCH_SCORE}): {best[2]} — {best[3]}")
    except Exception as e:
        print(f"YTMusic search failed: {e}, falling back to ytsearch")

    # Fallback
    fallback_query = f"{track_name} {primary_artist}" if artist_known else track_name
    return f"ytsearch1:{fallback_query} official audio", None


def embed_genre(file_path, genre):
    if not genre or not os.path.exists(file_path):
        return
    try:
        audio = ID3(file_path)
        audio["TCON"] = TCON(encoding=3, text=[genre])
        audio.save()
        print(f"Genre set: {genre}")
    except ID3Error as e:
        print(f"Genre embed failed: {e}")


def normalize_audio(file_path, job_id):
    """Normalize to -14 LUFS / -1 dBTP true peak (DJ standard) using ffmpeg loudnorm."""
    tmp_path = file_path + ".norm.mp3"
    try:
        result = subprocess.run([
            "ffmpeg", "-i", file_path,
            "-af", "loudnorm=I=-14:TP=-1:LRA=11:linear=true",
            "-b:a", "320k",
            "-y", tmp_path
        ], capture_output=True, text=True)
        if result.returncode == 0:
            os.replace(tmp_path, file_path)
            print(f"Normalized: {file_path}")
        else:
            print(f"Normalization failed: {result.stderr[-300:]}")
    except Exception as e:
        print(f"Normalization error: {e}")
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


# YouTube gates its media URLs (GVS) behind PO tokens on most player clients and
# serves SABR-only URLs to the plain web clients. web_embedded needs neither a PO
# token nor a JS challenge solver and handles both normal uploads and the
# auto-generated "art tracks" that YouTube Music search returns, so it leads.
# The rest cover its blind spots: web_music for art tracks when embedding is
# disabled, tv_downgraded for normal uploads, then yt-dlp's own defaults.
YOUTUBE_CLIENT_CHAIN = (
    ("web_embedded",),
    ("web_music",),
    ("tv_downgraded",),
    ("web_safari",),
    (),
)


def build_ydl_opts(output_template, progress_hook, player_clients):
    opts = {
        "format": "bestaudio/best",
        "outtmpl": output_template,
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "320",
            },
            {"key": "FFmpegMetadata"},
            {"key": "EmbedThumbnail"},
        ],
        "writethumbnail": True,
        "progress_hooks": [progress_hook],
        "quiet": True,
        "no_warnings": True,
        "default_search": "ytsearch",
        # Lets yt-dlp fetch its JS challenge solver. Without it YouTube extraction
        # dies with "The page needs to be reloaded".
        "remote_components": ["ejs:github"],
    }
    if player_clients:
        opts["extractor_args"] = {"youtube": {"player_client": list(player_clients)}}
    return opts


def extract_with_fallback(url, output_template, progress_hook, actual_file, job_id):
    """Download via the first client in YOUTUBE_CLIENT_CHAIN that YouTube allows."""
    last_error = None
    for clients in YOUTUBE_CLIENT_CHAIN:
        label = ",".join(clients) if clients else "default"
        actual_file[0] = None
        jobs[job_id]["progress"] = 0
        try:
            opts = build_ydl_opts(output_template, progress_hook, clients)
            with yt_dlp.YoutubeDL(opts) as ydl:
                return ydl.extract_info(url, download=True)
        except Exception as e:
            last_error = e
            print(f"Player client {label} failed: {e}")
    raise last_error


def run_download(job_id, track_name, artist, genre=""):
    jobs[job_id]["status"] = "downloading"
    jobs[job_id]["progress"] = 0

    url, matched = find_youtube_url(track_name, artist)
    print(f"Downloading: {track_name} — {artist}")
    if matched:
        print(f"  matched: {matched['title']} — {matched['artists']} (score {matched['score']})")
    else:
        print("  no confident YouTube Music match; falling back to YouTube search")
    output_template = str(DOWNLOADS_DIR / "%(artist)s - %(title)s.%(ext)s")

    actual_file = [None]

    def progress_hook(d):
        if d["status"] == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            downloaded = d.get("downloaded_bytes", 0)
            if total:
                jobs[job_id]["progress"] = round(downloaded / total * 100, 1)
        elif d["status"] == "finished":
            actual_file[0] = d.get("filename")
            jobs[job_id]["progress"] = 99  # converting…

    try:
        info = extract_with_fallback(url, output_template, progress_hook, actual_file, job_id)
        # Grab the actual downloaded filename
        if info and "entries" in info:
            info = info["entries"][0]

        # Derive mp3 path from the actual downloaded file (pre-postprocessor)
        if actual_file[0]:
            base = os.path.splitext(actual_file[0])[0]
            file_path = base + ".mp3"
            if not os.path.exists(file_path):
                # yt-dlp may have sanitised the filename — find newest mp3 in dir
                mp3s = sorted(DOWNLOADS_DIR.glob("*.mp3"), key=os.path.getmtime, reverse=True)
                file_path = str(mp3s[0]) if mp3s else str(DOWNLOADS_DIR)
        else:
            mp3s = sorted(DOWNLOADS_DIR.glob("*.mp3"), key=os.path.getmtime, reverse=True)
            file_path = str(mp3s[0]) if mp3s else str(DOWNLOADS_DIR)

        jobs[job_id]["status"] = "normalizing"
        jobs[job_id]["progress"] = 100
        normalize_audio(file_path, job_id)
        embed_genre(file_path, genre)

        jobs[job_id]["status"] = "done"
        jobs[job_id]["file_path"] = file_path

        save_history({
            "id": job_id,
            "track_name": track_name,
            "artist": artist,
            "file_path": file_path,
            "matched_title": matched["title"] if matched else None,
            "matched_artist": matched["artists"] if matched else None,
            "match_score": matched["score"] if matched else None,
            "downloaded_at": datetime.utcnow().isoformat() + "Z",
        })

    except Exception as e:
        jobs[job_id]["status"] = "error"
        jobs[job_id]["error"] = str(e)


@app.route("/download", methods=["POST"])
def download():
    ensure_dirs()
    data = request.get_json(force=True)
    spotify_url = (data.get("spotify_url") or data.get("spotifyUrl") or "").strip()
    track_name = data.get("track_name") or data.get("trackName") or "Unknown Track"
    artist = data.get("artist") or "Unknown Artist"
    genre = data.get("genre") or ""

    if not track_name or track_name == "Unknown Track":
        return jsonify({"error": "Could not extract track name"}), 400

    job_id = str(uuid.uuid4())
    jobs[job_id] = {"status": "queued", "progress": 0, "file_path": None, "error": None}

    thread = threading.Thread(
        target=run_download,
        args=(job_id, track_name, artist, genre),
        daemon=True,
    )
    thread.start()

    return jsonify({"id": job_id, "status": "queued"})


@app.route("/status/<job_id>")
def status(job_id):
    job = jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    return jsonify({"id": job_id, **job})


@app.route("/history")
def history():
    return jsonify(load_history())


@app.route("/open-folder")
def open_folder():
    ensure_dirs()
    subprocess.Popen(["open", str(DOWNLOADS_DIR)])
    return jsonify({"ok": True})


@app.route("/ping")
def ping():
    return jsonify({"ok": True})


if __name__ == "__main__":
    ensure_dirs()
    print(f"rip.mp3 server running on http://localhost:7823")
    print(f"Downloads folder: {DOWNLOADS_DIR}")
    app.run(host="localhost", port=7823, debug=False)
