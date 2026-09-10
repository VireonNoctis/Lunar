from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from pathlib import Path
from typing import Optional

import aiohttp
import discord

try:

    import redis.asyncio as aioredis

except ImportError:

    aioredis = None

from discord import app_commands
from discord.ext import commands, tasks

from cogs.utilities.database import db
from cogs.utilities.emoji import EMOJI
from cogs.commands.linkaccount import LinkUsernameModal


# ============================================================
# CONFIG
# ============================================================

TOKEN = os.getenv("TOKEN")

if not TOKEN:
    raise RuntimeError(
        "TOKEN environment variable is not set."
    )


COGS_DIR = Path("./cogs")

SCAN_INTERVAL = 1.0

GUILD_ID = 1330574273760465029
STATUS_CHANNEL_ID = 1519023423383277778

LUNAR_WEBSITE = "https://lunarx.to"
LUNAR_API = "https://api.lunarx.to"

WEBSITE_CHECK_INTERVAL = 5 * 60
PRESENCE_INTERVAL = 10

HTTP_TIMEOUT = aiohttp.ClientTimeout(
    total=15,
    connect=5,
    sock_connect=5,
    sock_read=10,
)

# Dashboard integration (optional). When DASHBOARD_API is set the
# bot reports audit events, usage and status to the dashboard backend.
DASHBOARD_API = os.getenv("DASHBOARD_API")

# Redis pub/sub channels used by the dashboard backend.
REDIS_URL = os.getenv("REDIS_URL")

FEATURES_CHANNEL = "lunar:features"
CONTROL_CHANNEL = "lunar:control"

FEATURE_MAPPING_PATH = Path(
    os.getenv(
        "FEATURE_MAPPING_PATH",
        "./feature_mapping.json",
    )
)

if not FEATURE_MAPPING_PATH.exists():

    FEATURE_MAPPING_PATH = Path(
        "./dashboard/feature_mapping.json"
    )

BOT_STARTED_AT = time.monotonic()


# ============================================================
# OWNERS
# ============================================================

OWNERS = {
    1419744000977403994,
    960946185768685618,
}


# ============================================================
# MAINTENANCE
# ============================================================

MAINTENANCE_VARIABLE = "bot_maintenance"

DEVELOPER_COMMANDS = {
    "debug",
    "logs",
    "cache",
    "database",
    "shard",
    "maintenance",
}


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format=(
        "%(asctime)s | "
        "%(levelname)s | "
        "%(name)s | "
        "%(message)s"
    ),
)

logger = logging.getLogger("LunarBot")


# ============================================================
# BOT
# ============================================================

intents = discord.Intents.default()

intents.message_content = True
intents.members = True


bot = commands.Bot(
    command_prefix="!",
    intents=intents,
    status=discord.Status.idle,
)


# Runtime maintenance state.
#
# The persistent source of truth is ScyllaDB.
# These values are loaded during startup and then updated
# by /maintenance.
#
bot.maintenance_mode = False
bot.maintenance_reason = ""


# ============================================================
# STATE
# ============================================================

loaded_cogs: dict[str, float] = {}

# Cog modules the dashboard has explicitly disabled. The cog
# watcher skips these so disabled features stay unloaded.
disabled_cogs: set[str] = set()

# Feature name -> {cogs, description, toggle_maintenance} loaded
# from dashboard/feature_mapping.json.
feature_mapping: dict[str, dict[str, object]] = {}

tree_sync_lock = asyncio.Lock()

latest_status: dict[str, object] = {
    "website_status": None,
    "website_latency": None,
    "website_error": None,
    "api_status": None,
    "api_latency": None,
    "api_error": None,
}

presence_index = 0


# ============================================================
# DASHBOARD REPORTING
# ============================================================

_dashboard_session: Optional[aiohttp.ClientSession] = None


def _load_feature_mapping() -> dict[str, dict[str, object]]:

    try:

        with FEATURE_MAPPING_PATH.open(
            encoding="utf-8"
        ) as file:

            data = json.load(file)

        if isinstance(data, dict):

            logger.info(
                "Loaded %d feature mapping(s) from %s",
                len(data),
                FEATURE_MAPPING_PATH,
            )

            return data

    except Exception:

        logger.exception(
            "Failed to load feature mapping from %s.",
            FEATURE_MAPPING_PATH,
        )

    return {}


async def _dashboard_post(
    path: str,
    payload: dict,
) -> None:
    """POST a JSON payload to the dashboard backend (best effort)."""

    if not DASHBOARD_API:
        return

    global _dashboard_session

    try:

        if (
            _dashboard_session is None
            or _dashboard_session.closed
        ):

            _dashboard_session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(
                    total=5,
                    connect=3,
                ),
            )

        async with _dashboard_session.post(
            f"{DASHBOARD_API}{path}",
            json=payload,
            headers={
                "User-Agent": "LunarDiscordBot/1.0",
            },
        ) as response:

            if response.status >= 400:

                logger.warning(
                    "Dashboard POST %s failed: %s",
                    path,
                    response.status,
                )

    except Exception:

        logger.debug(
            "Dashboard POST %s unavailable.",
            path,
        )


async def report_audit(
    action: str,
    target: str,
    details: Optional[dict] = None,
) -> None:
    """Record an audit event in the dashboard backend."""

    await _dashboard_post(
        "/api/audit",
        {
            "actor_id": "bot",
            "action": action,
            "target": target,
            "details": details or {},
        },
    )


async def report_usage(
    command: str,
    guild_id: Optional[int] = None,
    user_id: Optional[int] = None,
) -> None:
    """Report a command usage event to the dashboard."""

    await _dashboard_post(
        "/api/usage",
        {
            "command": command,
            "guild_id": (
                str(guild_id)
                if guild_id
                else None
            ),
            "user_id": (
                str(user_id)
                if user_id
                else None
            ),
        },
    )


async def report_bot_status() -> None:
    """Report current bot health/status to the dashboard."""

    await _dashboard_post(
        "/api/bot/status",
        {
            "uptime_seconds": int(
                time.monotonic() - BOT_STARTED_AT
            ),
            "latency_ms": round(
                bot.latency * 1000
            ),
            "guild_count": len(bot.guilds),
            "user_count": sum(
                guild.member_count or 0
                for guild in bot.guilds
            ),
            "loaded_cogs": sorted(
                bot.cogs.keys()
            ),
            "maintenance_mode": bool(
                getattr(
                    bot,
                    "maintenance_mode",
                    False,
                )
            ),
        },
    )


async def report_error(
    message: str,
    *,
    level: str = "ERROR",
    logger_name: Optional[str] = None,
    cog: Optional[str] = None,
    traceback_text: Optional[str] = None,
) -> None:
    """Report an error to the dashboard error feed."""

    await _dashboard_post(
        "/api/errors",
        {
            "level": level,
            "logger": logger_name or "LunarBot",
            "message": message,
            "cog": cog,
            "traceback": traceback_text,
        },
    )


# ============================================================
# DASHBOARD LISTENER (REDIS)
# ============================================================

async def _apply_feature(
    feature: dict,
) -> None:
    """Apply a dashboard feature update (load/unload cogs)."""

    name = str(
        feature.get("name", "")
    ).strip()

    enabled = bool(
        feature.get("enabled_globally", False)
    )

    entry = feature_mapping.get(name)

    if entry is None:

        logger.info(
            "No cog mapping for feature: %s",
            name,
        )

        return

    modules = entry.get("cogs", [])

    if entry.get("toggle_maintenance"):

        bot.maintenance_mode = enabled

        bot.maintenance_reason = str(
            feature.get("description", "")
        )

        logger.info(
            "Maintenance mode set to %s via dashboard.",
            enabled,
        )

    for module in modules:

        module_name = str(module)

        if enabled:

            disabled_cogs.discard(module_name)

            if module_name not in bot.extensions:

                await load_cog(module_name)

        else:

            disabled_cogs.add(module_name)

            if module_name in bot.extensions:

                await unload_cog(module_name)

    if bot.is_ready():

        await sync_commands()

    await report_audit(
        "feature_update",
        name,
        {
            "enabled_globally": enabled,
            "modules": list(modules),
        },
    )


async def _handle_feature_message(
    payload: dict,
) -> None:
    """Handle a feature message from the dashboard."""

    action = str(
        payload.get("action", "")
    )

    feature = payload.get("feature")

    if action in (
        "upsert",
        "sync",
    ) and isinstance(feature, dict):

        await _apply_feature(feature)

        return

    logger.info(
        "Unhandled feature message: %s",
        payload,
    )


async def _handle_control(
    payload: dict,
) -> None:
    """Handle a control action published by the dashboard backend."""

    action = str(
        payload.get("action", "")
    )

    actor_id = payload.get("actor_id")

    reason = str(
        payload.get("reason", "")
    )

    # Safety: sensitive control actions require an owner actor_id.
    if action in (
        "shutdown",
        "restart",
    ):

        try:

            actor_id_int = int(actor_id or 0)

        except (TypeError, ValueError):

            actor_id_int = 0

        if actor_id_int not in OWNERS:

            logger.warning(
                "Ignoring control action %s from non-owner: %s",
                action,
                actor_id,
            )

            return

    logger.warning(
        "Control action received: %s | actor=%s | reason=%s",
        action,
        actor_id,
        reason,
    )

    await report_audit(
        f"control_{action}",
        "bot",
        {
            "actor_id": actor_id,
            "reason": reason,
        },
    )

    if action == "shutdown":

        await graceful_shutdown()

    elif action == "restart":

        bot._restart_requested = True

        await graceful_shutdown()

    elif action == "reload":

        for module in list(
            bot.extensions
        ):

            await reload_cog(module)

        await sync_commands()


async def graceful_shutdown() -> None:
    """Stop background tasks and close the bot cleanly."""

    logger.warning(
        "Graceful shutdown requested via dashboard."
    )

    for task_name in (
        "cog_watcher",
        "website_status_monitor",
        "rotating_presence",
    ):

        task = globals().get(task_name)

        if task is not None and task.is_running():

            task.cancel()

    await bot.close()


async def sync_features_from_dashboard() -> None:
    """Pull current feature flags from the dashboard on startup."""

    if not DASHBOARD_API:
        return

    try:

        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(
                total=5,
                connect=3,
            ),
        ) as session:

            async with session.get(
                f"{DASHBOARD_API}/api/features"
            ) as response:

                if response.status != 200:

                    return

                features = await response.json()

        for feature in features:

            if isinstance(feature, dict):

                await _apply_feature(feature)

    except Exception:

        logger.debug(
            "Could not sync features from dashboard."
        )


@tasks.loop(seconds=5.0)
async def dashboard_listener():
    """Subscribe to dashboard Redis channels for features/control."""

    if aioredis is None:

        logger.warning(
            "redis package not installed; "
            "dashboard listener disabled."
        )

        dashboard_listener.cancel()

        return

    redis_client = None

    try:

        redis_client = aioredis.from_url(
            REDIS_URL or "redis://localhost:6379/0",
            decode_responses=True,
        )

        pubsub = redis_client.pubsub()

        await pubsub.subscribe(
            FEATURES_CHANNEL,
            CONTROL_CHANNEL,
        )

        logger.info(
            "Dashboard listener subscribed to %s, %s",
            FEATURES_CHANNEL,
            CONTROL_CHANNEL,
        )

        async for message in pubsub.listen():

            if (
                message is None
                or message.get("type") != "message"
            ):

                continue

            channel = str(
                message.get("channel", "")
            )

            raw = message.get("data")

            try:

                payload = json.loads(raw)

            except (TypeError, ValueError):

                logger.warning(
                    "Invalid JSON on %s: %r",
                    channel,
                    raw,
                )

                continue

            try:

                if channel == FEATURES_CHANNEL:

                    await _handle_feature_message(payload)

                elif channel == CONTROL_CHANNEL:

                    await _handle_control(payload)

            except Exception:

                logger.exception(
                    "Error handling dashboard message: %s",
                    channel,
                )

    except asyncio.CancelledError:

        raise

    except Exception:

        logger.exception(
            "Dashboard listener error."
        )

    finally:

        if redis_client is not None:

            await redis_client.aclose()


@dashboard_listener.before_loop
async def before_dashboard_listener():

    await bot.wait_until_ready()


# ============================================================
# MAINTENANCE STATE
# ============================================================

async def load_maintenance_state() -> None:
    """
    Load the persistent maintenance state from ScyllaDB.

    Stored in:

        variables
        identifier = bot_maintenance
    """

    try:

        row = await db.variables.get(
            MAINTENANCE_VARIABLE
        )

        if row is None:

            bot.maintenance_mode = False
            bot.maintenance_reason = ""

            logger.info(
                "Maintenance state: disabled "
                "(no persistent state found)."
            )

            return

        if row.int_value is not None:

            bot.maintenance_mode = (
                int(row.int_value) == 1
            )

        else:

            bot.maintenance_mode = (
                str(
                    row.string_value or ""
                ).strip().lower()
                in {
                    "1",
                    "true",
                    "enabled",
                    "enable",
                    "on",
                }
            )

        bot.maintenance_reason = (
            row.string_value or ""
        )

        logger.info(
            "Maintenance state loaded: %s | reason=%s",
            (
                "ENABLED"
                if bot.maintenance_mode
                else "DISABLED"
            ),
            bot.maintenance_reason or "None",
        )

    except Exception:

        logger.exception(
            "Failed to load maintenance state."
        )

        # Fail open so a bad maintenance record does not
        # accidentally disable the entire bot.
        bot.maintenance_mode = False
        bot.maintenance_reason = ""


# ============================================================
# ACCOUNT LINK REQUIRED VIEW
# ============================================================

class LinkRequiredView(discord.ui.View):
    """
    Shown when a user attempts to use a command without
    having a verified Lunar account linked to Discord.
    """

    def __init__(self):
        super().__init__(
            timeout=120
        )

    @discord.ui.button(
        label="Link Lunar Account",
        style=discord.ButtonStyle.primary,
        emoji="🔗",
    )
    async def link_account(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:

        # Find the already-loaded LinkAccount cog.
        cog = bot.get_cog("LinkAccount")

        if cog is None:
            await interaction.response.send_message(
                (
                    f"{EMOJI['error']} "
                    "The account linking system is currently unavailable."
                ),
                ephemeral=True,
            )
            return

        # Open the exact same modal used by /link.
        await interaction.response.send_modal(
            LinkUsernameModal(cog)
        )

    @discord.ui.button(
        label="Cancel",
        style=discord.ButtonStyle.secondary,
        emoji="✖️",
    )
    async def cancel(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:

        await interaction.response.edit_message(
            content=None,
            embed=discord.Embed(
                title=(
                    f"{EMOJI['denied']} "
                    "Action Cancelled"
                ),
                description=(
                    "You must link your Lunar Anime account "
                    "before you can use this command."
                ),
                color=discord.Color.dark_grey(),
            ),
            view=None,
        )

    async def on_timeout(self) -> None:
        for item in self.children:
            item.disabled = True


# ============================================================
# GLOBAL APPLICATION COMMAND CHECK
# ============================================================

@bot.tree.interaction_check
async def global_interaction_check(
    interaction: discord.Interaction,
) -> bool:
    """
    Global gate for every slash command.

    Priority:
        1. Owners bypass everything.
        2. Developer commands are owner-only.
        3. Maintenance blocks normal commands.
        4. /link is always accessible.
        5. User must have a verified Lunar account.
        6. Otherwise allow execution.
    """

    user_id = interaction.user.id

    command = interaction.command

    command_name = (
        command.name
        if command is not None
        else None
    )

    # --------------------------------------------------------
    # OWNER BYPASS
    # --------------------------------------------------------

    if user_id in OWNERS:
        return True

    # --------------------------------------------------------
    # LINK COMMAND BYPASS
    # --------------------------------------------------------
    #
    # Users obviously need to be able to execute /link
    # while unlinked, otherwise the system would deadlock.
    #

    if command_name == "link":
        return True

    # --------------------------------------------------------
    # DEVELOPER COMMANDS
    # --------------------------------------------------------

    if command_name in DEVELOPER_COMMANDS:

        try:
            await interaction.response.send_message(
                (
                    f"{EMOJI['denied']} "
                    "You do not have access to the "
                    "Lunar Developer Console."
                ),
                ephemeral=True,
            )

        except discord.HTTPException:
            pass

        return False

    # --------------------------------------------------------
    # MAINTENANCE MODE
    # --------------------------------------------------------

    if getattr(
        bot,
        "maintenance_mode",
        False,
    ):

        reason = (
            getattr(
                bot,
                "maintenance_reason",
                None,
            )
            or "Maintenance is currently in progress."
        )

        try:
            await interaction.response.send_message(
                (
                    f"{EMOJI['loading']} "
                    "**Lunar is currently under maintenance.**\n\n"
                    f"{EMOJI['question']} "
                    f"**Reason:** {reason}"
                ),
                ephemeral=True,
            )

        except discord.HTTPException:
            pass

        return False

    # --------------------------------------------------------
    # ACCOUNT LINK CHECK
    # --------------------------------------------------------

    try:
        verified = await db.account_links.is_verified(
            user_id
        )

    except Exception:
        logger.exception(
            "Failed to check account link status for %s.",
            user_id,
        )

        try:
            await interaction.response.send_message(
                (
                    f"{EMOJI['error']} "
                    "**Unable to verify your Lunar account.**\n\n"
                    "Please try again in a moment."
                ),
                ephemeral=True,
            )

        except discord.HTTPException:
            pass

        return False

    # --------------------------------------------------------
    # NOT LINKED
    # --------------------------------------------------------

    if not verified:

        embed = discord.Embed(
            title=(
                f"{EMOJI['denied']} "
                "Lunar Account Required"
            ),
            description=(
                "You must link and verify your "
                "**Lunar Anime account** before using "
                "Lunar commands.\n\n"
                f"{EMOJI['lunar']} "
                "Click **Link Lunar Account** below to "
                "start the linking process."
            ),
            color=discord.Color.blurple(),
        )

        embed.set_footer(
            text="Lunar Account Verification"
        )

        try:
            await interaction.response.send_message(
                embed=embed,
                view=LinkRequiredView(),
                ephemeral=True,
            )

        except discord.HTTPException:
            pass

        return False

    # --------------------------------------------------------
    # ALLOW
    # --------------------------------------------------------

    return True



# ============================================================
# HTTP STATUS
# ============================================================

async def fetch_status(
    session: aiohttp.ClientSession,
    url: str,
) -> tuple[
    int | None,
    float | None,
    str | None,
]:

    started = (
        asyncio.get_running_loop().time()
    )

    try:

        async with session.get(
            url,
            allow_redirects=True,
        ) as response:

            elapsed = (
                asyncio.get_running_loop().time()
                - started
            ) * 1000

            return (
                response.status,
                round(
                    elapsed,
                    2,
                ),
                None,
            )

    except Exception as exc:

        elapsed = (
            asyncio.get_running_loop().time()
            - started
        ) * 1000

        return (
            None,
            round(
                elapsed,
                2,
            ),
            str(exc),
        )


async def get_lunar_status() -> dict[str, object]:

    async with aiohttp.ClientSession(
        timeout=HTTP_TIMEOUT,
    ) as session:

        website_task = fetch_status(
            session,
            LUNAR_WEBSITE,
        )

        api_task = fetch_status(
            session,
            LUNAR_API,
        )

        website, api = await asyncio.gather(
            website_task,
            api_task,
        )

    return {
        "website_status": website[0],
        "website_latency": website[1],
        "website_error": website[2],

        "api_status": api[0],
        "api_latency": api[1],
        "api_error": api[2],
    }


async def refresh_lunar_status():

    global latest_status

    try:

        latest_status = (
            await get_lunar_status()
        )

        logger.info(
            (
                "Lunar status refreshed | "
                "Website=%s | API=%s"
            ),
            latest_status[
                "website_status"
            ],
            latest_status[
                "api_status"
            ],
        )

        return latest_status

    except Exception:

        logger.exception(
            "Failed to refresh Lunar status."
        )

        return latest_status


# ============================================================
# STATUS HELPERS
# ============================================================

def status_text(
    status: int | None,
) -> str:

    if status == 200:
        return "Up"

    if status is None:
        return "Unknown"

    return "Down"


def status_emoji(
    status: int | None,
) -> str:

    if status == 200:
        return EMOJI["approved"]

    if status is None:
        return EMOJI["question"]

    return EMOJI["denied"]


# ============================================================
# STATUS EMBED
# ============================================================

def build_status_embed(
    status: dict[str, object],
) -> discord.Embed:

    website_status = status[
        "website_status"
    ]

    website_latency = status[
        "website_latency"
    ]

    website_error = status[
        "website_error"
    ]

    api_status = status[
        "api_status"
    ]

    api_latency = status[
        "api_latency"
    ]

    api_error = status[
        "api_error"
    ]

    website_online = (
        website_status == 200
    )

    api_online = (
        api_status == 200
    )

    everything_online = (
        website_online
        and api_online
    )

    embed = discord.Embed(
        title=(
            f"{EMOJI['moon']} "
            "Lunar System Status"
        ),
        color=(
            discord.Color.green()
            if everything_online
            else discord.Color.red()
        ),
        timestamp=discord.utils.utcnow(),
    )

    website_value = (
        f"{status_emoji(website_status)} "
        f"`{website_status}` | "
        f"**{status_text(website_status)}**"
    )

    if website_latency is not None:

        website_value += (
            f"\n{EMOJI['loading']} "
            f"`{website_latency}ms`"
        )

    if website_error:

        website_value += (
            f"\n{EMOJI['error']} "
            f"`{website_error[:250]}`"
        )

    api_value = (
        f"{status_emoji(api_status)} "
        f"`{api_status}` | "
        f"**{status_text(api_status)}**"
    )

    if api_latency is not None:

        api_value += (
            f"\n{EMOJI['loading']} "
            f"`{api_latency}ms`"
        )

    if api_error:

        api_value += (
            f"\n{EMOJI['error']} "
            f"`{api_error[:250]}`"
        )

    embed.add_field(
        name=(
            f"{EMOJI['lunar']} "
            "Website"
        ),
        value=website_value,
        inline=False,
    )

    embed.add_field(
        name=(
            f"{EMOJI['dev']} "
            "API"
        ),
        value=api_value,
        inline=False,
    )

    embed.set_footer(
        text="Lunar Infrastructure Monitor"
    )

    return embed


# ============================================================
# WEBSITE MONITOR
# ============================================================

@tasks.loop(minutes=5)
async def website_status_monitor():

    try:

        status = (
            await refresh_lunar_status()
        )

        guild = bot.get_guild(
            GUILD_ID
        )

        if guild is None:

            logger.warning(
                "Status monitor: guild %s not found.",
                GUILD_ID,
            )

            return

        channel = guild.get_channel(
            STATUS_CHANNEL_ID
        )

        if channel is None:

            try:

                channel = (
                    await guild.fetch_channel(
                        STATUS_CHANNEL_ID
                    )
                )

            except Exception:

                logger.exception(
                    "Could not fetch status channel %s.",
                    STATUS_CHANNEL_ID,
                )

                return

        if not isinstance(
            channel,
            discord.TextChannel,
        ):

            logger.warning(
                "Status channel %s is not a text channel.",
                STATUS_CHANNEL_ID,
            )

            return

        await channel.send(
            embed=build_status_embed(
                status
            )
        )

    except Exception:

        logger.exception(
            "Website status monitor failed."
        )


@website_status_monitor.before_loop
async def before_website_status_monitor():

    await bot.wait_until_ready()


# ============================================================
# ROTATING WATCHING PRESENCE
# ============================================================

@tasks.loop(seconds=PRESENCE_INTERVAL)
async def rotating_presence():

    global presence_index

    website_status = latest_status[
        "website_status"
    ]

    api_status = latest_status[
        "api_status"
    ]

    if presence_index == 0:

        state = status_text(
            website_status
        )

        activity_name = (
            f"{EMOJI['lunar']} "
            f"Website • {state}"
        )

    else:

        state = status_text(
            api_status
        )

        activity_name = (
            f"{EMOJI['dev']} "
            f"API • {state}"
        )

    try:

        await bot.change_presence(
            status=discord.Status.idle,
            activity=discord.Activity(
                type=(
                    discord.ActivityType.watching
                ),
                name=activity_name,
            ),
        )

        logger.debug(
            "Presence updated: Watching %s",
            activity_name,
        )

    except Exception:

        logger.exception(
            "Failed to update bot presence."
        )

    presence_index = (
        presence_index + 1
    ) % 2


@rotating_presence.before_loop
async def before_rotating_presence():

    await bot.wait_until_ready()

    await refresh_lunar_status()


# ============================================================
# COG DISCOVERY
# ============================================================

def discover_cogs() -> dict[
    str,
    tuple[Path, float],
]:

    discovered: dict[
        str,
        tuple[Path, float],
    ] = {}

    if not COGS_DIR.exists():

        COGS_DIR.mkdir(
            parents=True,
            exist_ok=True,
        )

    for file in COGS_DIR.rglob(
        "*.py"
    ):

        if file.name.startswith(
            "_"
        ):
            continue

        relative = file.relative_to(
            Path(".")
        )

        # Utilities are not Discord extensions.
        if "utilities" in relative.parts:
            continue

        module = str(
            relative.with_suffix("")
        ).replace(
            os.sep,
            ".",
        )

        discovered[module] = (
            file,
            file.stat().st_mtime,
        )

    return discovered


# ============================================================
# COMMAND SYNC
# ============================================================

async def sync_commands():

    async with tree_sync_lock:

        try:

            synced = (
                await bot.tree.sync()
            )

            logger.info(
                "Synced %d slash command(s).",
                len(synced),
            )

        except Exception:

            logger.exception(
                "Failed to sync slash commands."
            )


# ============================================================
# COG LOADING
# ============================================================

async def load_cog(
    module: str,
):

    try:

        await bot.load_extension(
            module
        )

        logger.info(
            "Loaded cog: %s",
            module,
        )

    except commands.ExtensionAlreadyLoaded:

        logger.debug(
            "Cog already loaded: %s",
            module,
        )

    except Exception:

        logger.exception(
            "Failed to load cog: %s",
            module,
        )


async def reload_cog(
    module: str,
):

    try:

        await bot.reload_extension(
            module
        )

        logger.info(
            "Reloaded cog: %s",
            module,
        )

    except commands.ExtensionNotLoaded:

        logger.warning(
            (
                "Cog %s was not loaded, "
                "attempting to load it."
            ),
            module,
        )

        await load_cog(
            module
        )

    except Exception:

        logger.exception(
            "Failed to reload cog: %s",
            module,
        )


async def unload_cog(
    module: str,
):

    try:

        await bot.unload_extension(
            module
        )

        logger.info(
            "Unloaded cog: %s",
            module,
        )

    except commands.ExtensionNotLoaded:

        pass

    except Exception:

        logger.exception(
            "Failed to unload cog: %s",
            module,
        )


# ============================================================
# COG WATCHER
# ============================================================

@tasks.loop(seconds=SCAN_INTERVAL)
async def cog_watcher():

    try:

        discovered = discover_cogs()

        changed = False

        # ----------------------------------------------------
        # NEW / MODIFIED COGS
        # ----------------------------------------------------

        for module, (
            _,
            modified_time,
        ) in discovered.items():

            # Skip modules the dashboard has explicitly disabled.
            if module in disabled_cogs:
                continue

            if module not in loaded_cogs:

                await load_cog(
                    module
                )

                loaded_cogs[
                    module
                ] = modified_time

                changed = True

                continue

            old_modified_time = (
                loaded_cogs[
                    module
                ]
            )

            if (
                modified_time
                != old_modified_time
            ):

                await reload_cog(
                    module
                )

                loaded_cogs[
                    module
                ] = modified_time

                changed = True

        # ----------------------------------------------------
        # DELETED COGS
        # ----------------------------------------------------

        deleted = (
            set(loaded_cogs)
            - set(discovered)
        )

        for module in deleted:

            await unload_cog(
                module
            )

            loaded_cogs.pop(
                module,
                None,
            )

            changed = True

        # ----------------------------------------------------
        # SYNC
        # ----------------------------------------------------

        if (
            changed
            and bot.is_ready()
        ):

            await sync_commands()

    except Exception:

        logger.exception(
            "Error while watching cogs."
        )


@cog_watcher.before_loop
async def before_cog_watcher():

    await bot.wait_until_ready()


# ============================================================
# COMMAND USAGE TRACKER
# ============================================================

@bot.listen(
    "on_app_command_completion"
)
async def command_usage_tracker(
    interaction: discord.Interaction,
    command: app_commands.Command,
):

    try:

        await db.command_stats.increment(
            command.qualified_name
        )

        await report_usage(
            command.qualified_name,
            guild_id=(
                interaction.guild_id
                if interaction.guild_id
                else None
            ),
            user_id=(
                interaction.user.id
                if interaction.user is not None
                else None
            ),
        )

    except Exception:

        # Command statistics must never
        # break an otherwise successful command.
        logger.exception(
            "Failed to record command usage: %s",
            getattr(
                command,
                "qualified_name",
                "unknown",
            ),
        )


# ============================================================
# PING COMMAND
# ============================================================

@bot.tree.command(
    name="ping",
    description=(
        "Check the bot, Lunar website "
        "and API status."
    ),
)
async def ping(
    interaction: discord.Interaction,
):

    await interaction.response.send_message(
        (
            f"{EMOJI['loading']} "
            "Checking Lunar systems..."
        ),
        ephemeral=True,
    )

    await asyncio.sleep(
        1
    )

    bot_latency = round(
        bot.latency * 1000
    )

    try:

        status = (
            await refresh_lunar_status()
        )

        website_status = status[
            "website_status"
        ]

        website_latency = status[
            "website_latency"
        ]

        api_status = status[
            "api_status"
        ]

        api_latency = status[
            "api_latency"
        ]

        website_online = (
            website_status == 200
        )

        api_online = (
            api_status == 200
        )

        overall_online = (
            website_online
            and api_online
        )

        embed = discord.Embed(
            title=(
                f"{EMOJI['lunar']} "
                "Lunar Ping"
            ),
            description=(
                f"{EMOJI['approved']} "
                "**Lunar systems have been checked.**"
            ),
            color=(
                discord.Color.green()
                if overall_online
                else discord.Color.red()
            ),
        )

        embed.add_field(
            name=(
                f"{EMOJI['moon']} "
                "Discord Gateway"
            ),
            value=(
                f"{EMOJI['approved']} "
                f"`{bot_latency}ms`\n"
                "**Up**"
            ),
            inline=True,
        )

        website_latency_text = (
            f"`{website_latency}ms`"
            if website_latency is not None
            else "`N/A`"
        )

        embed.add_field(
            name=(
                f"{EMOJI['lunar']} "
                "Website"
            ),
            value=(
                f"{status_emoji(website_status)} "
                f"`{website_status}`\n"
                f"**{status_text(website_status)}** "
                f"• {website_latency_text}"
            ),
            inline=True,
        )

        api_latency_text = (
            f"`{api_latency}ms`"
            if api_latency is not None
            else "`N/A`"
        )

        embed.add_field(
            name=(
                f"{EMOJI['dev']} "
                "API"
            ),
            value=(
                f"{status_emoji(api_status)} "
                f"`{api_status}`\n"
                f"**{status_text(api_status)}** "
                f"• {api_latency_text}"
            ),
            inline=True,
        )

        embed.set_footer(
            text=(
                "Lunar Infrastructure • Live Check"
            )
        )

        await interaction.edit_original_response(
            content=None,
            embed=embed,
        )

    except Exception as exc:

        logger.exception(
            "Ping status check failed."
        )

        error_embed = discord.Embed(
            title=(
                f"{EMOJI['error']} "
                "Lunar Ping"
            ),
            description=(
                f"{EMOJI['denied']} "
                "The bot is online, but the external "
                "status check failed."
            ),
            color=discord.Color.red(),
        )

        error_embed.add_field(
            name="Error",
            value=(
                f"`{str(exc)[:1000]}`"
            ),
            inline=False,
        )

        await interaction.edit_original_response(
            content=None,
            embed=error_embed,
        )


# ============================================================
# EVENTS
# ============================================================

@bot.event
async def on_ready():

    logger.info(
        "Logged in as %s (%s)",
        bot.user,
        bot.user.id,
    )

    # Keep the bot Idle.
    await bot.change_presence(
        status=discord.Status.idle,
        activity=discord.Activity(
            type=discord.ActivityType.watching,
            name=(
                f"{EMOJI['lunar']} "
                "Website • Checking"
            ),
        ),
    )

    await sync_commands()

    if not cog_watcher.is_running():

        cog_watcher.start()

    if not website_status_monitor.is_running():

        website_status_monitor.start()

    if not rotating_presence.is_running():

        rotating_presence.start()

    # Live dashboard feed (feature toggles, control actions).
    if REDIS_URL and aioredis is not None:

        if not dashboard_listener.is_running():

            dashboard_listener.start()

    await report_bot_status()


# ============================================================
# STARTUP
# ============================================================

async def main():

    global feature_mapping

    COGS_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    feature_mapping = _load_feature_mapping()

    # --------------------------------------------------------
    # Database first
    # --------------------------------------------------------

    await db.initialize()

    # --------------------------------------------------------
    # Restore persistent maintenance state
    # BEFORE Discord starts accepting commands.
    # --------------------------------------------------------

    await load_maintenance_state()

    # --------------------------------------------------------
    # Apply current dashboard feature flags so toggles made
    # while the bot was offline take effect on startup.
    # --------------------------------------------------------

    await sync_features_from_dashboard()

    try:

        restart = True

        while restart:

            restart = False

            try:

                async with bot:

                    await bot.start(
                        TOKEN
                    )

            finally:

                await report_audit(
                    "bot_shutdown",
                    "bot",
                    {
                        "reason": (
                            "restart requested via dashboard"
                            if getattr(
                                bot,
                                "_restart_requested",
                                False,
                            )
                            else "shutdown"
                        ),
                    },
                )

                if _dashboard_session is not None:

                    await _dashboard_session.close()

                restart = bool(
                    getattr(
                        bot,
                        "_restart_requested",
                        False,
                    )
                )

                bot._restart_requested = False

    finally:

        await db.close()


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":

    asyncio.run(
        main()
    )