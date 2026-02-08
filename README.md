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
## Deployment

### Automated Deployment (Recommended)

Use the provided script to deploy the bot to a remote server:

```bash
./deploy_automated.sh <server_ip> [ssh_user]
```

- `<server_ip>`: IP address of your server
- `[ssh_user]`: (optional) SSH username, defaults to your current user

**Example:**
```bash
./deploy_automated.sh 34.123.45.67 sivab
```

**What it does:**
1. Packages the bot files
2. Copies them to the server via SCP
3. SSHs into the server
4. Stops any running bot instance
5. Creates a Python virtual environment
6. Installs dependencies
7. Sets up a systemd service for auto-restart
8. Starts the bot

**Prerequisites:**
- Server must have Python 3.9+ installed
- SSH access configured (preferably with key)
- `.env` file configured with your bot token

---

### Manual Deployment

If you prefer not to use the automated script, follow these steps manually:

1. **Copy files to server**
   ```bash
   scp -r . <ssh_user>@<server_ip>:~/citybus
   ```

2. **SSH into server**
   ```bash
   ssh <ssh_user>@<server_ip>
   cd ~/citybus
   ```

3. **Create Python virtual environment and install dependencies**
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```

4. **Configure environment variables**
   ```bash
   cp .env.example .env
   nano .env  # Set your TELEGRAM_BOT_TOKEN
   ```

5. **Run the bot**
   ```bash
   source venv/bin/activate
   python3 bot.py
   ```

6. **(Optional) Set up as a systemd service for auto-restart**
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
   User=<ssh_user>
   WorkingDirectory=/home/<ssh_user>/citybus
   Environment="TELEGRAM_BOT_TOKEN=your_token_here"
   Environment="HEARTBEAT_URL=http://localhost:1903/heartbeat"
   ExecStart=/home/<ssh_user>/citybus/venv/bin/python3 /home/<ssh_user>/citybus/bot.py
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
