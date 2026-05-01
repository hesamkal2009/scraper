#!/bin/bash

# ============================================================================
# Deployment Script - Deploy to Remote Server via SSH
# Usage: ./deploy.sh
# ============================================================================

set -e

# Configuration
SERVER_USER="root"
SERVER_HOST="45.76.33.53"
SERVER_PATH="/root/scraper"
CONTAINER_NAME="scraper"
GIT_BRANCH="main"
IMAGE_NAME="scraper:latest"

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${BLUE}=== Scraper Deployment ===${NC}"
echo "Server: $SERVER_USER@$SERVER_HOST"
echo "Path: $SERVER_PATH"
echo "Container: $CONTAINER_NAME"
echo "Branch: $GIT_BRANCH"
echo ""

# Step 1: Push local changes to git
echo -e "${BLUE}[1/6] Pushing local changes to git...${NC}"
git add .
git commit -m "Deploy: $(date '+%Y-%m-%d %H:%M:%S')" || echo "No changes to commit"
git push origin $GIT_BRANCH

# Step 2: Connect to server and pull latest code (preserve .env)
echo -e "${BLUE}[2/6] Pulling latest code on server...${NC}"
ssh -i ~/.ssh/id_rsa $SERVER_USER@$SERVER_HOST << 'REMOTE_SCRIPT'
set -e
cd /root/scraper
echo "Current directory: $(pwd)"

# Preserve .env file before pulling
if [ -f .env ]; then
  cp .env .env.bak
  echo "✓ .env backed up"
fi

git fetch origin
git reset --hard origin/main

# Restore .env file after pulling
if [ -f .env.bak ]; then
  cp .env.bak .env
  rm .env.bak
  echo "✓ .env restored from backup"
fi

echo "✓ Code updated"
REMOTE_SCRIPT

# Step 3: Build Docker image
echo -e "${BLUE}[3/6] Building Docker image on server...${NC}"
ssh -i ~/.ssh/id_rsa $SERVER_USER@$SERVER_HOST << REMOTE_SCRIPT
set -e
cd /root/scraper
docker build -t scraper:latest .
echo "✓ Image built successfully"
REMOTE_SCRIPT

# Step 4: Stop old container
echo -e "${BLUE}[4/6] Stopping old container...${NC}"
ssh -i ~/.ssh/id_rsa $SERVER_USER@$SERVER_HOST << REMOTE_SCRIPT
set -e
docker stop scraper 2>/dev/null || echo "Container not running"
docker rm scraper 2>/dev/null || echo "Container not found"
echo "✓ Old container stopped/removed"
REMOTE_SCRIPT

# Step 5: Start new container
echo -e "${BLUE}[5/6] Starting new container...${NC}"
ssh -i ~/.ssh/id_rsa $SERVER_USER@$SERVER_HOST << REMOTE_SCRIPT
set -e
docker run -d \
  --name scraper \
  --restart unless-stopped \
  -v /root/scraper/data:/data \
  -e DOCKER=true \
  -e TELEGRAM_BOT_TOKEN \
  -e TELEGRAM_CHAT_ID \
  -e TARGET_URL \
  scraper:latest
echo "✓ Container started"
REMOTE_SCRIPT

# Step 6: Verify deployment
echo -e "${BLUE}[6/6] Verifying deployment...${NC}"
ssh -i ~/.ssh/id_rsa $SERVER_USER@$SERVER_HOST << REMOTE_SCRIPT
set -e
docker ps | grep scraper || (echo "Container not running!" && exit 1)
docker logs scraper --tail 5
echo "✓ Container is running"
REMOTE_SCRIPT

echo ""
echo -e "${GREEN}✓ Deployment completed successfully!${NC}"
