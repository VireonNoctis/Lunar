Lunar

«Lunar Bot V3 — a modular Discord bot built for the Lunar / Lunaranime community.»

Lunar is a feature-rich Discord bot focused on community management, entertainment, integrations, XP/leveling, a coins economy, a gacha card game, music release tracking, moderation, giveaways (with automated reward payouts), account linking, and Lunar-specific services.

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

- Website XP and leveling system (source of truth lives on lunarx.to)
- Guild XP — a separate, Discord-only leveling track for this server
- Coins economy — a second currency, earned from messages and level-ups on either XP system
- Role-based earning bonuses (Website Donator +50%, Server Booster +25%, stacking)
- Leaderboards (Guild XP and Lunar website XP)
- Account linking (/link) — ties your Discord account to your Lunar account
- Staff tools
- Channel management
- Inbox utilities
- Interactive Discord components (/interact)

Gacha

- Card catalog lookup with full stats/skills (/gacha card)
- Ownership/mint-number lookup per card (/gacha owners)
- Catalog browsing by rarity (/gacha list)
- Admin card-gifting integration (used by giveaway rewards)

Giveaways

- Cryptographically-verifiable winner drawing (commitment/proof included in results)
- Automated reward payouts — configure once per giveaway (/grewards) and every
  winner automatically receives gacha cards, coins, XP, a donator role, or a
  manual reward when the giveaway ends
- Reroll and re-verification of entrants' linked accounts

Entertainment

- Akinator
- Coin flip (provably fair)
- Dad jokes
- Random memes
- Fun commands (8ball, dice, rate)
- Cryptographic randomizer utilities

Music

- T-Music release tracking commands (this tracks new releases from artists/tags — it is not a voice-channel music player)
- Spotify integration support
- YouTube API support
- SoundCloud integration support

Administration

- Moderation utilities
- Giveaway management + automated rewards
- System diagnostics panel (/system)
- Restart controls
- Maintenance mode
- Centralized error handling with Discord channel logging (cogs/utilities/error.py)
- Automated cog loading (bot.py auto-discovers every cog under cogs/ at startup)
- Slash-command synchronization

Lunar Integrations

- cogs/utilities/lunarapi.py — the single shared client for every Lunar API call
  (XP grants, coin grants, gacha lookups/gifting, profile lookups, status pings).
  One session, one place auth headers live, one error type.
- Lunar XP integration
- Lunar coins integration
- Lunar gacha integration (lookup + admin gifting)
- GitHub integration
- Collection/reply systems
- Staff guide systems

Help

- /help — an in-Discord command reference with a category dropdown, covering
  every command plus deep-dive pages explaining exactly how the XP/coins and
  gacha systems work under the hood.

---

Project Structure
```
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
│   │   ├── gacha.py
│   │   ├── giveaway.py
│   │   ├── help.py
│   │   ├── inbox.py
│   │   ├── interactions.py
│   │   ├── leaderboard.py
│   │   ├── level.py
│   │   ├── linkaccount.py
│   │   ├── randommeme.py
│   │   ├── restart.py
│   │   ├── search.py
│   │   ├── steal.py
│   │   ├── system.py
│   │   └── tmusic.py
│   │
│   ├── integrations/
│   │   ├── coins.py
│   │   ├── collectionreply.py
│   │   ├── counting.py
│   │   ├── gacha-int.py
│   │   ├── github.py
│   │   ├── guild_xp.py
│   │   ├── staffguide.py
│   │   └── xp.py
│   │
│   └── utilities/
│       ├── api.py
│       ├── database.py
│       ├── emoji.py
│       ├── error.py
│       ├── generatecode.py
│       ├── giveaway_rewards.py
│       ├── info.py
│       ├── level_card.py
│       ├── lunarapi.py
│       ├── mathematical_random.py
│       ├── randomizer.py
│       ├── xp.py
│       └── xp_announcment.py
│
├── telegram/
│   └── bots/
│       ├── lunar.py
│       ├── nova.py
│       └── sapphire.py
│
└── dashboard/
    └── backend/
        └── main.py
```
Note: `bot.py` auto-discovers every `.py` file under `cogs/` (excluding `cogs/utilities/`) at startup and loads it as a cog — new command/integration files don't need to be registered anywhere. `cogs/utilities/` holds shared, non-cog code (the database layer, the Lunar API client, the XP/coin math, etc.). The `telegram/` bots are separate standalone processes — they are not loaded by `bot.py` and have their own tokens/config.

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
```
cd Lunar-main
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -U discord.py aiohttp akinator.py python-dotenv Pillow "psycopg[binary]" psycopg-pool
python bot.py
```
---

Linux / macOS
```
cd Lunar-main
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -U discord.py aiohttp akinator.py python-dotenv Pillow "psycopg[binary]" psycopg-pool
python bot.py
```
See `install.txt` for the full package breakdown, optional dashboard/Telegram dependencies, and what each package is actually for.

---

Environment Configuration
```
Create a ".env" file in the root directory (or copy .env.example):

TOKEN=your_discord_bot_token

lunar_token=your_lunar_api_token
bypass_token=your_lunar_bypass_token

DATABASE_URL=postgresql://user:password@host:5432/lunar

SPOTIFY_CLIENT_ID=your_spotify_client_id
SPOTIFY_CLIENT_SECRET=your_spotify_client_secret

YOUTUBE_API_KEY=your_youtube_api_key

SOUNDCLOUD_CLIENT_ID=your_soundcloud_client_id

TMUSIC_POLL_INTERVAL_MINUTES=10

«Never commit your real ".env" file to GitHub or share your Discord bot token publicly.»
```
Every Lunar API call in the bot (XP, coins, gacha, profile lookups) reads `lunar_token`/`bypass_token` in **lowercase** — that's the only casing anything in the codebase actually reads.

---

Discord Bot Setup
```
Create a Discord application through the Discord Developer Portal.

Create a bot and place its token inside:

TOKEN=your_discord_bot_token

Lunar requires the necessary privileged Discord intents, including:

Message Content Intent
Server Members Intent

These must be enabled in the Discord Developer Portal.

The bot also needs the required permissions in the Discord server where it is installed.
```
---

Database

Lunar uses **PostgreSQL** (via `psycopg` + `psycopg_pool`) as its database layer — see `cogs/utilities/database.py` for the full schema (it creates its own tables on startup).

Install the Python driver with:
```
pip install "psycopg[binary]" psycopg-pool
```
Point the bot at your database with either a single DSN or individual vars:
```
DATABASE_URL=postgresql://user:password@host:5432/lunar

# ...or...
PGHOST=127.0.0.1
PGPORT=5432
PGUSER=your_postgres_user
PGPASSWORD=your_postgres_password
PGDATABASE=lunar
```
Make sure PostgreSQL is running and reachable before starting Lunar.

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
```
Lunar Bot
    │
    ├── Discord
    │
    ├── PostgreSQL
    │
    └── Dashboard API
            │
            ├── Management
            ├── Configuration
            ├── Account systems
            └── Administrative controls
```
Until the revamp is complete, Discord remains the primary interface for Lunar management.

---

Dashboard Backend

The current dashboard backend is a small FastAPI app based around:

- FastAPI
- Pydantic
- Uvicorn (to run it)
- aioredis (optional — try/except-imported, degrades cleanly if absent)
- SQLAlchemy (optional — same graceful degrade, and note it's a
  separate DB connection from the bot's own psycopg layer even
  though both default to reading `DATABASE_URL`)

Install the backend dependencies:

python -m pip install -U fastapi pydantic uvicorn aioredis SQLAlchemy

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
`
sudo apt update && sudo apt upgrade -y`

Install the required packages:
`
sudo apt install -y python3 python3-pip python3-venv git postgresql`

Verify Python:
`
python3 --version`

---

2. Clone Lunar
`
git clone YOUR_REPOSITORY_URL Lunar
cd Lunar`

You may also upload the project directly to the VPS instead of using Git.

---

3. Create a Virtual Environment
```
python3 -m venv .venv
source .venv/bin/activate
```
Upgrade pip:
`
python -m pip install --upgrade pip`

Install Lunar:
`
python -m pip install -U discord.py aiohttp akinator.py python-dotenv Pillow "psycopg[binary]" psycopg-pool`

For dashboard development:
`
python -m pip install -U fastapi pydantic uvicorn`

---

4. Configure ".env"
```
nano .env

Add your production environment variables:

TOKEN=your_discord_bot_token

lunar_token=your_lunar_api_token
bypass_token=your_lunar_bypass_token

DATABASE_URL=postgresql://user:password@127.0.0.1:5432/lunar

SPOTIFY_CLIENT_ID=your_spotify_client_id
SPOTIFY_CLIENT_SECRET=your_spotify_client_secret

YOUTUBE_API_KEY=your_youtube_api_key

SOUNDCLOUD_CLIENT_ID=your_soundcloud_client_id

TMUSIC_POLL_INTERVAL_MINUTES=10

Save the file and make sure it is not publicly accessible.
```
---

VPS Testing

Before setting up Lunar as a permanent service, test it manually:
`
source .venv/bin/activate
python bot.py`

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
`
sudo nano /etc/systemd/system/lunar.service`

Paste:

[Unit]
Description=Lunar Discord Bot
After=network.target postgresql.service

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
`
YOUR_VPS_USERNAME
`
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

python -m pip install -U discord.py aiohttp akinator.py python-dotenv Pillow "psycopg[binary]" psycopg-pool

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

Check every file in the project at once:

find . -name "*.py" -print0 | xargs -0 -n1 python -m py_compile

---

Security

Never commit or publicly expose:

.env
Discord bot tokens
API keys (lunar_token, bypass_token, Spotify/YouTube/SoundCloud credentials)
Database credentials (DATABASE_URL, PGPASSWORD)
Private authentication tokens

Use environment variables for sensitive configuration.

If a Discord token or API credential is accidentally exposed, revoke/regenerate it immediately.

Note on the `ERROR_LOG_CHANNEL_ID` wired into `cogs/utilities/error.py`: uncaught errors across the bot are logged to a dedicated Discord channel with a full traceback attachment. Make sure that channel is staff-only.

---

Production Layout

A typical VPS installation:
```
/home/username/Lunar/
│
├── .venv/
├── .env
├── bot.py
├── README.md
├── install.txt
│
├── cogs/
├── telegram/
│
└── dashboard/
    └── backend/
```
System service:

/etc/systemd/system/lunar.service

Production architecture:
```
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
        │PostgreSQL │ │ Lunar API│ │ Dashboard   │
        └───────────┘ └──────────┘ └─────────────┘
```
`Lunar API` above is everything under `https://api.lunarx.to` — XP grants, coin grants, gacha lookups/gifting, and profile lookups — all routed through the single shared client in `cogs/utilities/lunarapi.py`.

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

Verify that PostgreSQL is running and that `DATABASE_URL` (or `PGHOST`/`PGPORT`/`PGUSER`/`PGPASSWORD`/`PGDATABASE`) points at a reachable instance.

Lunar API Calls Failing / Silently Doing Nothing

Check that `lunar_token` and `bypass_token` are set — in **lowercase**. Every Lunar API call in the bot goes through `cogs/utilities/lunarapi.py`, which only reads the lowercase names.

Missing Python Package

Inside the same virtual environment used to run Lunar:

python -m pip install PACKAGE_NAME

Then restart Lunar.

VPS Service Keeps Stopping

Check:

sudo systemctl status lunar

Then inspect:

sudo journalctl -u lunar -n 100

The logs should reveal the Python exception or service configuration problem. Uncaught exceptions are also logged to the configured Discord error-log channel with a full traceback attached.

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

Built by Vireon Noctis & real on discord

Lunar Bot V3
Made with ♥ and a soul.
