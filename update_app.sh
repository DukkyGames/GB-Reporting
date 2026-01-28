#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/opt/gb-reporting/GB-Reporting"
SERVICE_NAME="gb-reporting"

cd "$APP_DIR"

# Remove python bytecode caches so git pull doesn't fail on pycache artifacts
find . -type d -name "__pycache__" -prune -exec rm -rf {} +

git pull

# Ensure venv exists
if [ ! -d ".venv" ]; then
  python3 -m venv .venv
fi

source .venv/bin/activate
pip install -r requirements.txt

sudo systemctl restart "$SERVICE_NAME"
sudo systemctl status "$SERVICE_NAME" --no-pager
