from __future__ import annotations

import io
import logging
import platform
import sys
import time

from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from cogs.utilities.database import db
from cogs.utilities.emoji import EMOJI


# ============================================================
# CONFIGURATION
# ============================================================

OWNERS = {
    1419744000977403994,
    960946185768685618,
}

COG_NAME = "Lunar System Control"

MAX_LOG_ENTRIES = 500

LOADING_DELAY = 1.40

LOG_LEVELS = {
    "all": None,
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "warning": logging.WARNING,
    "error": logging.ERROR,
    "critical": logging.CRITICAL,
}


# ============================================================
# LOGGING
# ============================================================

logger = logging.getLogger("lunar.debug")


# ============================================================
# MEMORY LOG HANDLER
# ============================================================

@dataclass(slots=True)
class StoredLog:
    timestamp: datetime
    level: int
    logger_name: str
    message: str


class MemoryLogHandler(logging.Handler):

    def __init__(
        self,
        max_entries: int = MAX_LOG_ENTRIES,
    ):
        super().__init__()

        self.entries: deque[
            StoredLog
        ] = deque(
            maxlen=max_entries
        )

    def emit(
        self,
        record: logging.LogRecord,
    ) -> None:

        try:

            message = (
                self.format(record)
            )

            self.entries.append(
                StoredLog(
                    timestamp=datetime.fromtimestamp(
                        record.created,
                        timezone.utc,
                    ),
                    level=record.levelno,
                    logger_name=record.name,
                    message=message,
                )
            )

        except Exception:

            # Logging must never break the bot.
            pass

    def recent(
        self,
        *,
        limit: int = 25,
        level: Optional[int] = None,
    ) -> list[StoredLog]:

        entries = list(
            self.entries
        )

        if level is not None:

            entries = [
                entry
                for entry in entries
                if entry.level >= level
            ]

        return entries[
            -limit:
        ]


# ============================================================
# GLOBAL MEMORY LOGGER
# ============================================================

MEMORY_HANDLER = MemoryLogHandler()

MEMORY_HANDLER.setFormatter(
    logging.Formatter(
        "%(levelname)s | %(name)s | %(message)s"
    )
)


def install_memory_handler() -> None:

    root = logging.getLogger()

    if MEMORY_HANDLER not in root.handlers:

        root.addHandler(
            MEMORY_HANDLER
        )


# ============================================================
# HELPERS
# ============================================================

def utcnow() -> datetime:
    return datetime.now(
        timezone.utc
    )


def fmt_uptime(
    seconds: float,
) -> str:

    seconds = max(
        0,
        int(seconds),
    )

    days, remainder = divmod(
        seconds,
        86400,
    )

    hours, remainder = divmod(
        remainder,
        3600,
    )

    minutes, seconds = divmod(
        remainder,
        60,
    )

    parts = []

    if days:
        parts.append(
            f"{days}d"
        )

    if hours:
        parts.append(
            f"{hours}h"
        )

    if minutes:
        parts.append(
            f"{minutes}m"
        )

    if seconds or not parts:
        parts.append(
            f"{seconds}s"
        )

    return " ".join(parts)


def fmt_dt(
    value: Optional[datetime],
) -> str:

    if value is None:
        return "Never"

    if value.tzinfo is None:
        value = value.replace(
            tzinfo=timezone.utc
        )

    return (
        f"<t:{int(value.timestamp())}:F>"
        f" • "
        f"<t:{int(value.timestamp())}:R>"
    )


def status_badge(
    healthy: Optional[bool],
) -> str:

    if healthy is True:
        return (
            f"{EMOJI['approved']} `ONLINE`"
        )

    if healthy is False:
        return (
            f"{EMOJI['denied']} `OFFLINE`"
        )

    return (
        f"{EMOJI['question']} `UNKNOWN`"
    )


def yes_no(
    value: bool,
) -> str:

    return (
        f"{EMOJI['approved']} Yes"
        if value
        else
        f"{EMOJI['denied']} No"
    )


def truncate(
    value: str,
    maximum: int,
) -> str:

    value = str(value)

    if len(value) <= maximum:
        return value

    return (
        value[: maximum - 3]
        + "..."
    )


def safe_channel_name(
    channel: Optional[discord.abc.GuildChannel],
) -> str:

    if channel is None:
        return "Unknown"

    return (
        f"#{channel.name}"
        if hasattr(channel, "name")
        else str(channel)
    )


# ============================================================
# OWNER CHECK
# ============================================================

def owner_only():
    async def predicate(
        interaction: discord.Interaction,
    ) -> bool:

        if interaction.user.id in OWNERS:
            return True

        try:

            await interaction.response.send_message(
                (
                    f"{EMOJI['denied']} "
                    "**Access Denied**\n\n"
                    "This system panel is restricted to "
                    "the Lunar bot owners."
                ),
                ephemeral=True,
            )

        except discord.InteractionResponded:

            await interaction.followup.send(
                (
                    f"{EMOJI['denied']} "
                    "**Access Denied**\n\n"
                    "This system panel is restricted to "
                    "the Lunar bot owners."
                ),
                ephemeral=True,
            )

        return False

    return app_commands.check(
        predicate
    )


# ============================================================
# EMBED FACTORY
# ============================================================

class EmbedFactory:

    @staticmethod
    def base(
        *,
        title: str,
        description: Optional[str] = None,
        color: discord.Colour = discord.Colour.blurple(),
    ) -> discord.Embed:

        embed = discord.Embed(
            title=title,
            description=description,
            colour=color,
            timestamp=utcnow(),
        )

        embed.set_footer(
            text=COG_NAME
        )

        return embed

    @staticmethod
    def success(
        title: str,
        description: str,
    ) -> discord.Embed:

        return EmbedFactory.base(
            title=(
                f"{EMOJI['approved']} {title}"
            ),
            description=description,
            color=discord.Colour.green(),
        )

    @staticmethod
    def error(
        title: str,
        description: str,
    ) -> discord.Embed:

        return EmbedFactory.base(
            title=(
                f"{EMOJI['error']} {title}"
            ),
            description=description,
            color=discord.Colour.red(),
        )

    @staticmethod
    def warning(
        title: str,
        description: str,
    ) -> discord.Embed:

        return EmbedFactory.base(
            title=(
                f"{EMOJI['question']} {title}"
            ),
            description=description,
            color=discord.Colour.orange(),
        )


# ============================================================
# LOG VIEW
# ============================================================

class LogView(
    discord.ui.View
):

    def __init__(
        self,
        entries: list[StoredLog],
        *,
        level_name: str,
        per_page: int = 8,
    ):
        super().__init__(
            timeout=180
        )

        self.entries = entries
        self.level_name = level_name
        self.per_page = per_page
        self.page = 0

        self.max_page = max(
            0,
            (
                len(entries) - 1
            )
            // per_page,
        )

        self._sync_buttons()

    # ========================================================
    # BUTTON STATE
    # ========================================================

    def _sync_buttons(self):

        self.previous_button.disabled = (
            self.page <= 0
        )

        self.next_button.disabled = (
            self.page >= self.max_page
        )

    # ========================================================
    # EMBED
    # ========================================================

    def build_embed(self) -> discord.Embed:

        start = (
            self.page
            * self.per_page
        )

        end = (
            start
            + self.per_page
        )

        page_entries = self.entries[
            start:end
        ]

        embed = EmbedFactory.base(
            title=(
                f"{EMOJI['dev']} System Logs"
            ),
            description=(
                f"Filter: `{self.level_name}`\n"
                f"Entries: `{len(self.entries)}`"
            ),
        )

        if not page_entries:

            embed.description = (
                f"Filter: `{self.level_name}`\n\n"
                "No matching log entries were found."
            )

            return embed

        lines = []

        for entry in page_entries:

            timestamp = (
                int(
                    entry.timestamp.timestamp()
                )
            )

            level_name = (
                logging.getLevelName(
                    entry.level
                )
            )

            level_symbol = {
                "DEBUG": "DBG",
                "INFO": "INF",
                "WARNING": "WRN",
                "ERROR": "ERR",
                "CRITICAL": "CRT",
            }.get(
                level_name,
                "LOG",
            )

            lines.append(
                (
                    f"`{level_symbol:<3}` "
                    f"<t:{timestamp}:T> "
                    f"`{truncate(entry.logger_name, 28)}`\n"
                    f"> {truncate(entry.message, 220)}"
                )
            )

        embed.add_field(
            name=(
                f"Page {self.page + 1}"
                f" / "
                f"{self.max_page + 1}"
            ),
            value="\n\n".join(lines),
            inline=False,
        )

        return embed

    # ========================================================
    # PREVIOUS
    # ========================================================

    @discord.ui.button(
        label="Previous",
        emoji="◀",
        style=discord.ButtonStyle.secondary,
    )
    async def previous_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):

        self.page = max(
            0,
            self.page - 1,
        )

        self._sync_buttons()

        await interaction.response.edit_message(
            embed=self.build_embed(),
            view=self,
        )

    # ========================================================
    # NEXT
    # ========================================================

    @discord.ui.button(
        label="Next",
        emoji="▶",
        style=discord.ButtonStyle.secondary,
    )
    async def next_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):

        self.page = min(
            self.max_page,
            self.page + 1,
        )

        self._sync_buttons()

        await interaction.response.edit_message(
            embed=self.build_embed(),
            view=self,
        )

    # ========================================================
    # REFRESH
    # ========================================================

    @discord.ui.button(
        label="Refresh",
        emoji="↻",
        style=discord.ButtonStyle.primary,
    )
    async def refresh_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):

        self.entries = MEMORY_HANDLER.recent(
            limit=100,
            level=LOG_LEVELS.get(
                self.level_name
            ),
        )

        self.max_page = max(
            0,
            (
                len(self.entries) - 1
            )
            // self.per_page,
        )

        self.page = min(
            self.page,
            self.max_page,
        )

        self._sync_buttons()

        await interaction.response.edit_message(
            embed=self.build_embed(),
            view=self,
        )

    # ========================================================
    # CLOSE
    # ========================================================

    @discord.ui.button(
        label="Close",
        emoji="✕",
        style=discord.ButtonStyle.danger,
    )
    async def close_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):

        for child in self.children:

            if isinstance(
                child,
                discord.ui.Button,
            ):
                child.disabled = True

        await interaction.response.edit_message(
            view=self,
        )

        self.stop()


# ============================================================
# SYSTEM COG
# ============================================================

class Debug(commands.Cog):

    def __init__(
        self,
        bot: commands.Bot,
    ):
        self.bot = bot

        self.started_at = utcnow()

        install_memory_handler()

        # Runtime mirror.
        #
        # bot.py will also populate these when available.
        if not hasattr(
            self.bot,
            "maintenance_mode",
        ):
            self.bot.maintenance_mode = False

        if not hasattr(
            self.bot,
            "maintenance_reason",
        ):
            self.bot.maintenance_reason = ""

    # ========================================================
    # COG LOAD
    # ========================================================

    async def cog_load(self):

        try:

            if db.variables is not None:

                state = (
                    await db.variables.get_maintenance()
                )

                self.bot.maintenance_mode = (
                    bool(
                        state.get(
                            "enabled",
                            False,
                        )
                    )
                )

                self.bot.maintenance_reason = (
                    state.get(
                        "reason",
                        "",
                    )
                    or ""
                )

                logger.info(
                    "Maintenance state loaded | enabled=%s",
                    self.bot.maintenance_mode,
                )

        except Exception:

            logger.exception(
                "Failed to load maintenance state"
            )

    # ========================================================
    # BASIC BOT METRICS
    # ========================================================

    def guild_count(self) -> int:

        return len(
            getattr(
                self.bot,
                "guilds",
                [],
            )
        )

    def user_count(self) -> int:

        return len(
            getattr(
                self.bot,
                "users",
                [],
            )
        )

    def channel_count(self) -> int:

        return sum(
            len(
                getattr(
                    guild,
                    "channels",
                    [],
                )
            )
            for guild in getattr(
                self.bot,
                "guilds",
                [],
            )
        )

    def role_count(self) -> int:

        return sum(
            len(
                getattr(
                    guild,
                    "roles",
                    [],
                )
            )
            for guild in getattr(
                self.bot,
                "guilds",
                [],
            )
        )

    def emoji_count(self) -> int:

        return sum(
            len(
                getattr(
                    guild,
                    "emojis",
                    [],
                )
            )
            for guild in getattr(
                self.bot,
                "guilds",
                [],
            )
        )

    def thread_count(self) -> int:

        total = 0

        for guild in getattr(
            self.bot,
            "guilds",
            [],
        ):

            threads = getattr(
                guild,
                "threads",
                [],
            )

            total += len(
                threads
            )

        return total

    # ========================================================
    # /DEBUG
    # ========================================================

    @app_commands.command(
        name="debug",
        description="Display a complete Lunar runtime diagnostic.",
    )
    @owner_only()
    async def debug_command(
        self,
        interaction: discord.Interaction,
    ):

        await interaction.response.defer(
            ephemeral=True,
            thinking=True,
        )

        await asyncio_sleep(
            LOADING_DELAY
        )

        bot_latency = (
            round(
                self.bot.latency * 1000
            )
            if self.bot.latency >= 0
            else 0
        )

        uptime = (
            utcnow()
            - self.started_at
        ).total_seconds()

        db_status = {
            "healthy": False,
            "initialized": False,
        }

        try:

            db_status = (
                await db.status()
            )

        except Exception:

            logger.exception(
                "Debug database status failed"
            )

        embed = EmbedFactory.base(
            title=(
                f"{EMOJI['dev']} Lunar Diagnostic Console"
            ),
            description=(
                f"Runtime snapshot generated at "
                f"<t:{int(utcnow().timestamp())}:T>."
            ),
        )

        embed.add_field(
            name=f"{EMOJI['moon']} Runtime",
            value=(
                f"**Python:** `{platform.python_version()}`\n"
                f"**Platform:** `{platform.system()} {platform.release()}`\n"
                f"**Architecture:** `{platform.machine()}`\n"
                f"**Discord.py:** `{discord.__version__}`\n"
                f"**Uptime:** `{fmt_uptime(uptime)}`"
            ),
            inline=False,
        )

        embed.add_field(
            name=f"{EMOJI['lunar']} Discord",
            value=(
                f"**Latency:** `{bot_latency}ms`\n"
                f"**Guilds:** `{self.guild_count():,}`\n"
                f"**Users:** `{self.user_count():,}`\n"
                f"**Channels:** `{self.channel_count():,}`\n"
                f"**Roles:** `{self.role_count():,}`\n"
                f"**Emojis:** `{self.emoji_count():,}`\n"
                f"**Threads:** `{self.thread_count():,}`"
            ),
            inline=False,
        )

        embed.add_field(
            name=f"{EMOJI['dev']} Cogs",
            value=(
                f"**Loaded:** "
                f"`{len(self.bot.extensions):,}`\n"
                f"**Commands:** "
                f"`{len(self.bot.tree.get_commands()):,}`"
            ),
            inline=True,
        )

        embed.add_field(
            name="Maintenance",
            value=(
                yes_no(
                    bool(
                        getattr(
                            self.bot,
                            "maintenance_mode",
                            False,
                        )
                    )
                )
                + (
                    f"\n`{truncate(getattr(self.bot, 'maintenance_reason', ''), 100)}`"
                    if getattr(
                        self.bot,
                        "maintenance_reason",
                        "",
                    )
                    else ""
                )
            ),
            inline=True,
        )

        embed.add_field(
            name="Database",
            value=(
                f"**Health:** "
                f"{status_badge(db_status.get('healthy'))}\n"
                f"**Initialized:** "
                f"{yes_no(bool(db_status.get('initialized')))}\n"
                f"**Keyspace:** "
                f"`{db_status.get('keyspace', 'unknown')}`\n"
                f"**Prepared:** "
                f"`{db_status.get('prepared_statements', 0):,}`"
            ),
            inline=False,
        )

        embed.set_author(
            name=str(
                interaction.user
            ),
            icon_url=(
                interaction.user
                .display_avatar
                .url
            ),
        )

        await interaction.followup.send(
            embed=embed,
            ephemeral=True,
        )

    # ========================================================
    # /LOGS
    # ========================================================

    @app_commands.command(
        name="logs",
        description="View recent Lunar application logs.",
    )
    @app_commands.describe(
        count="Number of log entries to display.",
        level="Minimum severity to display.",
    )
    @app_commands.choices(
        level=[
            app_commands.Choice(
                name="All",
                value="all",
            ),
            app_commands.Choice(
                name="Debug",
                value="debug",
            ),
            app_commands.Choice(
                name="Info",
                value="info",
            ),
            app_commands.Choice(
                name="Warning",
                value="warning",
            ),
            app_commands.Choice(
                name="Error",
                value="error",
            ),
            app_commands.Choice(
                name="Critical",
                value="critical",
            ),
        ]
    )
    @owner_only()
    async def logs_command(
        self,
        interaction: discord.Interaction,
        count: app_commands.Range[
            int,
            1,
            100
        ] = 25,
        level: app_commands.Choice[
            str
        ] | None = None,
    ):

        await interaction.response.defer(
            ephemeral=True,
            thinking=True,
        )

        await asyncio_sleep(
            0.8
        )

        level_name = (
            level.value
            if level
            else "all"
        )

        minimum_level = (
            LOG_LEVELS.get(
                level_name
            )
        )

        entries = MEMORY_HANDLER.recent(
            limit=count,
            level=minimum_level,
        )

        view = LogView(
            entries,
            level_name=level_name,
        )

        await interaction.followup.send(
            embed=view.build_embed(),
            view=view,
            ephemeral=True,
        )

    # ========================================================
    # /CACHE
    # ========================================================

    @app_commands.command(
        name="cache",
        description="Inspect the Discord.py runtime cache.",
    )
    @owner_only()
    async def cache_command(
        self,
        interaction: discord.Interaction,
    ):

        await interaction.response.defer(
            ephemeral=True,
            thinking=True,
        )

        await asyncio_sleep(
            0.9
        )

        voice_clients = len(
            getattr(
                self.bot,
                "voice_clients",
                [],
            )
        )

        application_commands = (
            self.bot.tree.get_commands()
        )

        embed = EmbedFactory.base(
            title=(
                f"{EMOJI['dev']} Runtime Cache"
            ),
            description=(
                "Current in-memory Discord state."
            ),
        )

        embed.add_field(
            name="Guild Cache",
            value=(
                f"**Guilds:** `{self.guild_count():,}`\n"
                f"**Users:** `{self.user_count():,}`\n"
                f"**Channels:** `{self.channel_count():,}`\n"
                f"**Roles:** `{self.role_count():,}`\n"
                f"**Emojis:** `{self.emoji_count():,}`"
            ),
            inline=False,
        )

        embed.add_field(
            name="Extended Cache",
            value=(
                f"**Threads:** `{self.thread_count():,}`\n"
                f"**Voice Clients:** `{voice_clients:,}`\n"
                f"**Slash Commands:** "
                f"`{len(application_commands):,}`"
            ),
            inline=False,
        )

        memory_entries = (
            len(
                MEMORY_HANDLER.entries
            )
        )

        embed.add_field(
            name="Diagnostic Cache",
            value=(
                f"**Stored Logs:** `{memory_entries:,}` / `{MAX_LOG_ENTRIES}`\n"
                f"**Runtime Start:** "
                f"{fmt_dt(self.started_at)}"
            ),
            inline=False,
        )

        await interaction.followup.send(
            embed=embed,
            ephemeral=True,
        )

    # ========================================================
    # /DATABASE
    # ========================================================

    @app_commands.command(
        name="database",
        description="Inspect ScyllaDB health and repository state.",
    )
    @owner_only()
    async def database_command(
        self,
        interaction: discord.Interaction,
    ):

        await interaction.response.defer(
            ephemeral=True,
            thinking=True,
        )

        await asyncio_sleep(
            1.1
        )

        try:

            status = (
                await db.status()
            )

        except Exception as exc:

            logger.exception(
                "Database diagnostics failed"
            )

            await interaction.followup.send(
                embed=EmbedFactory.error(
                    "Database Diagnostics Failed",
                    (
                        f"```text\n"
                        f"{truncate(exc, 1500)}"
                        f"\n```"
                    ),
                ),
                ephemeral=True,
            )

            return

        healthy = bool(
            status.get(
                "healthy",
                False,
            )
        )

        embed = EmbedFactory.base(
            title=(
                f"{EMOJI['dev']} ScyllaDB Diagnostics"
            ),
            description=(
                f"Health: "
                f"{status_badge(healthy)}"
            ),
            color=(
                discord.Colour.green()
                if healthy
                else discord.Colour.red()
            ),
        )

        embed.add_field(
            name="Connection",
            value=(
                f"**Keyspace:** "
                f"`{status.get('keyspace', 'unknown')}`\n"
                f"**Port:** "
                f"`{status.get('port', 'unknown')}`\n"
                f"**DC:** "
                f"`{status.get('data_center', 'unknown')}`\n"
                f"**Cluster:** "
                f"`{status.get('cluster_name', 'unknown')}`"
            ),
            inline=False,
        )

        embed.add_field(
            name="Server",
            value=(
                f"**Release:** "
                f"`{status.get('release_version', 'unknown')}`\n"
                f"**Host ID:** "
                f"`{status.get('host_id', 'unknown')}`"
            ),
            inline=False,
        )

        repositories = status.get(
            "repositories",
            [],
        )

        repo_text = (
            "\n".join(
                f"{EMOJI['approved']} `{repo}`"
                for repo in repositories
            )
            if repositories
            else "No repositories bound."
        )

        embed.add_field(
            name=(
                f"Repositories "
                f"`{len(repositories)}`"
            ),
            value=truncate(
                repo_text,
                1024,
            ),
            inline=False,
        )

        embed.add_field(
            name="Driver",
            value=(
                f"**Prepared Statements:** "
                f"`{status.get('prepared_statements', 0):,}`\n"
                f"**Session:** "
                f"{status_badge(status.get('session_connected'))}\n"
                f"**Cluster:** "
                f"{status_badge(status.get('cluster_connected'))}"
            ),
            inline=False,
        )

        if status.get("error"):

            embed.add_field(
                name="Error",
                value=(
                    f"```text\n"
                    f"{truncate(status['error'], 900)}"
                    f"\n```"
                ),
                inline=False,
            )

        await interaction.followup.send(
            embed=embed,
            ephemeral=True,
        )

    # ========================================================
    # /SHARD
    # ========================================================

    @app_commands.command(
        name="shard",
        description="Inspect Discord shard and gateway information.",
    )
    @owner_only()
    async def shard_command(
        self,
        interaction: discord.Interaction,
    ):

        await interaction.response.defer(
            ephemeral=True,
            thinking=True,
        )

        await asyncio_sleep(
            0.95
        )

        embed = EmbedFactory.base(
            title=(
                f"{EMOJI['moon']} Gateway / Shard Console"
            )
        )

        shards = getattr(
            self.bot,
            "shards",
            None,
        )

        if not shards:

            embed.description = (
                "The bot is currently running "
                "without a sharded gateway manager."
            )

            embed.add_field(
                name="Gateway",
                value=(
                    f"**Mode:** `Single Shard`\n"
                    f"**Latency:** "
                    f"`{round(self.bot.latency * 1000)}ms`\n"
                    f"**Guilds:** "
                    f"`{self.guild_count():,}`"
                ),
                inline=False,
            )

        else:

            embed.description = (
                f"Detected `{len(shards)}` active shard(s)."
            )

            for shard_id, shard in sorted(
                shards.items(),
                key=lambda item: item[0],
            ):

                latency = getattr(
                    shard,
                    "latency",
                    0,
                )

                guilds = [
                    guild
                    for guild in self.bot.guilds
                    if guild.shard_id == shard_id
                ]

                embed.add_field(
                    name=f"Shard {shard_id}",
                    value=(
                        f"**Latency:** "
                        f"`{round(latency * 1000)}ms`\n"
                        f"**Guilds:** "
                        f"`{len(guilds):,}`"
                    ),
                    inline=True,
                )

        embed.add_field(
            name="Gateway Summary",
            value=(
                f"**Bot User:** "
                f"`{self.bot.user.id if self.bot.user else 'unknown'}`\n"
                f"**Session:** "
                f"{status_badge(self.bot.is_ready())}"
            ),
            inline=False,
        )

        await interaction.followup.send(
            embed=embed,
            ephemeral=True,
        )

    # ========================================================
    # /MAINTENANCE
    # ========================================================

    @app_commands.command(
        name="maintenance",
        description="Manage Lunar maintenance mode.",
    )
    @app_commands.describe(
        action="Action to perform.",
        reason="Reason shown to users while maintenance is active.",
    )
    @app_commands.choices(
        action=[
            app_commands.Choice(
                name="Status",
                value="status",
            ),
            app_commands.Choice(
                name="Enable",
                value="enable",
            ),
            app_commands.Choice(
                name="Disable",
                value="disable",
            ),
        ]
    )
    @owner_only()
    async def maintenance_command(
        self,
        interaction: discord.Interaction,
        action: app_commands.Choice[
            str
        ],
        reason: Optional[
            app_commands.Range[
                str,
                1,
                500
            ]
        ] = None,
    ):

        await interaction.response.defer(
            ephemeral=True,
            thinking=True,
        )

        await asyncio_sleep(
            1.0
        )

        selected = action.value

        # ----------------------------------------------------
        # STATUS
        # ----------------------------------------------------

        if selected == "status":

            enabled = bool(
                getattr(
                    self.bot,
                    "maintenance_mode",
                    False,
                )
            )

            current_reason = (
                getattr(
                    self.bot,
                    "maintenance_reason",
                    "",
                )
                or ""
            )

            embed = EmbedFactory.base(
                title=(
                    f"{EMOJI['dev']} Maintenance Status"
                ),
                description=(
                    f"**State:** "
                    f"{status_badge(not enabled)}"
                    if not enabled
                    else
                    f"**State:** "
                    f"{EMOJI['question']} `MAINTENANCE`"
                ),
            )

            embed.add_field(
                name="Mode",
                value=(
                    yes_no(enabled)
                ),
                inline=True,
            )

            embed.add_field(
                name="Reason",
                value=(
                    truncate(
                        current_reason,
                        1024,
                    )
                    if current_reason
                    else "No reason configured."
                ),
                inline=False,
            )

            embed.add_field(
                name="Effect",
                value=(
                    "Normal user commands should be blocked by "
                    "the global maintenance check in `bot.py`."
                    if enabled
                    else
                    "Normal commands are operating normally."
                ),
                inline=False,
            )

            await interaction.followup.send(
                embed=embed,
                ephemeral=True,
            )

            return

        # ----------------------------------------------------
        # DATABASE REPOSITORY
        # ----------------------------------------------------

        if db.variables is None:

            await interaction.followup.send(
                embed=EmbedFactory.error(
                    "Database Repository Unavailable",
                    (
                        "The `variables` repository is not bound. "
                        "Maintenance state could not be persisted."
                    ),
                ),
                ephemeral=True,
            )

            return

        # ----------------------------------------------------
        # ENABLE
        # ----------------------------------------------------

        if selected == "enable":

            maintenance_reason = (
                str(reason).strip()
                if reason
                else "Lunar is currently undergoing maintenance."
            )

            await db.variables.set_maintenance(
                True,
                reason=maintenance_reason,
                changed_by=interaction.user.id,
            )

            self.bot.maintenance_mode = True

            self.bot.maintenance_reason = (
                maintenance_reason
            )

            try:

                if db.audit is not None:

                    await db.audit.record(
                        interaction.guild.id
                        if interaction.guild
                        else 0,
                        actor_id=interaction.user.id,
                        action="maintenance_enable",
                        target_id=None,
                        reason=maintenance_reason,
                        metadata={
                            "source": "debug.py",
                        },
                    )

            except Exception:

                logger.exception(
                    "Failed to audit maintenance enable"
                )

            embed = EmbedFactory.success(
                "Maintenance Enabled",
                (
                    "Lunar maintenance mode is now active.\n\n"
                    f"**Reason:**\n"
                    f"> {truncate(maintenance_reason, 700)}\n\n"
                    "The state has been persisted to ScyllaDB."
                ),
            )

            await interaction.followup.send(
                embed=embed,
                ephemeral=True,
            )

            logger.warning(
                "Maintenance mode ENABLED by %s | %s",
                interaction.user.id,
                maintenance_reason,
            )

            return

        # ----------------------------------------------------
        # DISABLE
        # ----------------------------------------------------

        await db.variables.set_maintenance(
            False,
            reason="",
            changed_by=interaction.user.id,
        )

        self.bot.maintenance_mode = False

        self.bot.maintenance_reason = ""

        try:

            if db.audit is not None:

                await db.audit.record(
                    interaction.guild.id
                    if interaction.guild
                    else 0,
                    actor_id=interaction.user.id,
                    action="maintenance_disable",
                    target_id=None,
                    reason="Maintenance mode disabled.",
                    metadata={
                        "source": "debug.py",
                    },
                )

        except Exception:

            logger.exception(
                "Failed to audit maintenance disable"
            )

        embed = EmbedFactory.success(
            "Maintenance Disabled",
            (
                "Lunar maintenance mode has been disabled.\n\n"
                "Normal command processing may resume immediately."
            ),
        )

        await interaction.followup.send(
            embed=embed,
            ephemeral=True,
        )

        logger.info(
            "Maintenance mode DISABLED by %s",
            interaction.user.id,
        )

    # ========================================================
    # /COMMANDS
    # ========================================================

    @app_commands.command(
        name="commandstats",
        description="Inspect persistent command usage statistics.",
    )
    @owner_only()
    async def commandstats_command(
        self,
        interaction: discord.Interaction,
    ):

        await interaction.response.defer(
            ephemeral=True,
            thinking=True,
        )

        await asyncio_sleep(
            0.9
        )

        if db.command_stats is None:

            await interaction.followup.send(
                embed=EmbedFactory.error(
                    "Command Statistics Unavailable",
                    (
                        "The command statistics repository is not "
                        "currently bound."
                    ),
                ),
                ephemeral=True,
            )

            return

        try:

            total = (
                await db.command_stats.total()
            )

            rows = (
                await db.command_stats.all()
            )

        except Exception as exc:

            logger.exception(
                "Command statistics lookup failed"
            )

            await interaction.followup.send(
                embed=EmbedFactory.error(
                    "Statistics Lookup Failed",
                    (
                        f"```text\n"
                        f"{truncate(exc, 1200)}"
                        f"\n```"
                    ),
                ),
                ephemeral=True,
            )

            return

        embed = EmbedFactory.base(
            title=(
                f"{EMOJI['dev']} Command Analytics"
            ),
            description=(
                f"**Total recorded invocations:** "
                f"`{total:,}`"
            ),
        )

        if not rows:

            embed.add_field(
                name="Usage",
                value="No command usage has been recorded yet.",
                inline=False,
            )

        else:

            top_rows = rows[:15]

            lines = []

            for index, row in enumerate(
                top_rows,
                start=1,
            ):

                command_name = (
                    getattr(
                        row,
                        "command_name",
                        "unknown",
                    )
                )

                uses = int(
                    getattr(
                        row,
                        "uses",
                        0,
                    )
                    or 0
                )

                medal = {
                    1: "1.",
                    2: "2.",
                    3: "3.",
                }.get(
                    index,
                    f"{index}.",
                )

                lines.append(
                    f"`{medal}` "
                    f"`/{command_name}` "
                    f"— **{uses:,}**"
                )

            embed.add_field(
                name="Top Commands",
                value="\n".join(lines),
                inline=False,
            )

        embed.add_field(
            name="Tracked Commands",
            value=(
                f"`{len(rows):,}`"
            ),
            inline=True,
        )

        embed.add_field(
            name="Storage",
            value=(
                "`ScyllaDB counter table`"
            ),
            inline=True,
        )

        await interaction.followup.send(
            embed=embed,
            ephemeral=True,
        )

    # ========================================================
    # /SYSINFO
    # ========================================================

    @app_commands.command(
        name="sysinfo",
        description="Show detailed Python and host diagnostics.",
    )
    @owner_only()
    async def sysinfo_command(
        self,
        interaction: discord.Interaction,
    ):

        await interaction.response.defer(
            ephemeral=True,
            thinking=True,
        )

        await asyncio_sleep(
            0.8
        )

        process_uptime = (
            utcnow()
            - self.started_at
        ).total_seconds()

        embed = EmbedFactory.base(
            title=(
                f"{EMOJI['dev']} Host Diagnostics"
            )
        )

        embed.add_field(
            name="Python",
            value=(
                f"**Version:** `{platform.python_version()}`\n"
                f"**Implementation:** `{platform.python_implementation()}`\n"
                f"**Executable:** `{truncate(sys.executable, 100)}`"
            ),
            inline=False,
        )

        embed.add_field(
            name="Host",
            value=(
                f"**OS:** `{platform.system()}`\n"
                f"**Release:** `{platform.release()}`\n"
                f"**Machine:** `{platform.machine()}`\n"
                f"**Processor:** `{truncate(platform.processor() or 'Unknown', 120)}`"
            ),
            inline=False,
        )

        embed.add_field(
            name="Bot Runtime",
            value=(
                f"**Uptime:** `{fmt_uptime(process_uptime)}`\n"
                f"**Latency:** `{round(self.bot.latency * 1000)}ms`\n"
                f"**Ready:** {yes_no(self.bot.is_ready())}"
            ),
            inline=False,
        )

        embed.add_field(
            name="Gateway",
            value=(
                f"**Guilds:** `{self.guild_count():,}`\n"
                f"**Users:** `{self.user_count():,}`"
            ),
            inline=True,
        )

        embed.add_field(
            name="Application",
            value=(
                f"**Commands:** "
                f"`{len(self.bot.tree.get_commands()):,}`\n"
                f"**Cogs:** "
                f"`{len(self.bot.extensions):,}`"
            ),
            inline=True,
        )

        await interaction.followup.send(
            embed=embed,
            ephemeral=True,
        )

    # ========================================================
    # /HEALTH
    # ========================================================

    @app_commands.command(
        name="health",
        description="Run a compact Lunar health check.",
    )
    @owner_only()
    async def health_command(
        self,
        interaction: discord.Interaction,
    ):

        await interaction.response.defer(
            ephemeral=True,
            thinking=True,
        )

        started = time.perf_counter()

        await asyncio_sleep(
            0.65
        )

        discord_latency = (
            round(
                self.bot.latency * 1000
            )
        )

        database_ok = False

        try:

            database_ok = (
                await db.ping()
            )

        except Exception:

            logger.exception(
                "Health database ping failed"
            )

        elapsed = (
            (time.perf_counter() - started)
            * 1000
        )

        overall_ok = (
            self.bot.is_ready()
            and database_ok
        )

        embed = EmbedFactory.base(
            title=(
                f"{EMOJI['moon']} Lunar Health Check"
            ),
            description=(
                f"Overall: "
                f"{status_badge(overall_ok)}"
            ),
            color=(
                discord.Colour.green()
                if overall_ok
                else discord.Colour.red()
            ),
        )

        embed.add_field(
            name="Discord",
            value=(
                f"{status_badge(self.bot.is_ready())}\n"
                f"`{discord_latency}ms` gateway latency"
            ),
            inline=True,
        )

        embed.add_field(
            name="ScyllaDB",
            value=(
                f"{status_badge(database_ok)}"
            ),
            inline=True,
        )

        embed.add_field(
            name="Diagnostics",
            value=(
                f"`{round(elapsed, 2)}ms` total diagnostic time"
            ),
            inline=False,
        )

        await interaction.followup.send(
            embed=embed,
            ephemeral=True,
        )


# ============================================================
# ASYNC SLEEP WRAPPER
# ============================================================

async def asyncio_sleep(
    seconds: float,
):
    await __import__(
        "asyncio"
    ).sleep(
        seconds
    )


# ============================================================
# SETUP
# ============================================================

async def setup(
    bot: commands.Bot,
) -> None:

    await bot.add_cog(
        Debug(bot)
    )
