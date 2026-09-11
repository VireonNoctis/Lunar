from __future__ import annotations

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
LOG_PAGE_SIZE = 8

LOG_LEVELS = {
    "all": None,
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "warning": logging.WARNING,
    "error": logging.ERROR,
    "critical": logging.CRITICAL,
}

logger = logging.getLogger("lunar.system")


# ============================================================
# MEMORY LOG
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
    ) -> None:

        super().__init__()

        self.entries = deque(
            maxlen=max_entries
        )

    def emit(
        self,
        record: logging.LogRecord,
    ) -> None:

        try:

            self.entries.append(
                StoredLog(
                    timestamp=datetime.fromtimestamp(
                        record.created,
                        timezone.utc,
                    ),
                    level=record.levelno,
                    logger_name=record.name,
                    message=self.format(
                        record
                    ),
                )
            )

        except Exception:
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


def truncate(
    value: object,
    maximum: int,
) -> str:

    value = str(value)

    if len(value) <= maximum:
        return value

    return (
        value[: maximum - 3]
        + "..."
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


# ============================================================
# EMBEDS
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
                f"{EMOJI['approved']} "
                f"{title}"
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
                f"{EMOJI['error']} "
                f"{title}"
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
                f"{EMOJI['question']} "
                f"{title}"
            ),
            description=description,
            color=discord.Colour.orange(),
        )


# ============================================================
# EVAL MODAL
# ============================================================

class EvalModal(
    discord.ui.Modal,
    title="Lunar Developer Eval",
):

    code = discord.ui.TextInput(
        label="Python Expression",
        placeholder=(
            "Example: bot.latency"
        ),
        style=discord.TextStyle.paragraph,
        required=True,
        max_length=1000,
    )

    def __init__(
        self,
        cog: "System",
        user_id: int,
    ) -> None:

        super().__init__()

        self.cog = cog
        self.user_id = user_id

    async def on_submit(
        self,
        interaction: discord.Interaction,
    ) -> None:

        if (
            interaction.user.id
            != self.user_id
        ):

            await interaction.response.send_message(
                f"{EMOJI['denied']} "
                "This evaluation session belongs to another user.",
                ephemeral=True,
            )

            return

        expression = (
            self.code.value.strip()
        )

        if expression.startswith(
            "```"
        ):

            lines = expression.splitlines()

            if lines:
                lines = lines[1:]

            if (
                lines
                and lines[-1].strip()
                == "```"
            ):

                lines.pop()

            expression = "\n".join(
                lines
            )

        await interaction.response.defer(
            ephemeral=True
        )

        environment = {
            "bot": self.cog.bot,
            "interaction": interaction,
            "guild": interaction.guild,
            "channel": interaction.channel,
            "author": interaction.user,
            "discord": discord,
            "commands": commands,
            "app_commands": app_commands,
            "EMOJI": EMOJI,
            "db": db,
        }

        try:

            result = eval(
                expression,
                {
                    "__builtins__": {}
                },
                environment,
            )

            if hasattr(
                result,
                "__await__",
            ):

                result = await result

            result = self.cog.format_result(
                result
            )

            embed = EmbedFactory.success(
                "Eval Result",
                (
                    "```py\n"
                    f"{result}"
                    "\n```"
                ),
            )

        except Exception as exc:

            embed = EmbedFactory.error(
                "Eval Error",
                (
                    "```py\n"
                    f"{type(exc).__name__}: "
                    f"{exc}"
                    "\n```"
                ),
            )

        await interaction.followup.send(
            embed=embed,
            ephemeral=True,
        )


# ============================================================
# MAINTENANCE MODAL
# ============================================================

class MaintenanceModal(
    discord.ui.Modal,
):

    reason = discord.ui.TextInput(
        label="Maintenance Reason",
        placeholder=(
            "Example: Database migration"
        ),
        style=discord.TextStyle.paragraph,
        required=False,
        max_length=500,
    )

    def __init__(
        self,
        cog: "System",
        user_id: int,
    ) -> None:

        super().__init__(
            title="Enable Maintenance"
        )

        self.cog = cog
        self.user_id = user_id

    async def on_submit(
        self,
        interaction: discord.Interaction,
    ) -> None:

        if (
            interaction.user.id
            != self.user_id
        ):

            await interaction.response.send_message(
                f"{EMOJI['denied']} "
                "This maintenance session belongs to another owner.",
                ephemeral=True,
            )

            return

        maintenance_reason = (
            self.reason.value.strip()
            or "Lunar is currently undergoing maintenance."
        )

        await self.cog.enable_maintenance(
            interaction,
            maintenance_reason,
        )


# ============================================================
# LOG VIEW
# ============================================================

class LogView(
    discord.ui.View
):

    def __init__(
        self,
        cog: "System",
        owner_id: int,
        level_name: str = "all",
    ) -> None:

        super().__init__(
            timeout=180
        )

        self.cog = cog
        self.owner_id = owner_id
        self.level_name = level_name

        self.entries = MEMORY_HANDLER.recent(
            limit=100,
            level=LOG_LEVELS.get(
                level_name
            ),
        )

        self.page = 0

        self.max_page = max(
            0,
            (
                len(self.entries) - 1
            )
            // LOG_PAGE_SIZE,
        )

        self.sync_buttons()

    def sync_buttons(
        self,
    ) -> None:

        self.previous.disabled = (
            self.page <= 0
        )

        self.next.disabled = (
            self.page >= self.max_page
        )

    async def interaction_check(
        self,
        interaction: discord.Interaction,
    ) -> bool:

        if interaction.user.id != self.owner_id:

            await interaction.response.send_message(
                f"{EMOJI['denied']} "
                "Only the owner who opened this panel can use it.",
                ephemeral=True,
            )

            return False

        return True

    def build_embed(
        self,
    ) -> discord.Embed:

        start = (
            self.page
            * LOG_PAGE_SIZE
        )

        end = (
            start
            + LOG_PAGE_SIZE
        )

        page_entries = self.entries[
            start:end
        ]

        embed = EmbedFactory.base(
            title=(
                f"{EMOJI['dev']} "
                "System Logs"
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

            timestamp = int(
                entry.timestamp.timestamp()
            )

            level_name = logging.getLevelName(
                entry.level
            )

            level_code = {
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
                    f"`{level_code:<3}` "
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
            value="\n\n".join(
                lines
            ),
            inline=False,
        )

        return embed

    @discord.ui.button(
        label="Previous",
        emoji="◀️",
        style=discord.ButtonStyle.secondary,
    )
    async def previous(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:

        self.page = max(
            0,
            self.page - 1,
        )

        self.sync_buttons()

        await interaction.response.edit_message(
            embed=self.build_embed(),
            view=self,
        )

    @discord.ui.button(
        label="Next",
        emoji="▶️",
        style=discord.ButtonStyle.secondary,
    )
    async def next(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:

        self.page = min(
            self.max_page,
            self.page + 1,
        )

        self.sync_buttons()

        await interaction.response.edit_message(
            embed=self.build_embed(),
            view=self,
        )

    @discord.ui.button(
        label="Refresh",
        emoji="🔄",
        style=discord.ButtonStyle.primary,
    )
    async def refresh(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:

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
            // LOG_PAGE_SIZE,
        )

        self.page = min(
            self.page,
            self.max_page,
        )

        self.sync_buttons()

        await interaction.response.edit_message(
            embed=self.build_embed(),
            view=self,
        )

    @discord.ui.button(
        label="Close",
        emoji="✖️",
        style=discord.ButtonStyle.danger,
    )
    async def close(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:

        for item in self.children:

            if isinstance(
                item,
                discord.ui.Button,
            ):

                item.disabled = True

        await interaction.response.edit_message(
            view=self
        )

        self.stop()


# ============================================================
# DASHBOARD VIEW
# ============================================================

class SystemDashboard(
    discord.ui.View
):

    def __init__(
        self,
        cog: "System",
        owner_id: int,
    ) -> None:

        super().__init__(
            timeout=600
        )

        self.cog = cog
        self.owner_id = owner_id

    async def interaction_check(
        self,
        interaction: discord.Interaction,
    ) -> bool:

        if interaction.user.id != self.owner_id:

            await interaction.response.send_message(
                f"{EMOJI['denied']} "
                "Only the owner who opened this dashboard can use it.",
                ephemeral=True,
            )

            return False

        return True

    @discord.ui.button(
        label="Diagnostics",
        emoji="🔧",
        style=discord.ButtonStyle.primary,
        row=0,
    )
    async def diagnostics(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:

        await self.cog.show_diagnostics(
            interaction
        )

    @discord.ui.button(
        label="Logs",
        emoji="📜",
        style=discord.ButtonStyle.secondary,
        row=0,
    )
    async def logs(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:

        view = LogView(
            self.cog,
            self.owner_id,
        )

        await interaction.response.edit_message(
            embed=view.build_embed(),
            view=view,
        )

    @discord.ui.button(
        label="Database",
        emoji="💾",
        style=discord.ButtonStyle.secondary,
        row=0,
    )
    async def database(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:

        await self.cog.show_database(
            interaction
        )

    @discord.ui.button(
        label="Cache",
        emoji="⚡",
        style=discord.ButtonStyle.secondary,
        row=0,
    )
    async def cache(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:

        await self.cog.show_cache(
            interaction
        )

    @discord.ui.button(
        label="Gateway",
        emoji="🌐",
        style=discord.ButtonStyle.secondary,
        row=1,
    )
    async def gateway(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:

        await self.cog.show_gateway(
            interaction
        )

    @discord.ui.button(
        label="System",
        emoji="🖥️",
        style=discord.ButtonStyle.secondary,
        row=1,
    )
    async def system(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:

        await self.cog.show_system(
            interaction
        )

    @discord.ui.button(
        label="Health",
        emoji="🩺",
        style=discord.ButtonStyle.success,
        row=1,
    )
    async def health(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:

        await self.cog.show_health(
            interaction
        )

    @discord.ui.button(
        label="Commands",
        emoji="📊",
        style=discord.ButtonStyle.secondary,
        row=1,
    )
    async def commands(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:

        await self.cog.show_command_stats(
            interaction
        )

    @discord.ui.button(
        label="Maintenance",
        emoji="🔒",
        style=discord.ButtonStyle.danger,
        row=2,
    )
    async def maintenance(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:

        enabled = bool(
            getattr(
                self.cog.bot,
                "maintenance_mode",
                False,
            )
        )

        if enabled:

            await self.cog.disable_maintenance(
                interaction
            )

        else:

            await interaction.response.send_modal(
                MaintenanceModal(
                    self.cog,
                    self.owner_id,
                )
            )

    @discord.ui.button(
        label="Eval",
        emoji="🧪",
        style=discord.ButtonStyle.primary,
        row=2,
    )
    async def eval(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:

        await interaction.response.send_modal(
            EvalModal(
                self.cog,
                self.owner_id,
            )
        )

    @discord.ui.button(
        label="Refresh",
        emoji="🔄",
        style=discord.ButtonStyle.success,
        row=2,
    )
    async def refresh(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:

        await self.cog.show_dashboard(
            interaction,
            edit=True,
        )

    @discord.ui.button(
        label="Close",
        emoji="✖️",
        style=discord.ButtonStyle.danger,
        row=3,
    )
    async def close(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:

        for item in self.children:

            if isinstance(
                item,
                discord.ui.Button,
            ):

                item.disabled = True

        await interaction.response.edit_message(
            view=self
        )

        self.stop()

    async def on_timeout(
        self,
    ) -> None:

        for item in self.children:

            if isinstance(
                item,
                discord.ui.Button,
            ):

                item.disabled = True


# ============================================================
# SYSTEM COG
# ============================================================

class System(
    commands.Cog
):

    def __init__(
        self,
        bot: commands.Bot,
    ) -> None:

        self.bot = bot
        self.started_at = utcnow()

        install_memory_handler()

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
    # COMMAND
    # ========================================================

    @app_commands.command(
        name="system",
        description=(
            "Open the Lunar system control dashboard."
        ),
    )
    async def system_command(
        self,
        interaction: discord.Interaction,
    ) -> None:

        if (
            interaction.user.id
            not in OWNERS
        ):

            await interaction.response.send_message(
                (
                    f"{EMOJI['denied']} "
                    "**Access Denied**\n\n"
                    "This system panel is restricted to "
                    "the Lunar bot owners."
                ),
                ephemeral=True,
            )

            return

        await interaction.response.send_message(
            embed=self.build_dashboard_embed(),
            view=SystemDashboard(
                self,
                interaction.user.id,
            ),
            ephemeral=True,
        )

    # ========================================================
    # DASHBOARD EMBED
    # ========================================================

    def build_dashboard_embed(
        self,
    ) -> discord.Embed:

        uptime = (
            utcnow()
            - self.started_at
        ).total_seconds()

        maintenance = bool(
            getattr(
                self.bot,
                "maintenance_mode",
                False,
            )
        )

        latency = (
            round(
                self.bot.latency * 1000
            )
            if self.bot.latency >= 0
            else 0
        )

        embed = EmbedFactory.base(
            title=(
                f"{EMOJI['lunar']} "
                "Lunar System Control"
            ),
            description=(
                "Owner-only control dashboard.\n"
                "Use the buttons below to inspect and manage "
                "the Lunar runtime."
            ),
        )

        embed.add_field(
            name="Discord",
            value=(
                f"{status_badge(self.bot.is_ready())}\n"
                f"`{latency}ms` latency"
            ),
            inline=True,
        )

        embed.add_field(
            name="Database",
            value=(
                "Press **Database** to inspect."
            ),
            inline=True,
        )

        embed.add_field(
            name="Maintenance",
            value=(
                f"{EMOJI['question']} `ACTIVE`"
                if maintenance
                else
                f"{EMOJI['approved']} `NORMAL`"
            ),
            inline=True,
        )

        embed.add_field(
            name="Runtime",
            value=(
                f"**Uptime:** "
                f"`{fmt_uptime(uptime)}`\n"
                f"**Guilds:** "
                f"`{len(self.bot.guilds):,}`\n"
                f"**Users:** "
                f"`{len(self.bot.users):,}`\n"
                f"**Cogs:** "
                f"`{len(self.bot.extensions):,}`\n"
                f"**Commands:** "
                f"`{len(self.bot.tree.get_commands()):,}`"
            ),
            inline=False,
        )

        if maintenance:

            reason = (
                getattr(
                    self.bot,
                    "maintenance_reason",
                    "",
                )
                or "No reason configured."
            )

            embed.add_field(
                name="Maintenance Reason",
                value=(
                    f"> {truncate(reason, 700)}"
                ),
                inline=False,
            )

        embed.set_thumbnail(
            url=self.bot.user.display_avatar.url
            if self.bot.user
            else discord.Embed.EmptyEmbed
        )

        return embed

    # ========================================================
    # DIAGNOSTICS
    # ========================================================

    async def show_diagnostics(
        self,
        interaction: discord.Interaction,
    ) -> None:

        if not interaction.response.is_done():

            await interaction.response.defer(
                ephemeral=True
            )

        bot_latency = round(
            self.bot.latency * 1000
        )

        uptime = (
            utcnow()
            - self.started_at
        ).total_seconds()

        try:

            status = (
                await db.status()
            )

        except Exception as exc:

            status = {
                "healthy": False,
                "initialized": False,
                "error": str(exc),
            }

        embed = EmbedFactory.base(
            title=(
                f"{EMOJI['dev']} "
                "Lunar Diagnostics"
            ),
            description=(
                "Complete runtime snapshot."
            ),
        )

        embed.add_field(
            name="Runtime",
            value=(
                f"**Python:** "
                f"`{platform.python_version()}`\n"
                f"**Platform:** "
                f"`{platform.system()} {platform.release()}`\n"
                f"**Architecture:** "
                f"`{platform.machine()}`\n"
                f"**Discord.py:** "
                f"`{discord.__version__}`\n"
                f"**Uptime:** "
                f"`{fmt_uptime(uptime)}`"
            ),
            inline=False,
        )

        embed.add_field(
            name="Discord",
            value=(
                f"**Status:** "
                f"{status_badge(self.bot.is_ready())}\n"
                f"**Latency:** "
                f"`{bot_latency}ms`\n"
                f"**Guilds:** "
                f"`{len(self.bot.guilds):,}`\n"
                f"**Users:** "
                f"`{len(self.bot.users):,}`"
            ),
            inline=True,
        )

        embed.add_field(
            name="Application",
            value=(
                f"**Cogs:** "
                f"`{len(self.bot.extensions):,}`\n"
                f"**Commands:** "
                f"`{len(self.bot.tree.get_commands()):,}`\n"
                f"**Voice:** "
                f"`{len(self.bot.voice_clients):,}`"
            ),
            inline=True,
        )

        embed.add_field(
            name="Database",
            value=(
                f"**Health:** "
                f"{status_badge(status.get('healthy'))}\n"
                f"**Initialized:** "
                f"{yes_no(bool(status.get('initialized')))}\n"
                f"**Keyspace:** "
                f"`{status.get('keyspace', 'unknown')}`"
            ),
            inline=False,
        )

        if status.get("error"):

            embed.add_field(
                name="Database Error",
                value=(
                    f"```text\n"
                    f"{truncate(status['error'], 900)}"
                    f"\n```"
                ),
                inline=False,
            )

        await self.edit_panel(
            interaction,
            embed,
        )

    # ========================================================
    # DATABASE
    # ========================================================

    async def show_database(
        self,
        interaction: discord.Interaction,
    ) -> None:

        if not interaction.response.is_done():

            await interaction.response.defer(
                ephemeral=True
            )

        try:

            status = (
                await db.status()
            )

        except Exception as exc:

            await self.edit_panel(
                interaction,
                EmbedFactory.error(
                    "Database Diagnostics Failed",
                    (
                        f"```text\n"
                        f"{truncate(exc, 1500)}"
                        f"\n```"
                    ),
                ),
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
                f"{EMOJI['dev']} "
                "ScyllaDB Diagnostics"
            ),
            description=(
                f"Health: "
                f"{status_badge(healthy)}"
            ),
            color=(
                discord.Colour.green()
                if healthy
                else
                discord.Colour.red()
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

        repositories = status.get(
            "repositories",
            [],
        )

        embed.add_field(
            name=(
                f"Repositories "
                f"`{len(repositories)}`"
            ),
            value=(
                "\n".join(
                    f"{EMOJI['approved']} `{repo}`"
                    for repo in repositories
                )
                if repositories
                else
                "No repositories bound."
            )[:1024],
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

        await self.edit_panel(
            interaction,
            embed,
        )

    # ========================================================
    # CACHE
    # ========================================================

    async def show_cache(
        self,
        interaction: discord.Interaction,
    ) -> None:

        if not interaction.response.is_done():

            await interaction.response.defer(
                ephemeral=True
            )

        guilds = len(
            self.bot.guilds
        )

        users = len(
            self.bot.users
        )

        channels = sum(
            len(
                guild.channels
            )
            for guild
            in self.bot.guilds
        )

        roles = sum(
            len(
                guild.roles
            )
            for guild
            in self.bot.guilds
        )

        emojis = len(
            self.bot.emojis
        )

        threads = sum(
            len(
                guild.threads
            )
            for guild
            in self.bot.guilds
        )

        embed = EmbedFactory.base(
            title=(
                f"{EMOJI['dev']} "
                "Runtime Cache"
            ),
        )

        embed.add_field(
            name="Discord Cache",
            value=(
                f"**Guilds:** `{guilds:,}`\n"
                f"**Users:** `{users:,}`\n"
                f"**Channels:** `{channels:,}`\n"
                f"**Roles:** `{roles:,}`\n"
                f"**Emojis:** `{emojis:,}`\n"
                f"**Threads:** `{threads:,}`"
            ),
            inline=False,
        )

        embed.add_field(
            name="Bot State",
            value=(
                f"**Voice Clients:** "
                f"`{len(self.bot.voice_clients):,}`\n"
                f"**Extensions:** "
                f"`{len(self.bot.extensions):,}`\n"
                f"**Commands:** "
                f"`{len(self.bot.tree.get_commands()):,}`"
            ),
            inline=False,
        )

        embed.add_field(
            name="Diagnostic Log",
            value=(
                f"`{len(MEMORY_HANDLER.entries):,}` "
                f"/ `{MAX_LOG_ENTRIES}` entries"
            ),
            inline=False,
        )

        await self.edit_panel(
            interaction,
            embed,
        )

    # ========================================================
    # GATEWAY
    # ========================================================

    async def show_gateway(
        self,
        interaction: discord.Interaction,
    ) -> None:

        if not interaction.response.is_done():

            await interaction.response.defer(
                ephemeral=True
            )

        embed = EmbedFactory.base(
            title=(
                f"{EMOJI['moon']} "
                "Gateway / Shard"
            ),
        )

        shards = getattr(
            self.bot,
            "shards",
            None,
        )

        if not shards:

            embed.description = (
                "Single gateway session."
            )

            embed.add_field(
                name="Gateway",
                value=(
                    f"**Ready:** "
                    f"{yes_no(self.bot.is_ready())}\n"
                    f"**Latency:** "
                    f"`{round(self.bot.latency * 1000)}ms`\n"
                    f"**Guilds:** "
                    f"`{len(self.bot.guilds):,}`"
                ),
                inline=False,
            )

        else:

            embed.description = (
                f"`{len(shards)}` active shard(s)."
            )

            for shard_id, shard in sorted(
                shards.items()
            ):

                guilds = [
                    guild
                    for guild
                    in self.bot.guilds
                    if guild.shard_id
                    == shard_id
                ]

                embed.add_field(
                    name=f"Shard {shard_id}",
                    value=(
                        f"**Latency:** "
                        f"`{round(shard.latency * 1000)}ms`\n"
                        f"**Guilds:** "
                        f"`{len(guilds):,}`"
                    ),
                    inline=True,
                )

        await self.edit_panel(
            interaction,
            embed,
        )

    # ========================================================
    # SYSTEM INFO
    # ========================================================

    async def show_system(
        self,
        interaction: discord.Interaction,
    ) -> None:

        if not interaction.response.is_done():

            await interaction.response.defer(
                ephemeral=True
            )

        embed = EmbedFactory.base(
            title=(
                f"{EMOJI['dev']} "
                "Host Diagnostics"
            ),
        )

        embed.add_field(
            name="Python",
            value=(
                f"**Version:** "
                f"`{platform.python_version()}`\n"
                f"**Implementation:** "
                f"`{platform.python_implementation()}`\n"
                f"**Executable:** "
                f"`{truncate(sys.executable, 100)}`"
            ),
            inline=False,
        )

        embed.add_field(
            name="Host",
            value=(
                f"**OS:** "
                f"`{platform.system()}`\n"
                f"**Release:** "
                f"`{platform.release()}`\n"
                f"**Machine:** "
                f"`{platform.machine()}`\n"
                f"**Processor:** "
                f"`{truncate(platform.processor() or 'Unknown', 100)}`"
            ),
            inline=False,
        )

        embed.add_field(
            name="Runtime",
            value=(
                f"**Ready:** "
                f"{yes_no(self.bot.is_ready())}\n"
                f"**Latency:** "
                f"`{round(self.bot.latency * 1000)}ms`"
            ),
            inline=True,
        )

        embed.add_field(
            name="Application",
            value=(
                f"**Guilds:** "
                f"`{len(self.bot.guilds):,}`\n"
                f"**Users:** "
                f"`{len(self.bot.users):,}`"
            ),
            inline=True,
        )

        await self.edit_panel(
            interaction,
            embed,
        )

    # ========================================================
    # HEALTH
    # ========================================================

    async def show_health(
        self,
        interaction: discord.Interaction,
    ) -> None:

        if not interaction.response.is_done():

            await interaction.response.defer(
                ephemeral=True
            )

        started = time.perf_counter()

        try:

            database_ok = bool(
                await db.ping()
            )

        except Exception:

            database_ok = False

        discord_ok = (
            self.bot.is_ready()
        )

        elapsed = (
            time.perf_counter()
            - started
        ) * 1000

        overall = (
            discord_ok
            and database_ok
        )

        embed = EmbedFactory.base(
            title=(
                f"{EMOJI['moon']} "
                "Lunar Health Check"
            ),
            description=(
                f"Overall: "
                f"{status_badge(overall)}"
            ),
            color=(
                discord.Colour.green()
                if overall
                else
                discord.Colour.red()
            ),
        )

        embed.add_field(
            name="Discord",
            value=(
                f"{status_badge(discord_ok)}\n"
                f"`{round(self.bot.latency * 1000)}ms`"
            ),
            inline=True,
        )

        embed.add_field(
            name="ScyllaDB",
            value=(
                status_badge(
                    database_ok
                )
            ),
            inline=True,
        )

        embed.add_field(
            name="Check Time",
            value=(
                f"`{round(elapsed, 2)}ms`"
            ),
            inline=True,
        )

        await self.edit_panel(
            interaction,
            embed,
        )

    # ========================================================
    # COMMAND STATISTICS
    # ========================================================

    async def show_command_stats(
        self,
        interaction: discord.Interaction,
    ) -> None:

        if not interaction.response.is_done():

            await interaction.response.defer(
                ephemeral=True
            )

        if db.command_stats is None:

            await self.edit_panel(
                interaction,
                EmbedFactory.error(
                    "Statistics Unavailable",
                    (
                        "The command statistics repository "
                        "is not currently bound."
                    ),
                ),
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

            await self.edit_panel(
                interaction,
                EmbedFactory.error(
                    "Statistics Failed",
                    (
                        f"```text\n"
                        f"{truncate(exc, 1200)}"
                        f"\n```"
                    ),
                ),
            )

            return

        embed = EmbedFactory.base(
            title=(
                f"{EMOJI['dev']} "
                "Command Analytics"
            ),
            description=(
                f"Total recorded invocations: "
                f"`{total:,}`"
            ),
        )

        if rows:

            lines = []

            for index, row in enumerate(
                rows[:15],
                start=1,
            ):

                name = getattr(
                    row,
                    "command_name",
                    "unknown",
                )

                uses = int(
                    getattr(
                        row,
                        "uses",
                        0,
                    )
                    or 0
                )

                lines.append(
                    f"`{index}.` `/{name}` "
                    f"— **{uses:,}**"
                )

            embed.add_field(
                name="Top Commands",
                value="\n".join(
                    lines
                ),
                inline=False,
            )

        else:

            embed.add_field(
                name="Usage",
                value=(
                    "No command usage has been recorded."
                ),
                inline=False,
            )

        await self.edit_panel(
            interaction,
            embed,
        )

    # ========================================================
    # MAINTENANCE
    # ========================================================

    async def enable_maintenance(
        self,
        interaction: discord.Interaction,
        reason: str,
    ) -> None:

        if db.variables is None:

            await interaction.response.send_message(
                embed=EmbedFactory.error(
                    "Database Unavailable",
                    (
                        "The variables repository is unavailable, "
                        "so maintenance state cannot be persisted."
                    ),
                ),
                ephemeral=True,
            )

            return

        try:

            await db.variables.set_maintenance(
                True,
                reason=reason,
                changed_by=interaction.user.id,
            )

        except Exception as exc:

            await interaction.response.send_message(
                embed=EmbedFactory.error(
                    "Maintenance Failed",
                    (
                        f"```text\n"
                        f"{truncate(exc, 1000)}"
                        f"\n```"
                    ),
                ),
                ephemeral=True,
            )

            return

        self.bot.maintenance_mode = True
        self.bot.maintenance_reason = reason

        logger.warning(
            "Maintenance enabled by %s | %s",
            interaction.user.id,
            reason,
        )

        await interaction.response.send_message(
            embed=EmbedFactory.success(
                "Maintenance Enabled",
                (
                    "Lunar maintenance mode is now active.\n\n"
                    f"**Reason:**\n"
                    f"> {truncate(reason, 700)}"
                ),
            ),
            ephemeral=True,
        )

    async def disable_maintenance(
        self,
        interaction: discord.Interaction,
    ) -> None:

        if db.variables is None:

            await interaction.response.send_message(
                embed=EmbedFactory.error(
                    "Database Unavailable",
                    (
                        "The variables repository is unavailable."
                    ),
                ),
                ephemeral=True,
            )

            return

        try:

            await db.variables.set_maintenance(
                False,
                reason="",
                changed_by=interaction.user.id,
            )

        except Exception as exc:

            await interaction.response.send_message(
                embed=EmbedFactory.error(
                    "Maintenance Failed",
                    (
                        f"```text\n"
                        f"{truncate(exc, 1000)}"
                        f"\n```"
                    ),
                ),
                ephemeral=True,
            )

            return

        self.bot.maintenance_mode = False
        self.bot.maintenance_reason = ""

        logger.info(
            "Maintenance disabled by %s",
            interaction.user.id,
        )

        await interaction.response.send_message(
            embed=EmbedFactory.success(
                "Maintenance Disabled",
                (
                    "Lunar maintenance mode has been disabled."
                ),
            ),
            ephemeral=True,
        )

    # ========================================================
    # LOG VIEW ENTRY
    # ========================================================

    async def show_logs(
        self,
        interaction: discord.Interaction,
    ) -> None:

        view = LogView(
            self,
            interaction.user.id,
        )

        if interaction.response.is_done():

            await interaction.edit_original_response(
                embed=view.build_embed(),
                view=view,
            )

        else:

            await interaction.response.send_message(
                embed=view.build_embed(),
                view=view,
                ephemeral=True,
            )

    # ========================================================
    # PANEL EDIT
    # ========================================================

    async def edit_panel(
        self,
        interaction: discord.Interaction,
        embed: discord.Embed,
    ) -> None:

        view = SystemDashboard(
            self,
            interaction.user.id,
        )

        if interaction.response.is_done():

            await interaction.edit_original_response(
                embed=embed,
                view=view,
            )

        else:

            await interaction.response.send_message(
                embed=embed,
                view=view,
                ephemeral=True,
            )

    # ========================================================
    # DASHBOARD REFRESH
    # ========================================================

    async def show_dashboard(
        self,
        interaction: discord.Interaction,
        *,
        edit: bool = False,
    ) -> None:

        embed = (
            self.build_dashboard_embed()
        )

        view = SystemDashboard(
            self,
            interaction.user.id,
        )

        if edit:

            await interaction.response.edit_message(
                embed=embed,
                view=view,
            )

        else:

            await interaction.response.send_message(
                embed=embed,
                view=view,
                ephemeral=True,
            )

    # ========================================================
    # RESULT FORMATTER
    # ========================================================

    @staticmethod
    def format_result(
        result: object,
    ) -> str:

        if result is None:
            return "None"

        if isinstance(
            result,
            str,
        ):

            value = result

        else:

            try:

                value = repr(
                    result
                )

            except Exception:

                value = str(
                    result
                )

        return truncate(
            value,
            3800,
        )

    # ========================================================
    # COG LOAD
    # ========================================================

    async def cog_load(
        self,
    ) -> None:

        install_memory_handler()

        try:

            if db.variables is None:
                return

            state = (
                await db.variables.get_maintenance()
            )

            self.bot.maintenance_mode = bool(
                state.get(
                    "enabled",
                    False,
                )
            )

            self.bot.maintenance_reason = (
                state.get(
                    "reason",
                    "",
                )
                or ""
            )

        except Exception:

            logger.exception(
                "Failed loading maintenance state."
            )


# ============================================================
# SETUP
# ============================================================

async def setup(
    bot: commands.Bot,
) -> None:

    await bot.add_cog(
        System(bot)
    )