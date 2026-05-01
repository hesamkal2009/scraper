#!/usr/bin/env bash
# setup.sh — builds the Docker image, sets up /root/scraper, installs cron
# Run as root on Ubuntu 24.04
set -euo pipefail

DEPLOY_DIR="/root/scraper"
DATA_DIR="$DEPLOY_DIR/data"
IMAGE_NAME="scraper"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "=== Scraper Watcher Setup ==="
echo ""

# ── 1. Docker ─────────────────────────────────────────────────────────────
echo "[1/4] Checking Docker..."
if ! command -v docker &>/dev/null; then
    echo "    Docker not found — installing..."
    apt-get update -qq
    apt-get install -y -qq ca-certificates curl gnupg
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    chmod a+r /etc/apt/keyrings/docker.gpg
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
        > /etc/apt/sources.list.d/docker.list
    apt-get update -qq
    apt-get install -y -qq docker-ce docker-ce-cli containerd.io
    echo "    Docker installed."
else
    echo "    Docker $(docker --version | awk '{print $3}' | tr -d ',') found — OK."
fi

# ── 2. Directories ────────────────────────────────────────────────────────
echo "[2/4] Creating deploy directories..."
mkdir -p "$DATA_DIR"

echo "[2/4] Copying project files to deploy directory..."
# Copy project files
cp "$SCRIPT_DIR/watcher.py"             "$DEPLOY_DIR/"
cp "$SCRIPT_DIR/chromedriver_manager.py" "$DEPLOY_DIR/"
cp "$SCRIPT_DIR/requirements.txt"       "$DEPLOY_DIR/"
cp "$SCRIPT_DIR/Dockerfile"             "$DEPLOY_DIR/"

# Only copy .env if one doesn't exist in data/ yet — never overwrite secrets
if [ ! -f "$DATA_DIR/.env" ]; then
    cp "$SCRIPT_DIR/.env" "$DATA_DIR/.env"
    echo "    .env copied to $DATA_DIR/.env"
    echo "    ⚠️  EDIT $DATA_DIR/.env and set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID before running."
else
    echo "    $DATA_DIR/.env already exists — not overwritten."
fi

# ── 3. Build Docker image ─────────────────────────────────────────────────
echo "[3/4] Building Docker image '$IMAGE_NAME' (this may take a few minutes)..."
docker build --pull -t "$IMAGE_NAME" "$DEPLOY_DIR"
echo "    Image built."
echo "[3/4] Docker build completed successfully."

# ── 4. Cron job ───────────────────────────────────────────────────────────
echo "[4/4] Installing cron job (every 5 minutes)..."

CRON_CMD="*/5 * * * * docker run --rm -v $DATA_DIR:/data $IMAGE_NAME >> $DATA_DIR/cron.log 2>&1"
CRON_MARKER="# scraper"

( crontab -l 2>/dev/null | grep -v "$CRON_MARKER"; echo "$CRON_CMD $CRON_MARKER" ) | crontab -
echo "    Cron installed."

echo ""
echo "=== Setup complete ==="
echo ""
echo "  Deploy dir  : $DEPLOY_DIR"
echo "  Data dir    : $DATA_DIR  (mounted as /data inside the container)"
echo "  Image       : $IMAGE_NAME"
echo "  Cron        : every 5 minutes"
echo ""
echo "  Useful commands:"
echo "    Test run  : docker run --rm -v $DATA_DIR:/data $IMAGE_NAME"
echo "    Rebuild   : docker build --pull -t $IMAGE_NAME $DEPLOY_DIR"
echo "    Cron log  : tail -f $DATA_DIR/cron.log"
echo "    Error log : tail -f $DATA_DIR/watcher.log"
echo "    State     : cat $DATA_DIR/last_listing.txt"
