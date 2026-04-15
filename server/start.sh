#!/bin/bash
set -e

cd "$(dirname "$0")"

# Check for ffmpeg
if ! command -v ffmpeg &>/dev/null; then
  echo "Error: ffmpeg not found. Install it with: brew install ffmpeg"
  exit 1
fi

# Find a Python 3 with pip available
PYTHON=""
for candidate in python3 python3.11 python3.10 python3.12; do
  if command -v "$candidate" &>/dev/null; then
    PYTHON="$candidate"
    break
  fi
done

if [ -z "$PYTHON" ]; then
  echo "Error: Python 3 not found."
  exit 1
fi

echo "Using $($PYTHON --version)"
$PYTHON -m pip install -r requirements.txt -q

echo "Starting rip.mp3 server..."
$PYTHON server.py
