#!/bin/bash
set -e

cd "$(dirname "$0")"

# Check for ffmpeg
if ! command -v ffmpeg &>/dev/null; then
  echo "Error: ffmpeg not found. Install it with: brew install ffmpeg"
  exit 1
fi

# Use venv if it exists, otherwise fall back to system python
if [ -f "venv/bin/python" ]; then
  PYTHON="venv/bin/python"
  PIP="venv/bin/pip"
else
  PYTHON=$(command -v python3 || command -v python)
  PIP="$PYTHON -m pip"
  if [ -z "$PYTHON" ]; then
    echo "Error: Python 3 not found."
    exit 1
  fi
fi

echo "Using $($PYTHON --version)"
$PIP install -r requirements.txt -q

echo "Starting rip.mp3 server..."
$PYTHON server.py
