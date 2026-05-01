# Define deployment helpers and commands available from make
.PHONY: help deploy deploy-quick logs ssh

help:
	@echo "HouseCheckerV2 Deployment Commands:"
	@echo ""
	@echo "  make deploy          - Full deployment (push, build, restart container)"
	@echo "  make deploy-quick    - Quick deployment (no git push, just pull & rebuild)"
	@echo "  make logs            - View container logs on remote server"
	@echo "  make ssh             - SSH into remote server"
	@echo "  make stop            - Stop container on remote server"
	@echo "  make restart         - Restart container on remote server"

# Full deployment workflow through the shell deployment script
deploy:
	@echo "[make deploy] Launching deployment script..."
	@chmod +x deploy.sh
	@./deploy.sh

# Quick deployment without pushing local git changes
deploy-quick:
	@echo "[make deploy-quick] Pulling latest code and restarting remote container..."
	@ssh -i ~/.ssh/id_rsa root@45.76.33.53 'cd /root/HouseCheckerV2 && git pull origin main && docker build -t housecheckerv2:latest . && docker restart housecheckerv2'
	@echo "✓ Quick deployment complete!"

# Tail the remote container logs for live debugging
logs:
	@echo "[make logs] Streaming remote container logs..."
	@ssh -i ~/.ssh/id_rsa root@45.76.33.53 'docker logs -f housecheckerv2'

# Open an interactive SSH shell on the remote server
ssh:
	@echo "[make ssh] Opening SSH shell on remote server..."
	@ssh -i ~/.ssh/id_rsa root@45.76.33.53

# Stop the running remote container if present
stop:
	@echo "[make stop] Stopping remote container..."
	@ssh -i ~/.ssh/id_rsa root@45.76.33.53 'docker stop housecheckerv2'
	@echo "✓ Container stopped"

# Restart the remote container using the existing image
restart:
	@echo "[make restart] Restarting remote container..."
	@ssh -i ~/.ssh/id_rsa root@45.76.33.53 'docker restart housecheckerv2'
	@echo "✓ Container restarted"
