#!/bin/bash
# Automated deployment script for CityBus bot
# Usage: ./deploy_automated.sh <server_ip> [ssh_user]

set -e

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Check arguments
if [ -z "$1" ]; then
    echo -e "${RED}Error: Server IP required${NC}"
    echo "Usage: ./deploy_automated.sh <server_ip> [ssh_user]"
    echo "Example: ./deploy_automated.sh 34.123.45.67 your_username"
    exit 1
fi

SERVER_IP=$1
SSH_USER=${2:-$USER}
BOT_NAME="citybus"
REMOTE_DIR="/home/$SSH_USER/$BOT_NAME"

# Prompt for SSH key
echo -e "${YELLOW}SSH Configuration${NC}"
read -p "Enter SSH key name (e.g. 'gcp', 'azure') [default: id_rsa]: " KEY_NAME
KEY_NAME=${KEY_NAME:-id_rsa}
SSH_KEY="$HOME/.ssh/$KEY_NAME"

if [ ! -f "$SSH_KEY" ]; then
    echo -e "${RED}Error: SSH key not found at $SSH_KEY${NC}"
    exit 1
fi

SSH_OPTS="-i $SSH_KEY"

echo
echo -e "${GREEN}=== CityBus Bot Automated Deployment ===${NC}"
echo "Server: $SERVER_IP"
echo "User: $SSH_USER"
echo "SSH Key: $SSH_KEY"
echo "Remote directory: $REMOTE_DIR"
echo

# Check if .env exists
if [ ! -f .env ]; then
    echo -e "${YELLOW}Warning: .env file not found${NC}"
    echo "Create .env from .env.example and set your TELEGRAM_BOT_TOKEN"
    read -p "Continue anyway? (y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

# Create deployment package
echo -e "${GREEN}[1/6] Creating deployment package...${NC}"
DEPLOY_DIR=$(mktemp -d)
tar -czf "$DEPLOY_DIR/citybus.tar.gz" \
    --exclude='*.pyc' \
    --exclude='__pycache__' \
    --exclude='.git' \
    --exclude='*.pb' \
    --exclude='.DS_Store' \
    --exclude='*.zip' \
    bot.py \
    gtfs_loader.py \
    realtime.py \
    requirements.txt \
    .env \
    .env.example \
    data/

echo -e "${GREEN}[2/6] Copying to server...${NC}"
scp $SSH_OPTS "$DEPLOY_DIR/citybus.tar.gz" "$SSH_USER@$SERVER_IP:/tmp/"

echo -e "${GREEN}[3/6] Deploying on server...${NC}"

# Create remote deployment script
cat > "$DEPLOY_DIR/remote_deploy.sh" << 'REMOTE_SCRIPT'
#!/bin/bash
set -e

BOT_NAME="citybus"
INSTALL_DIR="$HOME/$BOT_NAME"

echo "Stopping bot if running..."
sudo systemctl stop citybus-bot 2>/dev/null || true

echo "Creating/updating installation directory..."
mkdir -p "$INSTALL_DIR"
cd "$INSTALL_DIR"

echo "Extracting files..."
tar -xzf /tmp/citybus.tar.gz
rm /tmp/citybus.tar.gz

echo "Setting up Python virtual environment..."
if [ ! -d "venv" ]; then
    python3 -m venv venv
fi

echo "Activating virtual environment and installing dependencies..."
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

echo "Creating systemd service..."
sudo tee /etc/systemd/system/citybus-bot.service > /dev/null << SERVICE
[Unit]
Description=CityBus Telegram Bot
After=network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$INSTALL_DIR
EnvironmentFile=$INSTALL_DIR/.env
ExecStart=$INSTALL_DIR/venv/bin/python $INSTALL_DIR/bot.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
SERVICE

echo "Reloading systemd and starting bot..."
sudo systemctl daemon-reload
sudo systemctl enable citybus-bot
sudo systemctl start citybus-bot

echo "Deployment complete!"
echo "Check status with: sudo systemctl status citybus-bot"
echo "View logs with: sudo journalctl -u citybus-bot -f"
REMOTE_SCRIPT

# Copy and execute remote script
scp $SSH_OPTS "$DEPLOY_DIR/remote_deploy.sh" "$SSH_USER@$SERVER_IP:/tmp/"
ssh $SSH_OPTS "$SSH_USER@$SERVER_IP" "bash /tmp/remote_deploy.sh"

# Clean up
rm -rf "$DEPLOY_DIR"

echo
echo -e "${GREEN}[4/6] Checking bot status...${NC}"
ssh $SSH_OPTS "$SSH_USER@$SERVER_IP" "sudo systemctl status citybus-bot --no-pager"

echo
echo -e "${GREEN}[5/6] Deployment Summary${NC}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Server: $SERVER_IP"
echo
echo "Commands:"
echo "  View logs:   ssh $SSH_OPTS $SSH_USER@$SERVER_IP 'sudo journalctl -u citybus-bot -f'"
echo "  Restart bot: ssh $SSH_OPTS $SSH_USER@$SERVER_IP 'sudo systemctl restart citybus-bot'"
echo "  Stop bot:    ssh $SSH_OPTS $SSH_USER@$SERVER_IP 'sudo systemctl stop citybus-bot'"
echo
echo -e "${GREEN}✓ Deployment complete!${NC}"
