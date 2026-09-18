Lunar

«Lunar Bot V3 — a modular Discord bot built for the Lunar / Lunaranime community.»

Lunar is a feature-rich Discord bot focused on community management, entertainment, integrations, XP/leveling, music, moderation, giveaways, account linking, and Lunar-specific services.

The project is actively maintained and its dashboard is currently undergoing a major revamp.

---

Credits

Developers

- Vireon Noctis — The Slop King
- Thanon C — Dei Evergreen
- Real — real.dev.io
---

Features

Community

- XP and leveling system
- Leaderboards
- Guild XP tracking
- Account linking
- Suggestions
- Modmail
- Staff tools
- Channel management
- Inbox utilities
- Birthday/community interactions

Entertainment

- Akinator
- Coin flip
- Dad jokes
- Random memes
- Fun commands
- Randomizer utilities
- Interactive Discord components

Music

- T-Music commands
- Music search/integration systems
- Spotify integration support
- YouTube API support
- SoundCloud integration support

Administration

- Moderation utilities
- Giveaway management
- System management
- Restart controls
- Maintenance mode
- Error handling
- Automated cog loading
- Slash-command synchronization

Lunar Integrations

- Lunar API integration
- Lunar XP integration
- GitHub integration
- Collection/reply systems
- Staff guide systems
- External service integrations

---

Project Structure

Lunar-main/
│
├── bot.py
├── .env.example
├── README.md
├── install.txt
│
├── cogs/
│   ├── commands/
│   │   ├── about.py
│   │   ├── akinator.py
│   │   ├── anime.py
│   │   ├── channel.py
│   │   ├── close.py
│   │   ├── coinflip.py
│   │   ├── dadjoke.py
│   │   ├── fun.py
│   │   ├── giveaway.py
│   │   ├── inbox.py
│   │   ├── interactions.py
│   │   ├── leaderboard.py
│   │   ├── level.py
│   │   ├── linkaccount.py
│   │   ├── modmail.py
│   │   ├── randommeme.py
│   │   ├── restart.py
│   │   ├── search.py
│   │   ├── steal.py
│   │   ├── suggest.py
│   │   ├── system.py
│   │   └── tmusic.py
│   │
│   ├── integrations/
│   │   ├── api.py
│   │   ├── collectionreply.py
│   │   ├── counting.py
│   │   ├── github.py
│   │   ├── guild_xp.py
│   │   ├── modmail-int.py
│   │   ├── staffguide.py
│   │   └── xp.py
│   │
│   └── utilities/
│       ├── database.py
│       ├── emoji.py
│       ├── error.py
│       ├── generatecode.py
│       ├── info.py
│       ├── level_card.py
│       ├── randomizer.py
│       ├── xp.py
│       └── xp_announcment.py
│
└── dashboard/
    └── backend/
        └── main.py

---

Requirements

Python

Recommended:

Python 3.11+

Minimum supported version:

Python 3.10

Check your version:

python --version

On Linux:

python3 --version

---

Installation

Windows

cd Lunar-main
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -U discord.py aiohttp Flask scylla-driver akinator python-dotenv
python bot.py

---

Linux / macOS

cd Lunar-main
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -U discord.py aiohttp Flask scylla-driver akinator python-dotenv
python bot.py

---

Environment Configuration

Create a ".env" file in the root directory:

TOKEN=your_discord_bot_token

lunar_token=your_lunar_api_token
bypass_token=your_lunar_xp_bypass_token

SPOTIFY_CLIENT_ID=your_spotify_client_id
SPOTIFY_CLIENT_SECRET=your_spotify_client_secret

YOUTUBE_API_KEY=your_youtube_api_key

SOUNDCLOUD_CLIENT_ID=your_soundcloud_client_id

TMUSIC_POLL_INTERVAL_MINUTES=10

«Never commit your real ".env" file to GitHub or share your Discord bot token publicly.»

---

Discord Bot Setup

Create a Discord application through the Discord Developer Portal.

Create a bot and place its token inside:

TOKEN=your_discord_bot_token

Lunar requires the necessary privileged Discord intents, including:

Message Content Intent
Server Members Intent

These must be enabled in the Discord Developer Portal.

The bot also needs the required permissions in the Discord server where it is installed.

---

Database

Lunar uses a ScyllaDB/Cassandra-compatible database layer.

Install the Python driver with:

pip install scylla-driver

The database layer uses the Cassandra-compatible Python modules provided by the driver.

A typical local ScyllaDB configuration uses:

Host: 127.0.0.1
Port: 9042

Make sure the database is available before starting Lunar.

---

Running Lunar

From the project root:

python bot.py

Lunar automatically discovers and loads its available cogs during startup.

---

Dashboard

Dashboard Revamp

The Lunar dashboard is currently being completely revamped.

The existing dashboard implementation should be considered transitional and is not the final Lunar dashboard.

The new dashboard is being designed around a cleaner architecture connecting:

Lunar Bot
    │
    ├── Discord
    │
    ├── ScyllaDB
    │
    └── Dashboard API
            │
            ├── Management
            ├── Configuration
            ├── Account systems
            └── Administrative controls

Until the revamp is complete, Discord remains the primary interface for Lunar management.

---

Dashboard Backend

The current dashboard backend is based around:

- FastAPI
- Pydantic
- Redis / aioredis
- SQLAlchemy

Install the backend dependencies:

python -m pip install -U fastapi pydantic uvicorn aioredis sqlalchemy

Run the backend during development:

uvicorn dashboard.backend.main:app --host 0.0.0.0 --port 8000

Development endpoint:

http://127.0.0.1:8000

«The dashboard backend is under active development and may change substantially during the revamp.»

---

VPS Deployment

A Linux VPS is recommended for running Lunar continuously.

The following setup is intended for Ubuntu/Debian-based VPS systems.

1. Update the VPS

sudo apt update && sudo apt upgrade -y

Install the required packages:

sudo apt install -y python3 python3-pip python3-venv git

Verify Python:

python3 --version

---

2. Clone Lunar

git clone YOUR_REPOSITORY_URL Lunar
cd Lunar

You may also upload the project directly to the VPS instead of using Git.

---

3. Create a Virtual Environment

python3 -m venv .venv
source .venv/bin/activate

Upgrade pip:

python -m pip install --upgrade pip

Install Lunar:

python -m pip install -U discord.py aiohttp Flask scylla-driver akinator python-dotenv

For dashboard development:

python -m pip install -U fastapi pydantic uvicorn aioredis sqlalchemy

---

4. Configure ".env"

nano .env

Add your production environment variables:

TOKEN=your_discord_bot_token

lunar_token=your_lunar_api_token
bypass_token=your_lunar_xp_bypass_token

SPOTIFY_CLIENT_ID=your_spotify_client_id
SPOTIFY_CLIENT_SECRET=your_spotify_client_secret

YOUTUBE_API_KEY=your_youtube_api_key

SOUNDCLOUD_CLIENT_ID=your_soundcloud_client_id

TMUSIC_POLL_INTERVAL_MINUTES=10

Save the file and make sure it is not publicly accessible.

---

VPS Testing

Before setting up Lunar as a permanent service, test it manually:

source .venv/bin/activate
python bot.py

If the bot starts correctly, stop it with:

CTRL+C

Then configure "systemd".

---

systemd Service

Using "systemd" allows Lunar to automatically:

- Start after a VPS reboot
- Restart after a crash
- Run without an active SSH session
- Store logs through "journalctl"

Create the service file:

sudo nano /etc/systemd/system/lunar.service

Paste:

[Unit]
Description=Lunar Discord Bot
After=network.target

[Service]
Type=simple
User=YOUR_VPS_USERNAME
WorkingDirectory=/home/YOUR_VPS_USERNAME/Lunar
ExecStart=/home/YOUR_VPS_USERNAME/Lunar/.venv/bin/python /home/YOUR_VPS_USERNAME/Lunar/bot.py
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target

Replace:

YOUR_VPS_USERNAME

with the actual VPS username.

Reload "systemd":

sudo systemctl daemon-reload

Enable Lunar at startup:

sudo systemctl enable lunar

Start Lunar:

sudo systemctl start lunar

Check its status:

sudo systemctl status lunar

---

VPS Service Commands

Start

sudo systemctl start lunar

Stop

sudo systemctl stop lunar

Restart

sudo systemctl restart lunar

Status

sudo systemctl status lunar

Enable at startup

sudo systemctl enable lunar

Disable startup

sudo systemctl disable lunar

---

VPS Logs

Live logs:

sudo journalctl -u lunar -f

Last 100 lines:

sudo journalctl -u lunar -n 100

Current boot:

sudo journalctl -u lunar -b

---

Updating Lunar

Stop the service:

sudo systemctl stop lunar

Enter the project:

cd /home/YOUR_VPS_USERNAME/Lunar

Pull updates:

git pull

Activate the environment:

source .venv/bin/activate

Update dependencies:

python -m pip install -U discord.py aiohttp Flask scylla-driver akinator python-dotenv

Start Lunar:

sudo systemctl start lunar

Check:

sudo systemctl status lunar

---

Development

Run Lunar directly during development:

source .venv/bin/activate
python bot.py

Windows:

.\.venv\Scripts\Activate.ps1
python bot.py

Check a Python file for syntax errors:

python -m py_compile bot.py

Check an individual cog:

python -m py_compile cogs/commands/about.py

---

Security

Never commit or publicly expose:

.env
Discord bot tokens
API keys
Database credentials
Private authentication tokens

Use environment variables for sensitive configuration.

If a Discord token or API credential is accidentally exposed, revoke/regenerate it immediately.

---

Production Layout

A typical VPS installation:

/home/username/Lunar/
│
├── .venv/
├── .env
├── bot.py
├── README.md
├── install.txt
│
├── cogs/
│
└── dashboard/
    └── backend/

System service:

/etc/systemd/system/lunar.service

Production architecture:

                    ┌──────────────┐
                    │   Discord    │
                    └──────┬───────┘
                           │
                    ┌──────▼───────┐
                    │ Lunar Bot    │
                    └──────┬───────┘
                           │
              ┌────────────┼────────────┐
              │            │            │
        ┌─────▼─────┐ ┌────▼─────┐ ┌──▼──────────┐
        │ ScyllaDB  │ │ Lunar API│ │ Dashboard   │
        └───────────┘ └──────────┘ └─────────────┘

---

Troubleshooting

Bot Does Not Start

Run it manually:

python bot.py

Read the first traceback carefully and fix the underlying error.

Invalid Discord Token

Verify:

TOKEN=your_discord_bot_token

Make sure the token has not been regenerated or revoked.

Database Connection Failure

Verify that ScyllaDB is running and that Lunar can connect to the configured host and port.

Missing Python Package

Inside the same virtual environment used to run Lunar:

python -m pip install PACKAGE_NAME

Then restart Lunar.

VPS Service Keeps Stopping

Check:

sudo systemctl status lunar

Then inspect:

sudo journalctl -u lunar -n 100

The logs should reveal the Python exception or service configuration problem.

---

Project Status

Lunar is under active development.

Current priorities include:

- Bot stability
- Database reliability
- Command and integration maintenance
- Production deployment improvements
- Complete dashboard revamp

The dashboard currently remains a work in progress and should not be considered the final production interface.

---

Lunar

Built by Vireon Noctis & @real.dev,io on discord

Lunar Bot V3
Made with ♥ and a soul.
