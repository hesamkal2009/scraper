# Deployment Guide

## One-Command Deployment

Deploy your latest changes to the production server with a single command.

### Prerequisites

1. **SSH Key Authentication** - Your SSH key must be set up:
   ```bash
   # Generate SSH key if you don't have one
   ssh-keygen -t rsa -b 4096 -f ~/.ssh/id_rsa
   
   # Copy public key to server
   ssh-copy-id -i ~/.ssh/id_rsa root@45.76.33.53
   ```

2. **Git** - Ensure your code is in a git repository:
   ```bash
   git init
   git add .
   git commit -m "Initial commit"
   git remote add origin <your-repo-url>
   ```

3. **Docker** - Must be installed on remote server

### Quick Start

#### Full Deployment (Recommended)
```bash
make deploy
```
Or manually:
```bash
./deploy.sh
```

This will:
1. Commit & push local changes to git
2. SSH into server
3. Pull latest code
4. Build Docker image
5. Stop old container
6. Start new container

Each deploy step emits a clear console status message so you can follow progress and verify which stage is running.

#### Quick Deployment (Skip git push)
```bash
make deploy-quick
```
Skips git operations, just rebuilds and restarts.

#### View Logs
```bash
make logs
```
Streams live container logs from the server.

#### SSH into Server
```bash
make ssh
```

#### Stop/Restart Container
```bash
make stop       # Stop container
make restart    # Restart container
```

## How It Works

1. **Local Git Push** - Commits changes and pushes to `main` branch
2. **Remote Git Pull** - SSH connects to server, pulls latest code
3. **Docker Build** - Builds new image with latest code
4. **Container Replacement** - Stops old container, starts new one
5. **Verification** - Checks container is running and shows logs

## Environment Variables

On the remote server, ensure these are set (in `.env` or Docker environment):
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`
- `TARGET_URL`
- `DOCKER=true`

The deploy script passes them to the container automatically.

## Troubleshooting

### SSH Connection Refused
```bash
# Test SSH connection
ssh -i ~/.ssh/id_rsa root@45.76.33.53
```

### Container Won't Start
```bash
# View error logs
make logs

# Check Docker status
make ssh
docker ps -a
docker logs mvgm-watcher
```

### Git Push Fails
Ensure you've set your git remote:
```bash
git remote -v
# Should show your GitHub/GitLab repo
```

## Configuration

To customize the deployment, edit `deploy.sh`:
- `SERVER_USER` - SSH user (default: root)
- `SERVER_HOST` - Server IP/hostname
- `SERVER_PATH` - Project directory on server
- `CONTAINER_NAME` - Docker container name
- `GIT_BRANCH` - Git branch to deploy (default: main)

## One-Liner Status Check

```bash
ssh -i ~/.ssh/id_rsa root@45.76.33.53 'docker ps | grep mvgm-watcher && echo "✓ Running" || echo "✗ Not running"'
```
