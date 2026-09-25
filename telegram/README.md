# Telegram Bots

This folder contains the Lunar family's standalone Telegram bots, built with
[`python-telegram-bot`](https://github.com/python-telegram-bot/python-telegram-bot).

Each bot is a **single-file, self-contained script**:

- Its own Telegram bot token
- Its own process (run with `python3 <file>.py`)
- Its own JSON data file for persistence
- No `.env` file — configuration is a `Config` dataclass at the top of the script

They do not share state and can be run side by side on the same machine without
conflicting with one another.

| Bot | File | Purpose |
|---|---|---|
| **Lunar** | [`lunar.py`](./lunar.py) | General-purpose / fun bot — games, utilities, external API lookups |
| **Nova** | [`nova.py`](./nova.py) | Bridges Telegram to the Lunar website — XP, leaderboard, account linking, search |
| **Sapphire** | [`sapphire.py`](./sapphire.py) | Group moderation bot — bans, warns, filters, anti-spam, logging |
| **Giveaways** | *(not yet added)* | Planned Telegram giveaways bot — currently incomplete and not included in this folder |

---

## Requirements

All bots require Python 3.10+ and `python-telegram-bot`. Some need extra packages:

```bash
# Lunar
pip install python-telegram-bot httpx

# Nova
pip install "python-telegram-bot[job-queue]" httpx pillow

# Sapphire
pip install "python-telegram-bot[job-queue]"
```

`[job-queue]` is required by Nova and Sapphire for scheduled/background tasks
(XP announcements, captcha timeouts, scheduled broadcasts, periodic data flushes).
Without it, the bot still runs, but those features are disabled and a warning is
logged on startup.

---

## Configuration

None of these bots read a `.env` file. Instead, open the script and edit the
`Config` dataclass near the top before running it:

```python
@dataclass
class Config:
    token: str = "PUT_YOUR_BOT_TOKEN_HERE"   # <-- get this from @BotFather
    owner_id: int = 0                         # <-- your numeric Telegram user ID
    ...
```

- `token` — the bot token from [@BotFather](https://t.me/BotFather). The bot will
  refuse to start (Sapphire) or fail to authenticate (Lunar/Nova) until this is set.
- `owner_id` — your numeric Telegram user ID, used for owner-only commands and
  super-admin overrides. Leaving it at `0` disables those checks/features.

**Never commit a script with a real token filled in.**

---

## Lunar — `lunar.py`

General-purpose bot: quick utilities, provably-fair random/fun commands, and a
handful of external API lookups. Every random outcome (`roll`, `flip`, `choose`,
etc.) is drawn from `secrets` (OS CSPRNG) rather than the standard `random`
module.

**Run:**

```bash
python3 lunar.py
```

**Data file:** `lunar_bot_users.json` (silently registers/tracks users and
groups the bot has seen — no setup required).

**Commands:**

| Category | Commands |
|---|---|
| Info | `/help` `/about` `/ping` `/id` `/time` |
| Utility | `/echo` `/calc` `/reverse` |
| Fun / CSPRNG | `/roll` `/flip` `/choose` `/8ball` `/rate` `/ship` `/joke` `/fact` `/quote` |
| External APIs | `/weather` `/crypto` `/define` `/trivia` `/advice` `/meme` `/cat` `/dog` `/qr` |
| Owner-only | `/callall` |

---

## Nova — `nova.py`

Connects Telegram to the Lunar website's API: website XP syncing, leaderboards,
account linking between Telegram and Lunar accounts, and an anime/manga search
bridge.

**Run:**

```bash
python3 nova.py
```

**Data file:** `nova_data.json`

**Additional config (Lunar API):** beyond `token` and `owner_id`, Nova's
`Config` also holds the Lunar API base URLs/endpoints and credentials:

```python
lunar_api_base: str = "https://api.lunarx.to/api"
lunar_token: str = "PUT_YOUR_LUNAR_TOKEN_HERE"
lunar_bypass_token: str = ""   # optional X-Scraper-Guard-Bypass
```

These must be filled in for XP sync, profile lookups, leaderboard, and
notification features to work against the live Lunar API.

**Commands:**

| Category | Commands |
|---|---|
| Info | `/help` `/about` `/ping` `/version` `/uptime` `/id` |
| Account linking | `/link` `/linkverify` `/unlink` |
| Lunar integration | `/level` `/leaderboard` `/search` |

---

## Sapphire — `sapphire.py`

Standalone group moderation bot — no fun/game/API-toy commands live here (that's
Lunar's job). Covers bans/mutes/warns, anti-spam & anti-flood, captcha
verification, message/content locks, welcome/goodbye/rules, filters and
blacklists, mod-action logging, activity stats, scheduled broadcasts, and
settings backup/restore.

**Run:**

```bash
python3 sapphire.py
```

**Data file:** `sapphire_data.json`, flushed to disk every 30 seconds via a
background job (requires `[job-queue]`) as well as on state-changing actions.

**Scope notes (by design):**

- No anti-porn / NSFW image detection — that requires a paid vision API
  (Google Vision, Sightengine, etc.); there's no accurate keyless alternative,
  so it's left out rather than faked with a keyword filter.
- No self-cloning into a new bot — the Bot API can't do this; it would require
  automating BotFather with a *user* account (Telethon/Pyrogram-style), which is
  out of scope here.
- Anti-flood/anti-spam trackers and pending-captcha state are **in-memory** and
  reset on restart. Everything else (settings, filters, warnings, stats,
  scheduled broadcasts) is persisted to disk and reloaded on startup.
- Night mode hours are UTC and chat-wide (no per-chat timezone config).

**Commands:**

| Category | Commands |
|---|---|
| Info | `/help` `/about` `/ping` `/version` `/uptime` `/id` `/info` `/userinfo` `/admins` |
| Punishments & warnings | `/ban` `/unban` `/kick` `/mute` `/unmute` `/unmuteall` `/tban` `/tmute` `/warn` `/unwarn` `/warnings` `/resetwarns` `/warnlist` `/setwarnlimit` `/warnaction` |
| Message & admin management | `/purge` `/del` `/pin` `/unpin` `/report` `/promote` `/demote` |
| Protection | `/captcha` `/setcaptchatype` `/setcaptchatimeout` `/antispam` `/antiflood` `/setfloodlimit` `/setfloodaction` `/nightmode` `/setnighttime` `/antiraid` `/raidmode` `/slowmode` `/slowmodeoff` |
| Locks | `/lock` `/unlock` `/locks` `/lockdown` `/unlockall` `/antilink` |
| Welcome / Goodbye / Rules | `/welcome` `/setwelcome` `/resetwelcome` `/cleanwelcome` `/goodbye` `/setgoodbye` `/resetgoodbye` `/rules` `/setrules` `/resetrules` |
| Filters & custom commands | `/filters` `/addfilter` `/removefilter` `/stopallfilters` `/badwords` `/addbadword` `/removebadword` `/clearbadwords` `/commands` `/addcommand` `/removecommand` |
| Blacklist / Approve | `/blacklist` `/blacklistadd` `/blacklistremove` `/approve` `/unapprove` `/approved` |
| Logging | `/setlog` `/unsetlog` `/logstatus` `/logtest` |
| Stats | `/stats` `/trend` `/graphic` `/top10` `/myactivity` `/resetstats` |
| Broadcasts | `/broadcast` `/schedule` `/scheduled` `/cancelschedule` |
| Backup / config | `/exportsettings` `/importsettings` `/resetsettings` `/mutelist` `/banlist` |
| Settings menu | `/settings` (interactive button menu) |

---

## Giveaways bot *(planned, not yet included)*

A dedicated Telegram giveaways bot is planned for this folder but is currently
**incomplete** and hasn't been added yet. Once it lands, it will follow the same
pattern as the bots above (single file, own token, own data file). This
document will be updated with its details at that time.

---

## Running bots together

Since each bot is a separate script with its own token and data file, you can
run any combination of them at once, e.g.:

```bash
python3 lunar.py &
python3 nova.py &
python3 sapphire.py &
```

For production use on a VPS, run each bot as its own `systemd` service (see the
root [`README.md`](../../README.md) for a full `systemd` walkthrough for the
main Discord bot — the same pattern applies here, just pointing `ExecStart` at
the relevant Telegram bot script).

---

## Security

- Tokens live in plain code in these scripts (no `.env`) — never commit a
  filled-in token, and treat any file with a real token as a secret.
- If a token is ever exposed, regenerate it immediately via
  [@BotFather](https://t.me/BotFather).
- Data files (`lunar_bot_users.json`, `nova_data.json`, `sapphire_data.json`)
  may contain user IDs and moderation history — don't publish them.
