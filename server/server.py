import json
import os
import subprocess
import threading
import uuid
from datetime import datetime
from functools import wraps
from pathlib import Path

import yt_dlp
from flask import Flask, after_this_request, jsonify, request, send_file
from flask_cors import CORS
from mutagen.id3 import ID3, TCON, error as ID3Error
from rapidfuzz import fuzz
from ytmusicapi import YTMusic

ytmusic = YTMusic()
app = Flask(__name__)
CORS(app, origins=["chrome-extension://*", "http://localhost:*", "https://open.spotify.com", "https://www.beatport.com"])

API_SECRET = os.environ.get("RIPMP3_SECRET", "")

def require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if API_SECRET:
            token = request.headers.get("X-Rip-Secret") or request.args.get("secret")
            if token != API_SECRET:
                return jsonify({"error": "Unauthorized"}), 401
        return f(*args, **kwargs)
    return decorated

DOWNLOADS_DIR = Path(os.environ.get("RIPMP3_DOWNLOADS", Path.home() / "Music" / "DJ Downloads"))
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

def find_youtube_url(track_name, artist):
    """Search YouTube Music, score all results, return best match URL."""
    primary_artist = artist.split(",")[0].strip()
    artist_known = primary_artist.lower() not in UNKNOWN_ARTIST_PLACEHOLDERS

    search_query = f"{track_name} {primary_artist}" if artist_known else track_name
    try:
        results = ytmusic.search(search_query, filter="songs", limit=10)
        best_url, best_score = None, -1
        for r in results:
            if not r.get("videoId"):
                continue
            r_title = r.get("title", "")
            r_artists = ", ".join(a["name"] for a in r.get("artists", []))

            title_score = fuzz.token_set_ratio(track_name.lower(), r_title.lower())
            remix_penalty = 10 if any(w in r_title.lower() for w in ["cover", "remix", "karaoke", "tribute"]) else 0

            if artist_known:
                artist_score = fuzz.partial_ratio(primary_artist.lower(), r_artists.lower())
                score = (title_score * 0.55 + artist_score * 0.45) - remix_penalty
            else:
                score = title_score - remix_penalty

            if score > best_score:
                best_score = score
                best_url = f"https://music.youtube.com/watch?v={r['videoId']}"

        if best_url and best_score >= 40:
            return best_url
    except Exception as e:
        print(f"YTMusic search failed: {e}, falling back to ytsearch")

    # Fallback
    fallback_query = f"{track_name} {primary_artist}" if artist_known else track_name
    return f"ytsearch1:{fallback_query} official audio"


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


def run_download(job_id, track_name, artist, genre=""):
    jobs[job_id]["status"] = "downloading"
    jobs[job_id]["progress"] = 0

    url = find_youtube_url(track_name, artist)
    print(f"Downloading: {track_name} — {artist}")
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

    ydl_opts = {
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
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
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
            "downloaded_at": datetime.utcnow().isoformat() + "Z",
        })

    except Exception as e:
        jobs[job_id]["status"] = "error"
        jobs[job_id]["error"] = str(e)


@app.route("/download", methods=["POST"])
@require_auth
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
@require_auth
def status(job_id):
    job = jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    return jsonify({"id": job_id, **job})


@app.route("/history")
@require_auth
def history():
    return jsonify(load_history())


@app.route("/file/<job_id>")
@require_auth
def download_file(job_id):
    job = jobs.get(job_id)
    if not job or job["status"] != "done":
        return jsonify({"error": "File not ready"}), 404
    file_path = job.get("file_path")
    if not file_path or not os.path.exists(file_path):
        return jsonify({"error": "File not found"}), 404

    @after_this_request
    def cleanup(response):
        try:
            os.remove(file_path)
            jobs.pop(job_id, None)
            print(f"Cleaned up: {file_path}")
        except Exception as e:
            print(f"Cleanup failed: {e}")
        return response

    return send_file(file_path, as_attachment=True, mimetype="audio/mpeg")


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
    ssl_cert = os.environ.get("RIPMP3_CERT")
    ssl_key = os.environ.get("RIPMP3_KEY")
    ssl_ctx = (ssl_cert, ssl_key) if ssl_cert and ssl_key else None
    host = "0.0.0.0"
    scheme = "https" if ssl_ctx else "http"
    print(f"rip.mp3 server running on {scheme}://{host}:7823")
    print(f"Downloads folder: {DOWNLOADS_DIR}")
    app.run(host=host, port=7823, ssl_context=ssl_ctx, debug=False)
