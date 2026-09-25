# Telegram Bots

This folder contains the Lunar family's standalone Telegram bots, built with [`python-telegram-bot`](https://github.com/python-telegram-bot/python-telegram-bot).

Each bot is a **single-file, self-contained script** with:

* Its own Telegram bot token
* Its own process (`python3 <file>.py`)
* Its own JSON data file for persistence
* No `.env` file — configuration is stored in a `Config` dataclass at the top of the script

The bots do not share state and can be run side by side on the same machine without conflicting with one another.

| Bot           | File                           | Purpose                                                                               |
| ------------- | ------------------------------ | ------------------------------------------------------------------------------------- |
| **Lunar**     | [`lunar.py`](.bots/lunar.py)       | General-purpose and fun bot — games, utilities, and external API lookups              |
| **Nova**      | [`nova.py`](.bots/nova.py)         | Bridges Telegram to the Lunar website — XP, leaderboards, account linking, and search |
| **Sapphire**  | [`sapphire.py`](.bots/sapphire.py) | Group moderation bot — bans, warnings, filters, anti-spam, and logging                |
| **Giveaways** | *Not yet added*                | Planned Telegram giveaways bot — currently incomplete and not included in this folder |

---

## Requirements

All bots require **Python 3.10+** and `python-telegram-bot`. Some bots require additional packages.

### Lunar

```bash
pip install python-telegram-bot httpx
```

### Nova

```bash
pip install "python-telegram-bot[job-queue]" httpx pillow
```

### Sapphire

```bash
pip install "python-telegram-bot[job-queue]"
```

The `[job-queue]` extra is required by **Nova** and **Sapphire** for scheduled and background tasks, including:

* XP announcements
* Captcha timeouts
* Scheduled broadcasts
* Periodic data flushes

Without `job-queue`, the bot can still start, but these features will be disabled and a warning will be logged on startup.

---

## Configuration

None of these bots read from a `.env` file.

Instead, open the relevant script and edit the `Config` dataclass near the top before running it:

```python
@dataclass
class Config:
    token: str = "PUT_YOUR_BOT_TOKEN_HERE"   # Get this from @BotFather
    owner_id: int = 0                        # Your numeric Telegram user ID
    ...
```

### Configuration fields

* **`token`** — The bot token obtained from [@BotFather](https://t.me/BotFather).

  * Sapphire refuses to start until this is configured.
  * Lunar and Nova will fail to authenticate until this is configured.
* **`owner_id`** — Your numeric Telegram user ID. Used for owner-only commands and super-admin overrides.

  * Setting this to `0` disables those checks and features.

> [!WARNING]
> **Never commit a script containing a real bot token.**

---

## Lunar — `lunar.py`

Lunar is a general-purpose bot providing quick utilities, provably-fair random/fun commands, and several external API lookups.

Every random outcome (`roll`, `flip`, `choose`, etc.) is generated using Python's `secrets` module, which uses an OS-provided CSPRNG, rather than the standard `random` module.

### Run

```bash
python3 lunar.py
```

### Data file

`lunar_bot_users.json`

The bot silently registers and tracks users and groups it has seen. No additional setup is required.

### Commands

| Category          | Commands                                                                                       |
| ----------------- | ---------------------------------------------------------------------------------------------- |
| **Info**          | `/help` · `/about` · `/ping` · `/id` · `/time`                                                 |
| **Utility**       | `/echo` · `/calc` · `/reverse`                                                                 |
| **Fun / CSPRNG**  | `/roll` · `/flip` · `/choose` · `/8ball` · `/rate` · `/ship` · `/joke` · `/fact` · `/quote`    |
| **External APIs** | `/weather` · `/crypto` · `/define` · `/trivia` · `/advice` · `/meme` · `/cat` · `/dog` · `/qr` |
| **Owner-only**    | `/callall`                                                                                     |

---

## Nova — `nova.py`

Nova connects Telegram to the Lunar website's API, providing:

* Website XP synchronization
* Leaderboards
* Account linking between Telegram and Lunar accounts
* Anime and manga search through the Lunar API

### Run

```bash
python3 nova.py
```

### Data file

`nova_data.json`

### Lunar API configuration

In addition to `token` and `owner_id`, Nova's `Config` contains the Lunar API base URLs, endpoints, and credentials:

```python
lunar_api_base: str = "https://api.lunarx.to/api"
lunar_token: str = "PUT_YOUR_LUNAR_TOKEN_HERE"
lunar_bypass_token: str = ""   # Optional X-Scraper-Guard-Bypass token
```

These values must be configured for the following features to work against the live Lunar API:

* XP synchronization
* Profile lookups
* Leaderboards
* Notifications

### Commands

| Category              | Commands                                                      |
| --------------------- | ------------------------------------------------------------- |
| **Info**              | `/help` · `/about` · `/ping` · `/version` · `/uptime` · `/id` |
| **Account linking**   | `/link` · `/linkverify` · `/unlink`                           |
| **Lunar integration** | `/level` · `/leaderboard` · `/search`                         |

---

## Sapphire — `sapphire.py`

Sapphire is a standalone Telegram group moderation bot.

It intentionally does not include fun, game, or API-toy commands — those belong to Lunar.

Sapphire provides:

* Bans, mutes, and warnings
* Anti-spam and anti-flood protection
* Captcha verification
* Message and content locks
* Welcome, goodbye, and rules messages
* Filters and blacklists
* Moderation-action logging
* Activity statistics
* Scheduled broadcasts
* Settings backup and restore

### Run

```bash
python3 sapphire.py
```

### Data file

`sapphire_data.json`

The data file is flushed to disk every **30 seconds** through a background job and is also written whenever state-changing actions occur.

> **Note:** Periodic background flushing requires the `[job-queue]` extra.

### Scope notes

The following behaviors are intentional design decisions:

* **No anti-porn / NSFW image detection** — This requires a paid vision API such as Google Vision or Sightengine. There is no accurate keyless alternative, so it is omitted rather than simulated with a keyword filter.
* **No self-cloning into a new bot** — The Telegram Bot API does not provide this functionality. Doing so would require automating BotFather with a user account using something like Telethon or Pyrogram, which is outside the scope of this bot.
* **Anti-flood/anti-spam trackers and pending captcha state are in-memory** and therefore reset when the bot restarts.
* **Persistent data** — Settings, filters, warnings, statistics, and scheduled broadcasts are persisted to disk and restored on startup.
* **Night mode** — Night mode hours use UTC and apply to the entire chat. Per-chat timezone configuration is not supported.

### Commands

| Category                       | Commands                                                                                                                                                                                                              |
| ------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Info**                       | `/help` · `/about` · `/ping` · `/version` · `/uptime` · `/id` · `/info` · `/userinfo` · `/admins`                                                                                                                     |
| **Punishments & warnings**     | `/ban` · `/unban` · `/kick` · `/mute` · `/unmute` · `/unmuteall` · `/tban` · `/tmute` · `/warn` · `/unwarn` · `/warnings` · `/resetwarns` · `/warnlist` · `/setwarnlimit` · `/warnaction`                             |
| **Message & admin management** | `/purge` · `/del` · `/pin` · `/unpin` · `/report` · `/promote` · `/demote`                                                                                                                                            |
| **Protection**                 | `/captcha` · `/setcaptchatype` · `/setcaptchatimeout` · `/antispam` · `/antiflood` · `/setfloodlimit` · `/setfloodaction` · `/nightmode` · `/setnighttime` · `/antiraid` · `/raidmode` · `/slowmode` · `/slowmodeoff` |
| **Locks**                      | `/lock` · `/unlock` · `/locks` · `/lockdown` · `/unlockall` · `/antilink`                                                                                                                                             |
| **Welcome / Goodbye / Rules**  | `/welcome` · `/setwelcome` · `/resetwelcome` · `/cleanwelcome` · `/goodbye` · `/setgoodbye` · `/resetgoodbye` · `/rules` · `/setrules` · `/resetrules`                                                                |
| **Filters & custom commands**  | `/filters` · `/addfilter` · `/removefilter` · `/stopallfilters` · `/badwords` · `/addbadword` · `/removebadword` · `/clearbadwords` · `/commands` · `/addcommand` · `/removecommand`                                  |
| **Blacklist / Approve**        | `/blacklist` · `/blacklistadd` · `/blacklistremove` · `/approve` · `/unapprove` · `/approved`                                                                                                                         |
| **Logging**                    | `/setlog` · `/unsetlog` · `/logstatus` · `/logtest`                                                                                                                                                                   |
| **Stats**                      | `/stats` · `/trend` · `/graphic` · `/top10` · `/myactivity` · `/resetstats`                                                                                                                                           |
| **Broadcasts**                 | `/broadcast` · `/schedule` · `/scheduled` · `/cancelschedule`                                                                                                                                                         |
| **Backup / Config**            | `/exportsettings` · `/importsettings` · `/resetsettings` · `/mutelist` · `/banlist`                                                                                                                                   |
| **Settings**                   | `/settings` — Interactive button menu                                                                                                                                                                                 |

---

## Giveaways Bot — Planned

A dedicated Telegram giveaways bot is planned for this folder but is currently **incomplete** and has not been added yet.

Once it is ready, it will follow the same structure as the existing bots:

* Single-file implementation
* Dedicated bot token
* Dedicated JSON data file
* Independent process and state

This document will be updated with its details when the bot is added.

---

## Running Bots Together

Because each bot is a separate script with its own token and data file, any combination of the bots can run simultaneously.

For example:

```bash
python3 lunar.py &
python3 nova.py &
python3 sapphire.py &
```

### Production / VPS

For production deployments on a VPS, run each bot as its own `systemd` service.

See the root [`README.md`](../../README.md) for the full `systemd` walkthrough for the main Discord bot. The same approach applies here, with `ExecStart` pointing to the relevant Telegram bot script.

---

## Security

* Tokens are stored directly in the scripts rather than in a `.env` file.
* **Never commit a script containing a real token.**
* Treat any file containing a real token as a secret.
* If a token is ever exposed, **regenerate it immediately** through [@BotFather](https://t.me/BotFather).
* Data files may contain sensitive information such as user IDs and moderation history. Do not publish or commit them.

The following files should be treated as private data:

```text
lunar_bot_users.json
nova_data.json
sapphire_data.json
```
