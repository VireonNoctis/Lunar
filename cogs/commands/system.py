from __future__ import annotations

import asyncio
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

# Fake loading timings.
DASHBOARD_LOADING = 1.20
DIAGNOSTICS_LOADING = 1.35
LOGS_LOADING = 0.90
CACHE_LOADING = 1.00
DATABASE_LOADING = 1.35
GATEWAY_LOADING = 1.00
SYSTEM_LOADING = 1.10
HEALTH_LOADING = 1.15
COMMAND_STATS_LOADING = 1.00
SECURITY_LOADING = 0.85
MAINTENANCE_LOADING = 1.25
EVAL_LOADING = 1.10

LOG_LEVELS = {
    "all": None,
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "warning": logging.WARNING,
    "error": logging.ERROR,
    "critical": logging.CRITICAL,
}


# ============================================================
# LOGGER
# ============================================================

logger = logging.getLogger("lunar.system")


# ============================================================
# STORED LOG
# ============================================================

@dataclass(slots=True)
class StoredLog:
    timestamp: datetime
    level: int
    logger_name: str
    message: str


# ============================================================
# MEMORY LOG HANDLER
# ============================================================

class MemoryLogHandler(logging.Handler):

    def __init__(
        self,
        max_entries: int = MAX_LOG_ENTRIES,
    ) -> None:

        super().__init__()

        self.entries: deque[StoredLog] = deque(
            maxlen=max_entries
        )

    def emit(
        self,
        record: logging.LogRecord,
    ) -> None:

        try:

            message = self.format(record)

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
            pass

    def recent(
        self,
        *,
        limit: int = 25,
        level: Optional[int] = None,
    ) -> list[StoredLog]:

        entries = list(self.entries)

        if level is not None:

            entries = [
                entry
                for entry in entries
                if entry.level >= level
            ]

        return entries[-limit:]


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
    return datetime.now(timezone.utc)


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

    parts: list[str] = []

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

    timestamp = int(
        value.timestamp()
    )

    return (
        f"<t:{timestamp}:F>"
        f" • "
        f"<t:{timestamp}:R>"
    )


def truncate(
    value,
    maximum: int,
) -> str:

    value = str(value)

    if len(value) <= maximum:
        return value

    return (
        value[:maximum - 3]
        + "..."
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


async def fake_loading(
    interaction: discord.Interaction,
    message: str,
    delay: float,
) -> None:

    """
    Creates a consistent fake loading process.

    This is intentionally visual only and does not perform
    unnecessary backend work.
    """

    try:

        if not interaction.response.is_done():

            await interaction.response.send_message(
                f"{EMOJI['loading']} {message}",
                ephemeral=True,
            )

        else:

            await interaction.followup.send(
                f"{EMOJI['loading']} {message}",
                ephemeral=True,
            )

        await asyncio.sleep(
            delay
        )

    except discord.HTTPException:

        await asyncio.sleep(
            delay
        )


async def defer_loading(
    interaction: discord.Interaction,
    delay: float,
) -> None:

    if not interaction.response.is_done():

        await interaction.response.defer(
            ephemeral=True,
            thinking=True,
        )

    await asyncio.sleep(
        delay
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
# OWNER CHECK
# ============================================================

def owner_only():

    async def predicate(
        interaction: discord.Interaction,
    ) -> bool:

        if interaction.user.id in OWNERS:
            return True

        message = (
            f"{EMOJI['denied']} "
            "**Access Denied**\n\n"
            "This system panel is restricted to "
            "the Lunar bot owners."
        )

        try:

            if not interaction.response.is_done():

                await interaction.response.send_message(
                    message,
                    ephemeral=True,
                )

            else:

                await interaction.followup.send(
                    message,
                    ephemeral=True,
                )

        except discord.HTTPException:
            pass

        return False

    return app_commands.check(
        predicate
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
        entries: Optional[list[StoredLog]] = None,
        *,
        level_name: str = "all",
        per_page: int = 8,
    ) -> None:

        super().__init__(
            timeout=300
        )

        self.cog = cog
        self.owner_id = owner_id
        self.level_name = level_name
        self.per_page = per_page
        self.page = 0

        self.entries = (
            entries
            if entries is not None
            else MEMORY_HANDLER.recent(
                limit=100,
                level=LOG_LEVELS.get(
                    level_name
                ),
            )
        )

        self.max_page = max(
            0,
            (
                len(self.entries) - 1
            )
            // self.per_page,
        )

        self.sync_buttons()

    # ========================================================
    # CHECK
    # ========================================================

    async def interaction_check(
        self,
        interaction: discord.Interaction,
    ) -> bool:

        if interaction.user.id != self.owner_id:

            await interaction.response.send_message(
                f"{EMOJI['denied']} "
                "Only the owner who opened this panel "
                "can use these controls.",
                ephemeral=True,
            )

            return False

        return True

    # ========================================================
    # BUTTON STATE
    # ========================================================

    def sync_buttons(
        self,
    ) -> None:

        self.previous_button.disabled = (
            self.page <= 0
        )

        self.next_button.disabled = (
            self.page >= self.max_page
        )

    # ========================================================
    # EMBED
    # ========================================================

    def build_embed(
        self,
    ) -> discord.Embed:

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
                f"{EMOJI['logs']} "
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

        lines: list[str] = []

        for entry in page_entries:

            timestamp = int(
                entry.timestamp.timestamp()
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
        emoji=EMOJI["left"],
        style=discord.ButtonStyle.secondary,
        row=0,
    )
    async def previous_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:

        await interaction.response.defer(
            ephemeral=True,
            thinking=True,
        )

        await asyncio.sleep(
            0.45
        )

        self.page = max(
            0,
            self.page - 1,
        )

        self.sync_buttons()

        await interaction.edit_original_response(
            embed=self.build_embed(),
            view=self,
        )

    # ========================================================
    # NEXT
    # ========================================================

    @discord.ui.button(
        label="Next",
        emoji=EMOJI["right"],
        style=discord.ButtonStyle.secondary,
        row=0,
    )
    async def next_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:

        await interaction.response.defer(
            ephemeral=True,
            thinking=True,
        )

        await asyncio.sleep(
            0.45
        )

        self.page = min(
            self.max_page,
            self.page + 1,
        )

        self.sync_buttons()

        await interaction.edit_original_response(
            embed=self.build_embed(),
            view=self,
        )

    # ========================================================
    # REFRESH
    # ========================================================

    @discord.ui.button(
        label="Refresh",
        emoji=EMOJI["loading"],
        style=discord.ButtonStyle.primary,
        row=0,
    )
    async def refresh_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:

        await interaction.response.defer(
            ephemeral=True,
            thinking=True,
        )

        await asyncio.sleep(
            LOGS_LOADING
        )

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

        self.sync_buttons()

        await interaction.edit_original_response(
            embed=self.build_embed(),
            view=self,
        )

    # ========================================================
    # BACK
    # ========================================================

    @discord.ui.button(
        label="Dashboard",
        emoji=EMOJI["left"],
        style=discord.ButtonStyle.secondary,
        row=1,
    )
    async def dashboard_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:

        await interaction.response.defer(
            ephemeral=True,
            thinking=True,
        )

        await asyncio.sleep(
            0.65
        )

        await self.cog.show_dashboard(
            interaction,
            edit=True,
        )

        self.stop()

    # ========================================================
    # CLOSE
    # ========================================================

    @discord.ui.button(
        label="Close",
        emoji=EMOJI["denied"],
        style=discord.ButtonStyle.danger,
        row=1,
    )
    async def close_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:

        for child in self.children:

            if isinstance(
                child,
                discord.ui.Button,
            ):
                child.disabled = True

        await interaction.response.edit_message(
            view=self
        )

        self.stop()

    # ========================================================
    # TIMEOUT
    # ========================================================

    async def on_timeout(
        self,
    ) -> None:

        for child in self.children:

            if isinstance(
                child,
                discord.ui.Button,
            ):
                child.disabled = True


# ============================================================
# SYSTEM DASHBOARD
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

    # ========================================================
    # OWNER CHECK
    # ========================================================

    async def interaction_check(
        self,
        interaction: discord.Interaction,
    ) -> bool:

        if interaction.user.id != self.owner_id:

            await interaction.response.send_message(
                f"{EMOJI['denied']} "
                "Only the owner who opened this dashboard "
                "can use these controls.",
                ephemeral=True,
            )

            return False

        return True

    # ========================================================
    # ROW 0
    # ========================================================

    @discord.ui.button(
        label="Diagnostics",
        emoji=EMOJI["diagnostics"],
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
        emoji=EMOJI["logs"],
        style=discord.ButtonStyle.secondary,
        row=0,
    )
    async def logs(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:

        await self.cog.show_logs(
            interaction
        )

    @discord.ui.button(
        label="Database",
        emoji=EMOJI["db"],
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
        emoji=EMOJI["cache"],
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

    # ========================================================
    # ROW 1
    # ========================================================

    @discord.ui.button(
        label="Gateway",
        emoji=EMOJI["gateway"],
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
        emoji=EMOJI["system"],
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
        emoji=EMOJI["health"],
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
        emoji=EMOJI["commands"],
        style=discord.ButtonStyle.secondary,
        row=1,
    )
    async def commands_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:

        await self.cog.show_command_stats(
            interaction
        )

    # ========================================================
    # ROW 2
    # ========================================================

    @discord.ui.button(
        label="Maintenance",
        emoji=EMOJI["maintenance"],
        style=discord.ButtonStyle.danger,
        row=2,
    )
    async def maintenance(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:

        await self.cog.open_maintenance(
            interaction
        )

    @discord.ui.button(
        label="Eval",
        emoji=EMOJI["eval"],
        style=discord.ButtonStyle.primary,
        row=2,
    )
    async def eval_button(
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
        label="Security",
        emoji=EMOJI["security"],
        style=discord.ButtonStyle.secondary,
        row=2,
    )
    async def security(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:

        await self.cog.show_security(
            interaction
        )

    @discord.ui.button(
        label="Refresh",
        emoji=EMOJI["loading"],
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

    # ========================================================
    # ROW 3
    # ========================================================

    @discord.ui.button(
        label="Close",
        emoji=EMOJI["denied"],
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
# MAINTENANCE MODAL
# ============================================================

class MaintenanceModal(
    discord.ui.Modal,
    title="Lunar Maintenance Control",
):

    reason = discord.ui.TextInput(
        label="Maintenance Reason",
        placeholder=(
            "Example: Database maintenance..."
        ),
        style=discord.TextStyle.paragraph,
        required=False,
        max_length=500,
    )

    def __init__(
        self,
        cog: "System",
        owner_id: int,
    ) -> None:

        super().__init__()

        self.cog = cog
        self.owner_id = owner_id

    async def on_submit(
        self,
        interaction: discord.Interaction,
    ) -> None:

        if interaction.user.id != self.owner_id:

            await interaction.response.send_message(
                f"{EMOJI['denied']} "
                "You cannot use this modal.",
                ephemeral=True,
            )

            return

        await interaction.response.defer(
            ephemeral=True,
            thinking=True,
        )

        await asyncio.sleep(
            MAINTENANCE_LOADING
        )

        reason = (
            str(self.reason.value).strip()
            or "Lunar is currently undergoing maintenance."
        )

        try:

            if db.variables is None:

                await interaction.followup.send(
                    embed=EmbedFactory.error(
                        "Database Unavailable",
                        (
                            "The maintenance repository is unavailable."
                        ),
                    ),
                    ephemeral=True,
                )

                return

            await db.variables.set_maintenance(
                True,
                reason=reason,
                changed_by=interaction.user.id,
            )

            self.cog.bot.maintenance_mode = True
            self.cog.bot.maintenance_reason = reason

            try:

                if db.audit is not None:

                    await db.audit.record(
                        interaction.guild.id
                        if interaction.guild
                        else 0,
                        actor_id=interaction.user.id,
                        action="maintenance_enable",
                        target_id=None,
                        reason=reason,
                        metadata={
                            "source": "system.py",
                        },
                    )

            except Exception:

                logger.exception(
                    "Failed to audit maintenance enable"
                )

            logger.warning(
                "Maintenance mode ENABLED by %s | %s",
                interaction.user.id,
                reason,
            )

            await interaction.followup.send(
                embed=EmbedFactory.success(
                    "Maintenance Enabled",
                    (
                        "Lunar maintenance mode is now active.\n\n"
                        f"**Reason:**\n"
                        f"> {truncate(reason, 700)}\n\n"
                        f"{EMOJI['security']} "
                        "The state has been persisted to ScyllaDB."
                    ),
                ),
                ephemeral=True,
            )

        except Exception as exc:

            logger.exception(
                "Failed to enable maintenance mode"
            )

            await interaction.followup.send(
                embed=EmbedFactory.error(
                    "Maintenance Failed",
                    (
                        "The maintenance state could not be saved.\n\n"
                        f"```text\n"
                        f"{truncate(exc, 1200)}"
                        f"\n```"
                    ),
                ),
                ephemeral=True,
            )


# ============================================================
# EVAL MODAL
# ============================================================

class EvalModal(
    discord.ui.Modal,
    title="Lunar Developer Console",
):

    code = discord.ui.TextInput(
        label="Python Expression",
        placeholder=(
            "bot.user\n"
            "bot.latency\n"
            "len(bot.guilds)"
        ),
        style=discord.TextStyle.paragraph,
        required=True,
        max_length=1500,
    )

    def __init__(
        self,
        cog: "System",
        owner_id: int,
    ) -> None:

        super().__init__()

        self.cog = cog
        self.owner_id = owner_id

    async def on_submit(
        self,
        interaction: discord.Interaction,
    ) -> None:

        if interaction.user.id != self.owner_id:

            await interaction.response.send_message(
                f"{EMOJI['denied']} "
                "You cannot use this developer console.",
                ephemeral=True,
            )

            return

        await interaction.response.defer(
            ephemeral=True,
            thinking=True,
        )

        await asyncio.sleep(
            EVAL_LOADING
        )

        code = str(
            self.code.value
        ).strip()

        if code.startswith("```"):

            lines = code.splitlines()

            if lines:
                lines = lines[1:]

            if lines and lines[-1].strip() == "```":
                lines.pop()

            code = "\n".join(lines)

        environment = {
            "bot": self.cog.bot,
            "ctx": None,
            "message": None,
            "guild": interaction.guild,
            "channel": interaction.channel,
            "author": interaction.user,
            "interaction": interaction,
            "discord": discord,
            "commands": commands,
            "app_commands": app_commands,
            "EMOJI": EMOJI,
            "db": db,
        }

        try:

            result = eval(
                code,
                {
                    "__builtins__": {},
                },
                environment,
            )

            if result is None:

                result_text = "None"

            elif isinstance(
                result,
                str,
            ):

                result_text = result

            else:

                try:

                    result_text = repr(
                        result
                    )

                except Exception:

                    result_text = str(
                        result
                    )

            if len(result_text) > 3900:

                result_text = (
                    result_text[:3900]
                    + "\n..."
                )

            embed = EmbedFactory.success(
                "Eval Result",
                "",
            )

            embed.add_field(
                name=(
                    f"{EMOJI['right']} "
                    "Output"
                ),
                value=(
                    "```py\n"
                    f"{result_text}"
                    "\n```"
                ),
                inline=False,
            )

            embed.set_footer(
                text=(
                    f"Executed by "
                    f"{interaction.user}"
                )
            )

            await interaction.followup.send(
                embed=embed,
                ephemeral=True,
            )

        except Exception as error:

            error_text = (
                f"{type(error).__name__}: "
                f"{error}"
            )

            if len(error_text) > 3900:

                error_text = (
                    error_text[:3900]
                    + "\n..."
                )

            embed = EmbedFactory.error(
                "Eval Error",
                (
                    "```py\n"
                    f"{error_text}"
                    "\n```"
                ),
            )

            embed.set_footer(
                text=(
                    f"Executed by "
                    f"{interaction.user}"
                )
            )

            await interaction.followup.send(
                embed=embed,
                ephemeral=True,
            )


# ============================================================
# EVAL HELP VIEW
# ============================================================

EVAL_PAGES = [

    (
        f"{EMOJI['new1']}{EMOJI['new2']} **Bot**\n\n"
        "```py\n"
        "bot\n"
        "bot.user\n"
        "bot.user.name\n"
        "bot.user.id\n"
        "bot.user.avatar\n"
        "bot.latency\n"
        "bot.guilds\n"
        "bot.users\n"
        "bot.application_id\n"
        "bot.intents\n"
        "bot.extensions\n"
        "```"
    ),

    (
        f"{EMOJI['new1']}{EMOJI['new2']} **Guild**\n\n"
        "```py\n"
        "interaction.guild.name\n"
        "interaction.guild.id\n"
        "interaction.guild.owner_id\n"
        "interaction.guild.member_count\n"
        "interaction.guild.created_at\n"
        "interaction.guild.icon\n"
        "interaction.guild.banner\n"
        "interaction.guild.features\n"
        "interaction.guild.verification_level\n"
        "interaction.guild.premium_tier\n"
        "```"
    ),

    (
        f"{EMOJI['new1']}{EMOJI['new2']} **User**\n\n"
        "```py\n"
        "interaction.user.name\n"
        "interaction.user.id\n"
        "interaction.user.created_at\n"
        "interaction.user.avatar\n"
        "interaction.user.display_avatar\n"
        "interaction.user.mention\n"
        "interaction.user.bot\n"
        "```"
    ),

    (
        f"{EMOJI['new1']}{EMOJI['new2']} **Channels**\n\n"
        "```py\n"
        "interaction.channel\n"
        "interaction.channel.id\n"
        "interaction.channel.name\n"
        "interaction.channel.type\n"
        "interaction.channel.created_at\n"
        "```"
    ),

    (
        f"{EMOJI['new1']}{EMOJI['new2']} **Members / Roles**\n\n"
        "```py\n"
        "len(interaction.guild.members)\n"
        "[m.name for m in interaction.guild.members]\n"
        "[m for m in interaction.guild.members if m.bot]\n"
        "[r.name for r in interaction.guild.roles]\n"
        "[r.id for r in interaction.guild.roles]\n"
        "interaction.user.roles\n"
        "interaction.user.guild_permissions\n"
        "```"
    ),

    (
        f"{EMOJI['new1']}{EMOJI['new2']} **Bot Collections**\n\n"
        "```py\n"
        "len(bot.guilds)\n"
        "len(bot.users)\n"
        "len(bot.emojis)\n"
        "[g.name for g in bot.guilds]\n"
        "[g.id for g in bot.guilds]\n"
        "[u.name for u in bot.users]\n"
        "[e.name for e in bot.emojis]\n"
        "```"
    ),

    (
        f"{EMOJI['new1']}{EMOJI['new2']} **System**\n\n"
        "```py\n"
        "import os\n"
        "import sys\n"
        "import platform\n\n"
        "os.getpid()\n"
        "platform.system()\n"
        "platform.platform()\n"
        "platform.machine()\n"
        "sys.version\n"
        "sys.platform\n"
        "```"
    ),

    (
        f"{EMOJI['new1']}{EMOJI['new2']} **Database**\n\n"
        "```py\n"
        "db\n"
        "db.users\n"
        "db.guilds\n"
        "db.github\n"
        "db.stats\n"
        "db.command_stats\n"
        "db.giveaways\n"
        "```"
    ),

    (
        f"{EMOJI['new1']}{EMOJI['new2']} **Advanced**\n\n"
        "```py\n"
        "type(bot)\n"
        "type(interaction)\n"
        "dir(bot)\n"
        "dir(interaction)\n"
        "bot.extensions\n"
        "bot.cogs\n"
        "bot.tree.get_commands()\n"
        "```"
    ),

    (
        f"{EMOJI['new1']}{EMOJI['new2']} **Examples**\n\n"
        "```py\n"
        "bot.user\n"
        "bot.latency\n"
        "len(bot.guilds)\n"
        "len(bot.users)\n"
        "len(bot.emojis)\n"
        "interaction.guild.name\n"
        "interaction.user.name\n"
        "EMOJI['lunar']\n"
        "```"
    ),
]


# ============================================================
# EVAL HELP VIEW
# ============================================================

class EvalHelpView(
    discord.ui.View
):

    def __init__(
        self,
        owner_id: int,
    ) -> None:

        super().__init__(
            timeout=180
        )

        self.owner_id = owner_id
        self.page = 0

    async def interaction_check(
        self,
        interaction: discord.Interaction,
    ) -> bool:

        if interaction.user.id != self.owner_id:

            await interaction.response.send_message(
                f"{EMOJI['denied']} "
                "Only the owner who opened this help panel "
                "can use it.",
                ephemeral=True,
            )

            return False

        return True

    def build_embed(
        self,
    ) -> discord.Embed:

        embed = EmbedFactory.base(
            title=(
                f"{EMOJI['eval']} "
                "Lunar Eval System"
            ),
            description=EVAL_PAGES[
                self.page
            ],
            color=discord.Colour.from_rgb(
                212,
                175,
                55,
            ),
        )

        embed.set_footer(
            text=(
                f"Page {self.page + 1}"
                f"/{len(EVAL_PAGES)}"
                " • Lunar Developer Console"
            )
        )

        return embed

    @discord.ui.button(
        emoji=EMOJI["left"],
        label="Previous",
        style=discord.ButtonStyle.secondary,
    )
    async def previous(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:

        await interaction.response.defer(
            ephemeral=True,
            thinking=True,
        )

        await asyncio.sleep(
            0.45
        )

        self.page -= 1

        if self.page < 0:

            self.page = (
                len(EVAL_PAGES) - 1
            )

        await interaction.edit_original_response(
            embed=self.build_embed(),
            view=self,
        )

    @discord.ui.button(
        emoji=EMOJI["right"],
        label="Next",
        style=discord.ButtonStyle.secondary,
    )
    async def next(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:

        await interaction.response.defer(
            ephemeral=True,
            thinking=True,
        )

        await asyncio.sleep(
            0.45
        )

        self.page += 1

        if self.page >= len(EVAL_PAGES):

            self.page = 0

        await interaction.edit_original_response(
            embed=self.build_embed(),
            view=self,
        )

    @discord.ui.button(
        emoji=EMOJI["left"],
        label="Dashboard",
        style=discord.ButtonStyle.primary,
    )
    async def dashboard(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:

        await interaction.response.defer(
            ephemeral=True,
            thinking=True,
        )

        await asyncio.sleep(
            0.65
        )

        await self.cog_show_dashboard(
            interaction
        )

    async def cog_show_dashboard(
        self,
        interaction: discord.Interaction,
    ) -> None:

        # This helper is replaced by assigning the
        # cog reference below.
        pass

    async def on_timeout(
        self,
    ) -> None:

        for child in self.children:

            if isinstance(
                child,
                discord.ui.Button,
            ):
                child.disabled = True


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
    # COG LOAD
    # ========================================================

    async def cog_load(
        self,
    ) -> None:

        try:

            if db.variables is not None:

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

                logger.info(
                    "Maintenance state loaded | enabled=%s",
                    self.bot.maintenance_mode,
                )

        except Exception:

            logger.exception(
                "Failed to load maintenance state"
            )

    # ========================================================
    # METRICS
    # ========================================================

    def guild_count(
        self,
    ) -> int:

        return len(
            getattr(
                self.bot,
                "guilds",
                [],
            )
        )

    def user_count(
        self,
    ) -> int:

        return len(
            getattr(
                self.bot,
                "users",
                [],
            )
        )

    def channel_count(
        self,
    ) -> int:

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

    def role_count(
        self,
    ) -> int:

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

    def emoji_count(
        self,
    ) -> int:

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

    def thread_count(
        self,
    ) -> int:

        return sum(
            len(
                getattr(
                    guild,
                    "threads",
                    [],
                )
            )
            for guild in getattr(
                self.bot,
                "guilds",
                [],
            )
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

        embed = discord.Embed(
            title=(
                f"{EMOJI['lunar']} "
                "Lunar System Control"
            ),
            description=(
                f"{EMOJI['dev']} "
                "**Owner Control Dashboard**\n\n"
                "Monitor and control the Lunar runtime "
                "from one centralized interface."
            ),
            color=(
                discord.Colour.orange()
                if maintenance
                else discord.Colour.blurple()
            ),
            timestamp=utcnow(),
        )

        embed.set_footer(
            text=COG_NAME
        )

        embed.add_field(
            name=(
                f"{EMOJI['gateway']} "
                "Discord"
            ),
            value=(
                f"{status_badge(self.bot.is_ready())}\n"
                f"`{latency}ms` latency"
            ),
            inline=True,
        )

        embed.add_field(
            name=(
                f"{EMOJI['db']} "
                "Database"
            ),
            value=(
                f"{EMOJI['loading']} "
                "Use **Database** to inspect"
            ),
            inline=True,
        )

        embed.add_field(
            name=(
                f"{EMOJI['maintenance']} "
                "Maintenance"
            ),
            value=(
                f"{EMOJI['question']} `ACTIVE`"
                if maintenance
                else
                f"{EMOJI['approved']} `NORMAL`"
            ),
            inline=True,
        )

        embed.add_field(
            name=(
                f"{EMOJI['system']} "
                "Runtime"
            ),
            value=(
                f"**Uptime:** "
                f"`{fmt_uptime(uptime)}`\n"
                f"**Guilds:** "
                f"`{self.guild_count():,}`\n"
                f"**Users:** "
                f"`{self.user_count():,}`\n"
                f"**Channels:** "
                f"`{self.channel_count():,}`\n"
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
                name=(
                    f"{EMOJI['question']} "
                    "Maintenance Reason"
                ),
                value=(
                    f"> {truncate(reason, 700)}"
                ),
                inline=False,
            )

        if self.bot.user:

            embed.set_thumbnail(
                url=self.bot.user.display_avatar.url
            )

        return embed

    # ========================================================
    # /SYSTEM
    # ========================================================

    @app_commands.command(
        name="system",
        description="Open the Lunar owner system control dashboard.",
    )
    @owner_only()
    async def system_command(
        self,
        interaction: discord.Interaction,
    ) -> None:

        await interaction.response.defer(
            ephemeral=True,
            thinking=True,
        )

        await asyncio.sleep(
            DASHBOARD_LOADING
        )

        view = SystemDashboard(
            self,
            interaction.user.id,
        )

        await interaction.edit_original_response(
            embed=self.build_dashboard_embed(),
            view=view,
            content=None,
        )

    # ========================================================
    # SHOW DASHBOARD
    # ========================================================

    async def show_dashboard(
        self,
        interaction: discord.Interaction,
        *,
        edit: bool = False,
    ) -> None:

        await asyncio.sleep(
            DASHBOARD_LOADING
        )

        view = SystemDashboard(
            self,
            interaction.user.id,
        )

        if edit:

            await interaction.edit_original_response(
                content=None,
                embed=self.build_dashboard_embed(),
                view=view,
            )

        else:

            await interaction.followup.send(
                embed=self.build_dashboard_embed(),
                view=view,
                ephemeral=True,
            )

    # ========================================================
    # DIAGNOSTICS
    # ========================================================

    async def show_diagnostics(
        self,
        interaction: discord.Interaction,
    ) -> None:

        await interaction.response.defer(
            ephemeral=True,
            thinking=True,
        )

        await asyncio.sleep(
            DIAGNOSTICS_LOADING
        )

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
                "Diagnostic database status failed"
            )

        uptime = (
            utcnow()
            - self.started_at
        ).total_seconds()

        latency = (
            round(
                self.bot.latency * 1000
            )
            if self.bot.latency >= 0
            else 0
        )

        embed = EmbedFactory.base(
            title=(
                f"{EMOJI['diagnostics']} "
                "Lunar Diagnostics"
            ),
            description=(
                "Complete runtime diagnostic snapshot."
            ),
        )

        embed.add_field(
            name=(
                f"{EMOJI['system']} "
                "Runtime"
            ),
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
            name=(
                f"{EMOJI['gateway']} "
                "Discord"
            ),
            value=(
                f"**Latency:** `{latency}ms`\n"
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
            name=(
                f"{EMOJI['commands']} "
                "Application"
            ),
            value=(
                f"**Loaded Cogs:** "
                f"`{len(self.bot.extensions):,}`\n"
                f"**Commands:** "
                f"`{len(self.bot.tree.get_commands()):,}`"
            ),
            inline=True,
        )

        embed.add_field(
            name=(
                f"{EMOJI['maintenance']} "
                "Maintenance"
            ),
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
            ),
            inline=True,
        )

        embed.add_field(
            name=(
                f"{EMOJI['db']} "
                "Database"
            ),
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

        await interaction.edit_original_response(
            embed=embed,
            view=SystemDashboard(
                self,
                interaction.user.id,
            ),
        )

    # ========================================================
    # LOGS
    # ========================================================

    async def show_logs(
        self,
        interaction: discord.Interaction,
    ) -> None:

        await interaction.response.defer(
            ephemeral=True,
            thinking=True,
        )

        await asyncio.sleep(
            LOGS_LOADING
        )

        entries = MEMORY_HANDLER.recent(
            limit=100
        )

        view = LogView(
            self,
            interaction.user.id,
            entries,
        )

        await interaction.edit_original_response(
            embed=view.build_embed(),
            view=view,
        )

    # ========================================================
    # CACHE
    # ========================================================

    async def show_cache(
        self,
        interaction: discord.Interaction,
    ) -> None:

        await interaction.response.defer(
            ephemeral=True,
            thinking=True,
        )

        await asyncio.sleep(
            CACHE_LOADING
        )

        voice_clients = len(
            getattr(
                self.bot,
                "voice_clients",
                [],
            )
        )

        commands_count = len(
            self.bot.tree.get_commands()
        )

        embed = EmbedFactory.base(
            title=(
                f"{EMOJI['cache']} "
                "Runtime Cache"
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
                f"**Slash Commands:** `{commands_count:,}`"
            ),
            inline=False,
        )

        embed.add_field(
            name="Diagnostic Cache",
            value=(
                f"**Stored Logs:** "
                f"`{len(MEMORY_HANDLER.entries):,}` / "
                f"`{MAX_LOG_ENTRIES}`\n"
                f"**Runtime Start:** "
                f"{fmt_dt(self.started_at)}"
            ),
            inline=False,
        )

        await interaction.edit_original_response(
            embed=embed,
            view=SystemDashboard(
                self,
                interaction.user.id,
            ),
        )

    # ========================================================
    # DATABASE
    # ========================================================

    async def show_database(
        self,
        interaction: discord.Interaction,
    ) -> None:

        await interaction.response.defer(
            ephemeral=True,
            thinking=True,
        )

        await asyncio.sleep(
            DATABASE_LOADING
        )

        try:

            status = (
                await db.status()
            )

        except Exception as exc:

            logger.exception(
                "Database diagnostics failed"
            )

            await interaction.edit_original_response(
                embed=EmbedFactory.error(
                    "Database Diagnostics Failed",
                    (
                        f"```text\n"
                        f"{truncate(exc, 1500)}"
                        f"\n```"
                    ),
                ),
                view=SystemDashboard(
                    self,
                    interaction.user.id,
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
                f"{EMOJI['db']} "
                "ScyllaDB Diagnostics"
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

        await interaction.edit_original_response(
            embed=embed,
            view=SystemDashboard(
                self,
                interaction.user.id,
            ),
        )

    # ========================================================
    # GATEWAY
    # ========================================================

    async def show_gateway(
        self,
        interaction: discord.Interaction,
    ) -> None:

        await interaction.response.defer(
            ephemeral=True,
            thinking=True,
        )

        await asyncio.sleep(
            GATEWAY_LOADING
        )

        embed = EmbedFactory.base(
            title=(
                f"{EMOJI['gateway']} "
                "Gateway / Shard Console"
            ),
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

        await interaction.edit_original_response(
            embed=embed,
            view=SystemDashboard(
                self,
                interaction.user.id,
            ),
        )

    # ========================================================
    # SYSTEM INFO
    # ========================================================

    async def show_system(
        self,
        interaction: discord.Interaction,
    ) -> None:

        await interaction.response.defer(
            ephemeral=True,
            thinking=True,
        )

        await asyncio.sleep(
            SYSTEM_LOADING
        )

        uptime = (
            utcnow()
            - self.started_at
        ).total_seconds()

        embed = EmbedFactory.base(
            title=(
                f"{EMOJI['system']} "
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
                f"**OS:** `{platform.system()}`\n"
                f"**Release:** `{platform.release()}`\n"
                f"**Machine:** `{platform.machine()}`\n"
                f"**Processor:** "
                f"`{truncate(platform.processor() or 'Unknown', 120)}`"
            ),
            inline=False,
        )

        embed.add_field(
            name="Runtime",
            value=(
                f"**Uptime:** "
                f"`{fmt_uptime(uptime)}`\n"
                f"**Latency:** "
                f"`{round(self.bot.latency * 1000)}ms`\n"
                f"**Ready:** "
                f"{yes_no(self.bot.is_ready())}"
            ),
            inline=False,
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

        embed.add_field(
            name="Discord",
            value=(
                f"**Guilds:** "
                f"`{self.guild_count():,}`\n"
                f"**Users:** "
                f"`{self.user_count():,}`"
            ),
            inline=True,
        )

        await interaction.edit_original_response(
            embed=embed,
            view=SystemDashboard(
                self,
                interaction.user.id,
            ),
        )

    # ========================================================
    # HEALTH
    # ========================================================

    async def show_health(
        self,
        interaction: discord.Interaction,
    ) -> None:

        await interaction.response.defer(
            ephemeral=True,
            thinking=True,
        )

        await asyncio.sleep(
            HEALTH_LOADING
        )

        started = time.perf_counter()

        database_ok = False

        try:

            database_ok = await db.ping()

        except Exception:

            logger.exception(
                "Health database ping failed"
            )

        elapsed = (
            time.perf_counter()
            - started
        ) * 1000

        discord_ok = self.bot.is_ready()

        overall_ok = (
            discord_ok
            and database_ok
        )

        embed = EmbedFactory.base(
            title=(
                f"{EMOJI['health']} "
                "Lunar Health Check"
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
                f"{status_badge(discord_ok)}\n"
                f"`{round(self.bot.latency * 1000)}ms` "
                "gateway latency"
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
            name="Diagnostics",
            value=(
                f"`{round(elapsed, 2)}ms` "
                "database diagnostic time"
            ),
            inline=False,
        )

        await interaction.edit_original_response(
            embed=embed,
            view=SystemDashboard(
                self,
                interaction.user.id,
            ),
        )

    # ========================================================
    # COMMAND STATS
    # ========================================================

    async def show_command_stats(
        self,
        interaction: discord.Interaction,
    ) -> None:

        await interaction.response.defer(
            ephemeral=True,
            thinking=True,
        )

        await asyncio.sleep(
            COMMAND_STATS_LOADING
        )

        if db.command_stats is None:

            await interaction.edit_original_response(
                embed=EmbedFactory.error(
                    "Command Statistics Unavailable",
                    (
                        "The command statistics repository "
                        "is not currently bound."
                    ),
                ),
                view=SystemDashboard(
                    self,
                    interaction.user.id,
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

            logger.exception(
                "Command statistics lookup failed"
            )

            await interaction.edit_original_response(
                embed=EmbedFactory.error(
                    "Statistics Lookup Failed",
                    (
                        f"```text\n"
                        f"{truncate(exc, 1200)}"
                        f"\n```"
                    ),
                ),
                view=SystemDashboard(
                    self,
                    interaction.user.id,
                ),
            )

            return

        embed = EmbedFactory.base(
            title=(
                f"{EMOJI['commands']} "
                "Command Analytics"
            ),
            description=(
                f"**Total recorded invocations:** "
                f"`{total:,}`"
            ),
        )

        if not rows:

            embed.add_field(
                name="Usage",
                value=(
                    "No command usage has been recorded yet."
                ),
                inline=False,
            )

        else:

            lines: list[str] = []

            for index, row in enumerate(
                rows[:15],
                start=1,
            ):

                command_name = getattr(
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
                    f"`{index:>2}.` "
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
            value=f"`{len(rows):,}`",
            inline=True,
        )

        embed.add_field(
            name="Storage",
            value="`ScyllaDB`",
            inline=True,
        )

        await interaction.edit_original_response(
            embed=embed,
            view=SystemDashboard(
                self,
                interaction.user.id,
            ),
        )

    # ========================================================
    # SECURITY
    # ========================================================

    async def show_security(
        self,
        interaction: discord.Interaction,
    ) -> None:

        await interaction.response.defer(
            ephemeral=True,
            thinking=True,
        )

        await asyncio.sleep(
            SECURITY_LOADING
        )

        embed = EmbedFactory.base(
            title=(
                f"{EMOJI['security']} "
                "Lunar Security Console"
            ),
            description=(
                "Current owner and runtime security information."
            ),
        )

        embed.add_field(
            name="Authorized Owners",
            value="\n".join(
                f"{EMOJI['approved']} "
                f"<@{owner_id}> "
                f"`{owner_id}`"
                for owner_id in OWNERS
            ),
            inline=False,
        )

        embed.add_field(
            name="Dashboard",
            value=(
                f"{EMOJI['approved']} Owner restricted\n"
                f"{EMOJI['approved']} Ephemeral interface\n"
                f"{EMOJI['approved']} Per-view executor validation"
            ),
            inline=False,
        )

        embed.add_field(
            name="Developer Console",
            value=(
                f"{EMOJI['approved']} Owner restricted\n"
                f"{EMOJI['approved']} Built-in namespace only\n"
                f"{EMOJI['approved']} Builtins disabled"
            ),
            inline=False,
        )

        await interaction.edit_original_response(
            embed=embed,
            view=SystemDashboard(
                self,
                interaction.user.id,
            ),
        )

    # ========================================================
    # MAINTENANCE
    # ========================================================

    async def open_maintenance(
        self,
        interaction: discord.Interaction,
    ) -> None:

        enabled = bool(
            getattr(
                self.bot,
                "maintenance_mode",
                False,
            )
        )

        if enabled:

            await interaction.response.send_message(
                f"{EMOJI['loading']} "
                "Disabling maintenance mode...",
                ephemeral=True,
            )

            await asyncio.sleep(
                MAINTENANCE_LOADING
            )

            if db.variables is None:

                await interaction.edit_original_response(
                    content=(
                        f"{EMOJI['error']} "
                        "The maintenance repository is unavailable."
                    )
                )

                return

            try:

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
                                "source": "system.py",
                            },
                        )

                except Exception:

                    logger.exception(
                        "Failed to audit maintenance disable"
                    )

                await interaction.edit_original_response(
                    content=(
                        f"{EMOJI['approved']} "
                        "**Maintenance Disabled**\n\n"
                        "Normal command processing may resume."
                    )
                )

                return

            except Exception as exc:

                logger.exception(
                    "Failed to disable maintenance"
                )

                await interaction.edit_original_response(
                    content=(
                        f"{EMOJI['error']} "
                        "Failed to disable maintenance.\n\n"
                        f"```text\n"
                        f"{truncate(exc, 1200)}"
                        f"\n```"
                    )
                )

                return

        await interaction.response.send_modal(
            MaintenanceModal(
                self,
                interaction.user.id,
            )
        )

    # ========================================================
    # EVAL HELP
    # ========================================================

    async def show_eval_help(
        self,
        interaction: discord.Interaction,
    ) -> None:

        view = EvalHelpView(
            interaction.user.id
        )

        # Attach cog to the navigation helper.
        view.cog = self

        await interaction.response.send_message(
            embed=view.build_embed(),
            view=view,
            ephemeral=True,
        )

    # ========================================================
    # PREFIX EVAL
    # ========================================================

    @commands.command(
        name="eval",
        aliases=("ev",),
    )
    async def eval_command(
        self,
        ctx: commands.Context,
        *,
        code: Optional[str] = None,
    ) -> None:

        if ctx.author.id not in OWNERS:

            await ctx.reply(
                f"{EMOJI['denied']} "
                "You do not have permission "
                "to use this command."
            )

            return

        if not code:

            view = EvalHelpView(
                ctx.author.id
            )

            view.cog = self

            await ctx.reply(
                embed=view.build_embed(),
                view=view,
            )

            return

        code = code.strip()

        if code.startswith("```"):

            lines = code.splitlines()

            if lines:
                lines = lines[1:]

            if (
                lines
                and
                lines[-1].strip() == "```"
            ):
                lines.pop()

            code = "\n".join(lines)

        try:

            environment = {
                "bot": self.bot,
                "ctx": ctx,
                "message": ctx.message,
                "guild": ctx.guild,
                "channel": ctx.channel,
                "author": ctx.author,
                "discord": discord,
                "commands": commands,
                "app_commands": app_commands,
                "EMOJI": EMOJI,
                "db": db,
            }

            result = eval(
                code,
                {
                    "__builtins__": {},
                },
                environment,
            )

            if result is None:

                result_text = "None"

            elif isinstance(
                result,
                str,
            ):

                result_text = result

            else:

                result_text = repr(
                    result
                )

            if len(result_text) > 3900:

                result_text = (
                    result_text[:3900]
                    + "\n..."
                )

            embed = EmbedFactory.success(
                "Eval Result",
                "",
            )

            embed.add_field(
                name=(
                    f"{EMOJI['right']} "
                    "Output"
                ),
                value=(
                    "```py\n"
                    f"{result_text}"
                    "\n```"
                ),
                inline=False,
            )

            await ctx.reply(
                embed=embed
            )

        except Exception as error:

            error_text = (
                f"{type(error).__name__}: "
                f"{error}"
            )

            if len(error_text) > 3900:

                error_text = (
                    error_text[:3900]
                    + "\n..."
                )

            await ctx.reply(
                embed=EmbedFactory.error(
                    "Eval Error",
                    (
                        "```py\n"
                        f"{error_text}"
                        "\n```"
                    ),
                )
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