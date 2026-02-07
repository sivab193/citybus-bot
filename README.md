# CityBus Telegram Bot

A real-time bus arrival tracking bot for CityBus of Greater Lafayette, Indiana.

## Features

- **Real-time Tracking**: Get live updates on bus locations and arrival times.
- **Smart Search**: Find stops by name, number, or code (e.g., "Walmart", "205").
- **Static Schedules**: Check planned arrival times for the rest of the day.
- **Clean Interface**: Rolling message window keeps your chat history clutter-free.
- **Heartbeat Monitoring**: Built-in health check for reliability.

## Quick Start

### Prerequisites

- Python 3.9+
- Telegram account
- Bot token from [@BotFather](https://t.me/botfather)

### Installation

1. **Clone or download this repository**

2. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

3. **Configure environment variables**:
   ```bash
   cp .env.example .env
   nano .env  # Edit and set your TELEGRAM_BOT_TOKEN
   ```

4. **Run the bot**:
   ```bash
   python3 bot.py
   ```

## Bot Commands

| Command | Description | Example |
|---------|-------------|---------|
| `/start` | Show welcome message and help | `/start` |
| `/search <name>` | Search for bus stops | `/search Walmart` |
| `/arrivals <stop_id>` | Check arrivals at a stop | `/arrivals BUS215` |
| `/status` | Show your active tracking | `/status` |
| `/stop` | Stop receiving notifications | `/stop` |

## Usage Example

1. **Search for a stop**:
   ```
   /search Walmart
   ```

2. **Select from results** using inline buttons

3. **Choose a route** to track

4. **Pick update frequency** (1-10 minutes)

5. **Receive notifications** with real-time arrivals:
   ```
   🚏 Walmart West Lafayette
   🚌 Route 21: 4 minutes
   🚌 Route 22: 14 minutes
   ```

## Deploying to Google Compute Engine (VM)

### ⚡ Automated Deployment (Recommended)

Deploy with a single command:

```bash
./deploy_automated.sh <server_ip> [ssh_user]
```

**Example:**
```bash
./deploy_automated.sh 34.123.45.67 sivab
```

**What it does:**
1. ✓ Creates tar.gz package
2. ✓ Copies via SCP to server
3. ✓ SSHs into server
4. ✓ Stops bot if running
5. ✓ Creates Python venv
6. ✓ Installs dependencies
7. ✓ Sets up systemd service
8. ✓ Starts bot automatically

**Prerequisites:**
- Server must have Python 3.9+ installed
- SSH access configured (preferably with key)
- `.env` file configured with your bot token

---

### Automated Deployment

Use the deployment script:

```bash
cd /Users/sivab/coding/citybus
./deploy_vm.sh
```

This will:
1. Create a VM instance (default: e2-micro, ~$7/month or FREE tier)
2. Set up firewall rules
3. Provide step-by-step instructions

### Manual Deployment

#### 1. Create VM Instance

```bash
gcloud compute instances create citybus-bot \
  --zone=us-central1-a \
  --machine-type=e2-micro \
  --image-family=debian-11 \
  --image-project=debian-cloud \
  --tags=bot-server
```

#### 2. Upload Bot Files

```bash
gcloud compute scp --recurse ./* citybus-bot:~/citybus --zone=us-central1-a
```

#### 3. SSH and Install

```bash
gcloud compute ssh citybus-bot --zone=us-central1-a

# On the VM:
cd ~/citybus
pip3 install -r requirements.txt
export TELEGRAM_BOT_TOKEN='your_token_here'
python3 bot.py
```

#### 4. Run as System Service (Auto-restart)

Create service file:
```bash
sudo nano /etc/systemd/system/citybus-bot.service
```

Paste:
```ini
[Unit]
Description=CityBus Telegram Bot
After=network.target

[Service]
Type=simple
User=your_username
WorkingDirectory=/home/your_username/citybus
Environment="TELEGRAM_BOT_TOKEN=your_token_here"
Environment="HEARTBEAT_URL=http://localhost:1903/heartbeat"
ExecStart=/usr/bin/python3 /home/your_username/citybus/bot.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Enable and start:
```bash
sudo systemctl daemon-reload
sudo systemctl enable citybus-bot
sudo systemctl start citybus-bot
sudo systemctl status citybus-bot
```

View logs:
```bash
sudo journalctl -u citybus-bot -f
```

### Monitoring Endpoints

Once deployed, access:
The bot also sends heartbeat to your monitoring dashboard every 60 seconds (if enabled).

## Project Structure

```
citybus/
├── bot.py                      # Main Telegram bot
├── gtfs_loader.py              # GTFS static data loader
├── realtime.py                 # GTFS-RT feed fetcher
├── requirements.txt            # Python dependencies
├── deploy_vm.sh                # VM deployment script
└── data/                       # GTFS static data
    ├── stops.txt
    ├── routes.txt
    ├── trips.txt
    └── ...
```

## Data Sources

- **Static GTFS**: Stop names, routes, schedules
- **GTFS-Realtime**: Live bus positions and arrival predictions
- **Provider**: [CityBus of Greater Lafayette](https://www.gocitybus.com/)

## Technical Details

- **Framework**: `python-telegram-bot` 20.0+
- **Data Format**: GTFS and GTFS-Realtime (Protocol Buffers)
- **Update Frequency**: Real-time data fetched every 30 seconds
- **Search**: Fuzzy matching with `rapidfuzz`
- **Scheduling**: APScheduler for periodic notifications

## Environment Variables

**Configuration via `.env` file:**

```bash
# Required
TELEGRAM_BOT_TOKEN=your_bot_token_here

# Optional
ENABLE_HEARTBEAT=false
HEARTBEAT_URL=http://localhost:1903/heartbeat
HEARTBEAT_INTERVAL=60
```

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `TELEGRAM_BOT_TOKEN` | Yes | - | Bot token from @BotFather |
| `ENABLE_HEARTBEAT` | No | false | Enable heartbeat monitoring |
| `HEARTBEAT_URL` | No | http://localhost:1903/heartbeat | Monitoring dashboard URL |
| `HEARTBEAT_INTERVAL` | No | 60 | Seconds between heartbeats |

## License

MIT

## Contributing

Issues and pull requests welcome!
