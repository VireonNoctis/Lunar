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

OWNERS = {1419744000977403994, 960946185768685618}
COG_NAME = "Lunar System Control"
MAX_LOG_ENTRIES = 500

DASHBOARD_LOADING = 1.2
DIAGNOSTICS_LOADING = 1.2
LOGS_LOADING = 0.9
DATABASE_LOADING = 1.2
GATEWAY_LOADING = 1.0
SYSTEM_LOADING = 1.0
HEALTH_LOADING = 1.0
COMMAND_STATS_LOADING = 1.0
SECURITY_LOADING = 0.85
MAINTENANCE_LOADING = 1.0
EVAL_LOADING = 1.0

LOG_LEVELS = {
    "all": None,
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "warning": logging.WARNING,
    "error": logging.ERROR,
    "critical": logging.CRITICAL,
}

logger = logging.getLogger("lunar.system")


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
        self.entries: deque[StoredLog] = deque(
            maxlen=max_entries
        )

    def emit(
        self,
        record: logging.LogRecord,
    ) -> None:
        try:
            self.entries.append(
                StoredLog(
                    datetime.fromtimestamp(
                        record.created,
                        timezone.utc,
                    ),
                    record.levelno,
                    record.name,
                    self.format(record),
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


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def fmt_uptime(
    seconds: float,
) -> str:
    seconds = max(
        0,
        int(seconds),
    )

    days, seconds = divmod(
        seconds,
        86400,
    )

    hours, seconds = divmod(
        seconds,
        3600,
    )

    minutes, seconds = divmod(
        seconds,
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

    ts = int(
        value.timestamp()
    )

    return (
        f"<t:{ts}:F>"
        f" • "
        f"<t:{ts}:R>"
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
    value: Optional[bool],
) -> str:
    if value is True:
        return (
            f"{EMOJI['approved']} "
            "`ONLINE`"
        )

    if value is False:
        return (
            f"{EMOJI['denied']} "
            "`OFFLINE`"
        )

    return (
        f"{EMOJI['question']} "
        "`UNKNOWN`"
    )


class EmbedFactory:

    @staticmethod
    def base(
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
            f"{EMOJI['approved']} {title}",
            description,
            discord.Colour.green(),
        )

    @staticmethod
    def error(
        title: str,
        description: str,
    ) -> discord.Embed:

        return EmbedFactory.base(
            f"{EMOJI['error']} {title}",
            description,
            discord.Colour.red(),
        )

    @staticmethod
    def warning(
        title: str,
        description: str,
    ) -> discord.Embed:

        return EmbedFactory.base(
            f"{EMOJI['question']} {title}",
            description,
            discord.Colour.orange(),
        )


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
                    "This system panel is restricted "
                    "to the Lunar bot owners."
                ),
                ephemeral=True,
            )

        except discord.HTTPException:
            pass

        return False

    return app_commands.check(
        predicate
    )


class PanelView(discord.ui.View):

    def __init__(
        self,
        cog: "System",
        owner_id: int,
        *,
        back: bool = True,
        timeout: float = 600,
        root_interaction: Optional[discord.Interaction] = None,
    ) -> None:

        super().__init__(
            timeout=timeout
        )

        self.cog = cog
        self.owner_id = owner_id
        self.root_interaction = root_interaction

        if back:
            self._add_navigation()

    async def interaction_check(
        self,
        interaction: discord.Interaction,
    ) -> bool:

        if interaction.user.id != self.owner_id:

            try:
                await interaction.response.send_message(
                    (
                        f"{EMOJI['denied']} "
                        "Only the owner who opened "
                        "this panel can use these controls."
                    ),
                    ephemeral=True,
                )

            except discord.HTTPException:
                pass

            return False

        return True

    def _add_navigation(
        self,
    ) -> None:

        back = discord.ui.Button(
            label="Dashboard",
            emoji=EMOJI["left"],
            style=discord.ButtonStyle.secondary,
            row=4,
        )

        back.callback = self._back
        self.add_item(back)

        close = discord.ui.Button(
            label="Close",
            emoji=EMOJI["denied"],
            style=discord.ButtonStyle.danger,
            row=4,
        )

        close.callback = self._close
        self.add_item(close)

    async def _back(
        self,
        interaction: discord.Interaction,
    ) -> None:

        await self.cog.render(
            interaction,
            self.cog.build_dashboard_embed(),
            SystemDashboard(
                self.cog,
                self.owner_id,
                root_interaction=self.root_interaction,
            ),
        )

        self.stop()

    async def _close(
        self,
        interaction: discord.Interaction,
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


class SystemDashboard(PanelView):

    def __init__(
        self,
        cog: "System",
        owner_id: int,
        *,
        root_interaction: Optional[discord.Interaction] = None,
    ) -> None:

        super().__init__(
            cog,
            owner_id,
            back=False,
            root_interaction=root_interaction,
        )

        self._build()

    def _add(
        self,
        label: str,
        emoji: str,
        callback,
        row: int,
        style=discord.ButtonStyle.secondary,
    ) -> None:

        button = discord.ui.Button(
            label=label,
            emoji=emoji,
            style=style,
            row=row,
        )

        button.callback = callback
        self.add_item(button)

    def _build(
        self,
    ) -> None:

        self._add(
            "Diagnostics",
            EMOJI["diagnostics"],
            self._diagnostics,
            0,
            discord.ButtonStyle.primary,
        )

        self._add(
            "Logs",
            EMOJI["logs"],
            self._logs,
            0,
        )

        self._add(
            "Database",
            EMOJI["db"],
            self._database,
            0,
        )

        self._add(
            "Cache",
            EMOJI["cache"],
            self._cache,
            0,
        )

        self._add(
            "Gateway",
            EMOJI["gateway"],
            self._gateway,
            1,
        )

        self._add(
            "System",
            EMOJI["system"],
            self._system,
            1,
        )

        self._add(
            "Health",
            EMOJI["health"],
            self._health,
            1,
            discord.ButtonStyle.success,
        )

        self._add(
            "Commands",
            EMOJI["commands"],
            self._commands,
            1,
        )

        self._add(
            "Maintenance",
            EMOJI["maintenance"],
            self._maintenance,
            2,
            discord.ButtonStyle.danger,
        )

        self._add(
            "Eval",
            EMOJI["eval"],
            self._eval,
            2,
            discord.ButtonStyle.primary,
        )

        self._add(
            "Security",
            EMOJI["security"],
            self._security,
            2,
        )

        self._add(
            "Refresh",
            EMOJI["loading"],
            self._refresh,
            2,
            discord.ButtonStyle.success,
        )

        self._add(
            "Close",
            EMOJI["denied"],
            self._close,
            3,
            discord.ButtonStyle.danger,
        )

    async def _diagnostics(
        self,
        interaction,
    ):
        await self.cog.show_diagnostics(
            interaction
        )

    async def _logs(
        self,
        interaction,
    ):
        await self.cog.show_logs(
            interaction
        )

    async def _database(
        self,
        interaction,
    ):
        await self.cog.show_database(
            interaction
        )

    async def _cache(
        self,
        interaction,
    ):
        await self.cog.show_cache(
            interaction
        )

    async def _gateway(
        self,
        interaction,
    ):
        await self.cog.show_gateway(
            interaction
        )

    async def _system(
        self,
        interaction,
    ):
        await self.cog.show_system(
            interaction
        )

    async def _health(
        self,
        interaction,
    ):
        await self.cog.show_health(
            interaction
        )

    async def _commands(
        self,
        interaction,
    ):
        await self.cog.show_command_stats(
            interaction
        )

    async def _maintenance(
        self,
        interaction,
    ):
        await self.cog.open_maintenance(
            interaction
        )

    async def _eval(
        self,
        interaction,
    ):

        await interaction.response.send_modal(
            EvalModal(
                self.cog,
                self.owner_id,
                root_interaction=(
                    self.root_interaction
                    or interaction
                ),
            )
        )

    async def _security(
        self,
        interaction,
    ):
        await self.cog.show_security(
            interaction
        )

    async def _refresh(
        self,
        interaction,
    ):
        await self.cog.show_dashboard(
            interaction,
            loading=True,
        )

    async def _close(
        self,
        interaction,
    ):

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


class LogView(PanelView):

    def __init__(
        self,
        cog: "System",
        owner_id: int,
        entries: Optional[list[StoredLog]] = None,
        *,
        level_name: str = "all",
        per_page: int = 8,
        page: int = 0,
        root_interaction: Optional[discord.Interaction] = None,
    ) -> None:

        super().__init__(
            cog,
            owner_id,
            root_interaction=root_interaction,
        )

        self.level_name = level_name
        self.per_page = per_page
        self.page = page

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
            // per_page,
        )

        self._controls()

    def _controls(
        self,
    ) -> None:

        previous = discord.ui.Button(
            label="Previous",
            emoji=EMOJI["left"],
            style=discord.ButtonStyle.secondary,
            row=0,
            disabled=self.page <= 0,
        )

        previous.callback = self.previous
        self.add_item(previous)

        next_button = discord.ui.Button(
            label="Next",
            emoji=EMOJI["right"],
            style=discord.ButtonStyle.secondary,
            row=0,
            disabled=self.page >= self.max_page,
        )

        next_button.callback = self.next
        self.add_item(next_button)

        refresh = discord.ui.Button(
            label="Refresh",
            emoji=EMOJI["loading"],
            style=discord.ButtonStyle.primary,
            row=0,
        )

        refresh.callback = self.refresh
        self.add_item(refresh)

    def build_embed(
        self,
    ) -> discord.Embed:

        entries = self.entries[
            self.page * self.per_page:
            (self.page + 1) * self.per_page
        ]

        embed = EmbedFactory.base(
            (
                f"{EMOJI['logs']} "
                "System Logs"
            ),
            (
                f"Filter: `{self.level_name}`\n"
                f"Entries: `{len(self.entries)}`"
            ),
        )

        if not entries:

            embed.description = (
                f"Filter: `{self.level_name}`\n\n"
                "No matching log entries were found."
            )

            return embed

        lines = []

        symbols = {
            "DEBUG": "DBG",
            "INFO": "INF",
            "WARNING": "WRN",
            "ERROR": "ERR",
            "CRITICAL": "CRT",
        }

        for entry in entries:

            ts = int(
                entry.timestamp.timestamp()
            )

            level = symbols.get(
                logging.getLevelName(
                    entry.level
                ),
                "LOG",
            )

            lines.append(
                (
                    f"`{level:<3}` "
                    f"<t:{ts}:T> "
                    f"`{truncate(entry.logger_name, 28)}`\n"
                    f"> {truncate(entry.message, 220)}"
                )
            )

        embed.add_field(
            name=(
                f"Page {self.page + 1} "
                f"/ "
                f"{self.max_page + 1}"
            ),
            value="\n\n".join(lines),
            inline=False,
        )

        return embed

    async def previous(
        self,
        interaction,
    ) -> None:

        page = max(
            0,
            self.page - 1,
        )

        view = LogView(
            self.cog,
            self.owner_id,
            self.entries,
            level_name=self.level_name,
            per_page=self.per_page,
            page=page,
            root_interaction=self.root_interaction,
        )

        await self.cog.render(
            interaction,
            view.build_embed(),
            view,
        )

    async def next(
        self,
        interaction,
    ) -> None:

        page = min(
            self.max_page,
            self.page + 1,
        )

        view = LogView(
            self.cog,
            self.owner_id,
            self.entries,
            level_name=self.level_name,
            per_page=self.per_page,
            page=page,
            root_interaction=self.root_interaction,
        )

        await self.cog.render(
            interaction,
            view.build_embed(),
            view,
        )

    async def refresh(
        self,
        interaction,
    ) -> None:

        entries = MEMORY_HANDLER.recent(
            limit=100,
            level=LOG_LEVELS.get(
                self.level_name
            ),
        )

        max_page = max(
            0,
            (
                len(entries) - 1
            )
            // self.per_page,
        )

        page = min(
            self.page,
            max_page,
        )

        view = LogView(
            self.cog,
            self.owner_id,
            entries,
            level_name=self.level_name,
            per_page=self.per_page,
            page=page,
            root_interaction=self.root_interaction,
        )

        await self.cog.render(
            interaction,
            view.build_embed(),
            view,
            delay=LOGS_LOADING,
        )


EVAL_PAGES = [
    (
        "**Bot**\n"
        "```py\n"
        "bot\n"
        "bot.user\n"
        "bot.user.name\n"
        "bot.user.id\n"
        "bot.latency\n"
        "bot.guilds\n"
        "bot.users\n"
        "bot.application_id\n"
        "bot.intents\n"
        "bot.extensions\n"
        "```"
    ),
    (
        "**Guild**\n"
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
        "**User**\n"
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
        "**Channels**\n"
        "```py\n"
        "interaction.channel\n"
        "interaction.channel.id\n"
        "interaction.channel.name\n"
        "interaction.channel.type\n"
        "interaction.channel.created_at\n"
        "```"
    ),
    (
        "**Members / Roles**\n"
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
        "**Bot Collections**\n"
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
        "**System**\n"
        "```py\n"
        "import os\n"
        "import sys\n"
        "import platform\n"
        "os.getpid()\n"
        "platform.system()\n"
        "platform.platform()\n"
        "platform.machine()\n"
        "sys.version\n"
        "sys.platform\n"
        "```"
    ),
    (
        "**Database**\n"
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
        "**Advanced**\n"
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
        "**Examples**\n"
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


class EvalHelpView(
    PanelView
):

    def __init__(
        self,
        cog: "System",
        owner_id: int,
        page: int = 0,
        *,
        root_interaction=None,
    ) -> None:

        super().__init__(
            cog,
            owner_id,
            root_interaction=root_interaction,
        )

        self.page = (
            page
            % len(EVAL_PAGES)
        )

        previous = discord.ui.Button(
            label="Previous",
            emoji=EMOJI["left"],
            style=discord.ButtonStyle.secondary,
            row=0,
        )

        previous.callback = self.previous
        self.add_item(previous)

        next_button = discord.ui.Button(
            label="Next",
            emoji=EMOJI["right"],
            style=discord.ButtonStyle.secondary,
            row=0,
        )

        next_button.callback = self.next
        self.add_item(next_button)

    def build_embed(
        self,
    ):

        embed = EmbedFactory.base(
            (
                f"{EMOJI['eval']} "
                "Lunar Eval System"
            ),
            EVAL_PAGES[self.page],
            discord.Colour.from_rgb(
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

    async def previous(
        self,
        interaction,
    ):

        view = EvalHelpView(
            self.cog,
            self.owner_id,
            self.page - 1,
            root_interaction=self.root_interaction,
        )

        await self.cog.render(
            interaction,
            view.build_embed(),
            view,
        )

    async def next(
        self,
        interaction,
    ):

        view = EvalHelpView(
            self.cog,
            self.owner_id,
            self.page + 1,
            root_interaction=self.root_interaction,
        )

        await self.cog.render(
            interaction,
            view.build_embed(),
            view,
        )


class MaintenanceModal(
    discord.ui.Modal,
    title="Lunar Maintenance Control",
):

    reason = discord.ui.TextInput(
        label="Maintenance Reason",
        placeholder="Example: Database maintenance...",
        style=discord.TextStyle.paragraph,
        required=False,
        max_length=500,
    )

    def __init__(
        self,
        cog: "System",
        owner_id: int,
        *,
        root_interaction=None,
    ) -> None:

        super().__init__()

        self.cog = cog
        self.owner_id = owner_id
        self.root_interaction = root_interaction

    async def on_submit(
        self,
        interaction: discord.Interaction,
    ) -> None:

        if interaction.user.id != self.owner_id:

            await interaction.response.send_message(
                (
                    f"{EMOJI['denied']} "
                    "You cannot use this modal."
                ),
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
            str(
                self.reason.value
            ).strip()
            or
            "Lunar is currently undergoing maintenance."
        )

        target = (
            self.root_interaction
            or interaction
        )

        try:

            if db.variables is None:

                raise RuntimeError(
                    "The maintenance repository is unavailable."
                )

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
                            "source": "system.py"
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
                    f"> {truncate(reason, 700)}\n\n"
                    f"{EMOJI['security']} "
                    "The state has been persisted to ScyllaDB."
                ),
            )

        except Exception as exc:

            logger.exception(
                "Failed to enable maintenance"
            )

            embed = EmbedFactory.error(
                "Maintenance Failed",
                (
                    "```text\n"
                    f"{truncate(exc, 1200)}"
                    "\n```"
                ),
            )

        await target.edit_original_response(
            content=None,
            embed=embed,
            view=SystemMaintenanceView(
                self.cog,
                self.owner_id,
                root_interaction=self.root_interaction,
            ),
        )


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
        *,
        root_interaction=None,
    ) -> None:

        super().__init__()

        self.cog = cog
        self.owner_id = owner_id
        self.root_interaction = root_interaction

    async def on_submit(
        self,
        interaction: discord.Interaction,
    ) -> None:

        if interaction.user.id != self.owner_id:

            await interaction.response.send_message(
                (
                    f"{EMOJI['denied']} "
                    "You cannot use this developer console."
                ),
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

        code = (
            str(
                self.code.value
            ).strip()
        )

        if code.startswith(
            "```"
        ):

            lines = (
                code.splitlines()[1:]
            )

            if (
                lines
                and
                lines[-1].strip()
                == "```"
            ):

                lines.pop()

            code = "\n".join(
                lines
            )

        env = {
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
                    "__builtins__": {}
                },
                env,
            )

            text = truncate(
                (
                    "None"
                    if result is None
                    else repr(result)
                ),
                3900,
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
                    f"{text}"
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

        except Exception as exc:

            embed = EmbedFactory.error(
                "Eval Error",
                (
                    "```py\n"
                    f"{truncate(
                        type(exc).__name__
                        + ": "
                        + str(exc),
                        3900,
                    )}"
                    "\n```"
                ),
            )

            embed.set_footer(
                text=(
                    f"Executed by "
                    f"{interaction.user}"
                )
            )

        target = (
            self.root_interaction
            or interaction
        )

        await target.edit_original_response(
            content=None,
            embed=embed,
            view=PanelView(
                self.cog,
                self.owner_id,
                root_interaction=(
                    self.root_interaction
                ),
            ),
        )


class SystemMaintenanceView(
    PanelView
):

    def __init__(
        self,
        cog: "System",
        owner_id: int,
        *,
        root_interaction=None,
    ) -> None:

        super().__init__(
            cog,
            owner_id,
            root_interaction=root_interaction,
        )

        enable = discord.ui.Button(
            label="Enable Maintenance",
            emoji=EMOJI["maintenance"],
            style=discord.ButtonStyle.danger,
            row=0,
        )

        enable.callback = self.enable
        self.add_item(enable)

        reason = discord.ui.Button(
            label="Enable With Reason",
            emoji=EMOJI["question"],
            style=discord.ButtonStyle.secondary,
            row=0,
        )

        reason.callback = self.enable_with_reason
        self.add_item(reason)

    async def enable(
        self,
        interaction,
    ):

        await self.cog.enable_maintenance(
            interaction,
            "Lunar is currently undergoing maintenance.",
        )

    async def enable_with_reason(
        self,
        interaction,
    ):

        await interaction.response.send_modal(
            MaintenanceModal(
                self.cog,
                self.owner_id,
                root_interaction=(
                    self.root_interaction
                    or interaction
                ),
            )
        )


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
            bot,
            "maintenance_mode",
        ):
            bot.maintenance_mode = False

        if not hasattr(
            bot,
            "maintenance_reason",
        ):
            bot.maintenance_reason = ""

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
                    (
                        "Maintenance state loaded "
                        "| enabled=%s"
                    ),
                    self.bot.maintenance_mode,
                )

        except Exception:

            logger.exception(
                "Failed to load maintenance state"
            )

    def guild_count(
        self,
    ):
        return len(
            getattr(
                self.bot,
                "guilds",
                [],
            )
        )

    def user_count(
        self,
    ):
        return len(
            getattr(
                self.bot,
                "users",
                [],
            )
        )

    def channel_count(
        self,
    ):
        return sum(
            len(
                getattr(
                    guild,
                    "channels",
                    [],
                )
            )
            for guild in self.bot.guilds
        )

    def role_count(
        self,
    ):
        return sum(
            len(
                getattr(
                    guild,
                    "roles",
                    [],
                )
            )
            for guild in self.bot.guilds
        )

    def emoji_count(
        self,
    ):
        return sum(
            len(
                getattr(
                    guild,
                    "emojis",
                    [],
                )
            )
            for guild in self.bot.guilds
        )

    def thread_count(
        self,
    ):
        return sum(
            len(
                getattr(
                    guild,
                    "threads",
                    [],
                )
            )
            for guild in self.bot.guilds
        )

    async def render(
        self,
        interaction,
        embed,
        view,
        *,
        delay=0,
    ) -> None:

        try:

            if (
                isinstance(
                    view,
                    PanelView,
                )
                and
                view.root_interaction is None
            ):

                view.root_interaction = (
                    interaction
                )

            if not interaction.response.is_done():

                if interaction.message is None:

                    await interaction.response.defer(
                        ephemeral=True,
                        thinking=True,
                    )

                else:

                    await interaction.response.defer()

            if delay:
                await asyncio.sleep(
                    delay
                )

            await interaction.edit_original_response(
                content=None,
                embed=embed,
                view=view,
            )

        except discord.NotFound:

            logger.warning(
                (
                    "System panel interaction expired "
                    "or message disappeared"
                )
            )

        except discord.HTTPException:

            logger.exception(
                "Failed to render System panel"
            )

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
            (
                f"{EMOJI['lunar']} "
                "Lunar System Control"
            ),
            (
                f"{EMOJI['dev']} "
                "**Owner Control Dashboard**\n\n"
                "Monitor and control the Lunar runtime "
                "from one centralized interface."
            ),
            (
                discord.Colour.orange()
                if maintenance
                else discord.Colour.blurple()
            ),
        )

        embed.add_field(
            name=(
                f"{EMOJI['gateway']} "
                "Discord"
            ),
            value=(
                f"{status_badge("
                    "self.bot.is_ready()"
                ")}\n"
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

            embed.add_field(
                name=(
                    f"{EMOJI['question']} "
                    "Maintenance Reason"
                ),
                value=(
                    "> "
                    f"{truncate("
                        "getattr("
                        "self.bot, "
                        "'maintenance_reason', "
                        "''"
                        ")"
                        " or "
                        "'No reason configured.'"
                        ", "
                        "700"
                    )}"
                ),
                inline=False,
            )

        if self.bot.user:

            embed.set_thumbnail(
                url=(
                    self.bot.user
                    .display_avatar
                    .url
                )
            )

        return embed

    @app_commands.command(
        name="system",
        description=(
            "Open the Lunar owner "
            "system control dashboard."
        ),
    )
    @owner_only()
    async def system_command(
        self,
        interaction: discord.Interaction,
    ) -> None:

        await self.render(
            interaction,
            self.build_dashboard_embed(),
            SystemDashboard(
                self,
                interaction.user.id,
            ),
            delay=DASHBOARD_LOADING,
        )

    async def show_dashboard(
        self,
        interaction,
        *,
        loading=False,
    ):

        await self.render(
            interaction,
            self.build_dashboard_embed(),
            SystemDashboard(
                self,
                interaction.user.id,
                root_interaction=(
                    getattr(
                        interaction,
                        "message",
                        None,
                    )
                    and getattr(
                        interaction,
                        "message",
                        None,
                    )
                    or None
                ),
            ),
            delay=(
                DASHBOARD_LOADING
                if loading
                else 0
            ),
        )

    async def show_diagnostics(
        self,
        interaction,
    ):

        status = {
            "healthy": False,
            "initialized": False,
        }

        try:
            status = await db.status()

        except Exception:

            logger.exception(
                "Diagnostic database status failed"
            )

        uptime = (
            utcnow()
            - self.started_at
        ).total_seconds()

        embed = EmbedFactory.base(
            (
                f"{EMOJI['diagnostics']} "
                "Lunar Diagnostics"
            ),
            "Complete runtime diagnostic snapshot.",
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
                f"`{platform.system()} "
                f"{platform.release()}`\n"
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
                f"**Latency:** "
                f"`{round(self.bot.latency * 1000)}ms`\n"
                f"**Guilds:** "
                f"`{self.guild_count():,}`\n"
                f"**Users:** "
                f"`{self.user_count():,}`\n"
                f"**Channels:** "
                f"`{self.channel_count():,}`\n"
                f"**Roles:** "
                f"`{self.role_count():,}`\n"
                f"**Emojis:** "
                f"`{self.emoji_count():,}`\n"
                f"**Threads:** "
                f"`{self.thread_count():,}`"
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
            value=yes_no(
                bool(
                    getattr(
                        self.bot,
                        "maintenance_mode",
                        False,
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
                f"{status_badge("
                    "status.get('healthy')"
                ")}\n"
                f"**Initialized:** "
                f"{yes_no("
                    "bool("
                    "status.get('initialized')"
                    ")"
                ")}\n"
                f"**Keyspace:** "
                f"`{status.get('keyspace', 'unknown')}`\n"
                f"**Prepared:** "
                f"`{status.get('prepared_statements', 0):,}`"
            ),
            inline=False,
        )

        await self.render(
            interaction,
            embed,
            PanelView(
                self,
                interaction.user.id,
            ),
            delay=DIAGNOSTICS_LOADING,
        )

    async def show_logs(
        self,
        interaction,
    ):

        view = LogView(
            self,
            interaction.user.id,
        )

        await self.render(
            interaction,
            view.build_embed(),
            view,
            delay=LOGS_LOADING,
        )

    async def show_cache(
        self,
        interaction,
    ):

        embed = EmbedFactory.base(
            (
                f"{EMOJI['cache']} "
                "Runtime Cache"
            ),
            "Current in-memory Discord state.",
        )

        embed.add_field(
            name="Guild Cache",
            value=(
                f"**Guilds:** "
                f"`{self.guild_count():,}`\n"
                f"**Users:** "
                f"`{self.user_count():,}`\n"
                f"**Channels:** "
                f"`{self.channel_count():,}`\n"
                f"**Roles:** "
                f"`{self.role_count():,}`\n"
                f"**Emojis:** "
                f"`{self.emoji_count():,}`"
            ),
            inline=False,
        )

        embed.add_field(
            name="Extended Cache",
            value=(
                f"**Threads:** "
                f"`{self.thread_count():,}`\n"
                f"**Voice Clients:** "
                f"`{len("
                    "getattr("
                    "self.bot, "
                    "'voice_clients', "
                    "[]"
                    ")"
                ):,}`\n"
                f"**Slash Commands:** "
                f"`{len(self.bot.tree.get_commands()):,}`"
            ),
            inline=False,
        )

        embed.add_field(
            name="Diagnostic Cache",
            value=(
                f"**Stored Logs:** "
                f"`{len(MEMORY_HANDLER.entries):,}` "
                f"/ `{MAX_LOG_ENTRIES}`\n"
                f"**Runtime Start:** "
                f"{fmt_dt(self.started_at)}"
            ),
            inline=False,
        )

        await self.render(
            interaction,
            embed,
            PanelView(
                self,
                interaction.user.id,
            ),
            delay=DATABASE_LOADING,
        )

    async def show_database(
        self,
        interaction,
    ):

        try:
            status = await db.status()

        except Exception as exc:

            logger.exception(
                "Database diagnostics failed"
            )

            await self.render(
                interaction,
                EmbedFactory.error(
                    "Database Diagnostics Failed",
                    (
                        "```text\n"
                        f"{truncate(exc, 1500)}"
                        "\n```"
                    ),
                ),
                PanelView(
                    self,
                    interaction.user.id,
                ),
                delay=DATABASE_LOADING,
            )

            return

        healthy = bool(
            status.get(
                "healthy",
                False,
            )
        )

        embed = EmbedFactory.base(
            (
                f"{EMOJI['db']} "
                "ScyllaDB Diagnostics"
            ),
            f"Health: {status_badge(healthy)}",
            (
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

        repos = status.get(
            "repositories",
            [],
        )

        repo_text = (
            "\n".join(
                f"{EMOJI['approved']} "
                f"`{repo}`"
                for repo in repos
            )
            if repos
            else
            "No repositories bound."
        )

        embed.add_field(
            name=(
                f"Repositories "
                f"`{len(repos)}`"
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
                f"{status_badge("
                    "status.get('session_connected')"
                ")}\n"
                f"**Cluster:** "
                f"{status_badge("
                    "status.get('cluster_connected')"
                ")}"
            ),
            inline=False,
        )

        await self.render(
            interaction,
            embed,
            PanelView(
                self,
                interaction.user.id,
            ),
            delay=DATABASE_LOADING,
        )

    async def show_gateway(
        self,
        interaction,
    ):

        embed = EmbedFactory.base(
            (
                f"{EMOJI['gateway']} "
                "Gateway / Shard Console"
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
                    "**Mode:** `Single Shard`\n"
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
                shards.items()
            ):

                latency = getattr(
                    shard,
                    "latency",
                    0,
                )

                count = sum(
                    1
                    for guild in self.bot.guilds
                    if guild.shard_id == shard_id
                )

                embed.add_field(
                    name=f"Shard {shard_id}",
                    value=(
                        f"**Latency:** "
                        f"`{round(latency * 1000)}ms`\n"
                        f"**Guilds:** "
                        f"`{count:,}`"
                    ),
                    inline=True,
                )

        embed.add_field(
            name="Gateway Summary",
            value=(
                f"**Bot User:** "
                f"`{self.bot.user.id if self.bot.user else 'unknown'}`\n"
                f"**Session:** "
                f"{status_badge("
                    "self.bot.is_ready()"
                ")}"
            ),
            inline=False,
        )

        await self.render(
            interaction,
            embed,
            PanelView(
                self,
                interaction.user.id,
            ),
            delay=GATEWAY_LOADING,
        )

    async def show_system(
        self,
        interaction,
    ):

        uptime = (
            utcnow()
            - self.started_at
        ).total_seconds()

        embed = EmbedFactory.base(
            (
                f"{EMOJI['system']} "
                "Host Diagnostics"
            )
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
                f"`{truncate("
                    "platform.processor() "
                    "or "
                    "'Unknown'"
                    ", 120"
                )}`"
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

        await self.render(
            interaction,
            embed,
            PanelView(
                self,
                interaction.user.id,
            ),
            delay=SYSTEM_LOADING,
        )

    async def show_health(
        self,
        interaction,
    ):

        started = time.perf_counter()
        db_ok = False

        try:
            db_ok = await db.ping()

        except Exception:

            logger.exception(
                "Health database ping failed"
            )

        elapsed = (
            time.perf_counter()
            - started
        ) * 1000

        discord_ok = self.bot.is_ready()
        overall = (
            discord_ok
            and db_ok
        )

        embed = EmbedFactory.base(
            (
                f"{EMOJI['health']} "
                "Lunar Health Check"
            ),
            (
                f"Overall: "
                f"{status_badge(overall)}"
            ),
            (
                discord.Colour.green()
                if overall
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
            value=status_badge(
                db_ok
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

        await self.render(
            interaction,
            embed,
            PanelView(
                self,
                interaction.user.id,
            ),
            delay=HEALTH_LOADING,
        )

    async def show_command_stats(
        self,
        interaction,
    ):

        if db.command_stats is None:

            embed = EmbedFactory.error(
                "Command Statistics Unavailable",
                (
                    "The command statistics repository "
                    "is not currently bound."
                ),
            )

            await self.render(
                interaction,
                embed,
                PanelView(
                    self,
                    interaction.user.id,
                ),
                delay=COMMAND_STATS_LOADING,
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

            await self.render(
                interaction,
                EmbedFactory.error(
                    "Statistics Lookup Failed",
                    (
                        "```text\n"
                        f"{truncate(exc, 1200)}"
                        "\n```"
                    ),
                ),
                PanelView(
                    self,
                    interaction.user.id,
                ),
                delay=COMMAND_STATS_LOADING,
            )

            return

        embed = EmbedFactory.base(
            (
                f"{EMOJI['commands']} "
                "Command Analytics"
            ),
            (
                f"**Total recorded invocations:** "
                f"`{total:,}`"
            ),
        )

        if rows:

            lines = [
                (
                    f"`{n:>2}.` "
                    f"`/{getattr(row, 'command_name', 'unknown')}` "
                    f"— **{int("
                        "getattr("
                        "row, "
                        "'uses', "
                        "0"
                        ")"
                        " or "
                        "0"
                    ):,}**"
                )
                for n, row
                in enumerate(
                    rows[:15],
                    1,
                )
            ]

            embed.add_field(
                name="Top Commands",
                value="\n".join(lines),
                inline=False,
            )

        else:

            embed.add_field(
                name="Usage",
                value=(
                    "No command usage has "
                    "been recorded yet."
                ),
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
            value="`ScyllaDB`",
            inline=True,
        )

        await self.render(
            interaction,
            embed,
            PanelView(
                self,
                interaction.user.id,
            ),
            delay=COMMAND_STATS_LOADING,
        )

    async def show_security(
        self,
        interaction,
    ):

        embed = EmbedFactory.base(
            (
                f"{EMOJI['security']} "
                "Lunar Security Console"
            ),
            (
                "Current owner and runtime "
                "security information."
            ),
        )

        embed.add_field(
            name="Authorized Owners",
            value="\n".join(
                (
                    f"{EMOJI['approved']} "
                    f"<@{owner}> "
                    f"`{owner}`"
                )
                for owner in OWNERS
            ),
            inline=False,
        )

        embed.add_field(
            name="Dashboard",
            value=(
                f"{EMOJI['approved']} "
                "Owner restricted\n"
                f"{EMOJI['approved']} "
                "Ephemeral interface\n"
                f"{EMOJI['approved']} "
                "Per-view owner validation"
            ),
            inline=False,
        )

        embed.add_field(
            name="Developer Console",
            value=(
                f"{EMOJI['approved']} "
                "Owner restricted\n"
                f"{EMOJI['approved']} "
                "Built-in namespace only\n"
                f"{EMOJI['approved']} "
                "Builtins disabled"
            ),
            inline=False,
        )

        await self.render(
            interaction,
            embed,
            PanelView(
                self,
                interaction.user.id,
            ),
            delay=SECURITY_LOADING,
        )

    async def open_maintenance(
        self,
        interaction,
    ):

        enabled = bool(
            getattr(
                self.bot,
                "maintenance_mode",
                False,
            )
        )

        if enabled:

            try:

                if db.variables is None:
                    raise RuntimeError(
                        "The maintenance repository "
                        "is unavailable."
                    )

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
                            (
                                interaction.guild.id
                                if interaction.guild
                                else 0
                            ),
                            actor_id=interaction.user.id,
                            action="maintenance_disable",
                            target_id=None,
                            reason=(
                                "Maintenance mode disabled."
                            ),
                            metadata={
                                "source": "system.py"
                            },
                        )

                except Exception:

                    logger.exception(
                        "Failed to audit maintenance disable"
                    )

                embed = EmbedFactory.success(
                    "Maintenance Disabled",
                    (
                        "Normal command processing "
                        "may resume."
                    ),
                )

            except Exception as exc:

                logger.exception(
                    "Failed to disable maintenance"
                )

                embed = EmbedFactory.error(
                    "Maintenance Failed",
                    (
                        "```text\n"
                        f"{truncate(exc, 1200)}"
                        "\n```"
                    ),
                )

            await self.render(
                interaction,
                embed,
                SystemMaintenanceView(
                    self,
                    interaction.user.id,
                ),
                delay=MAINTENANCE_LOADING,
            )

            return

        reason = (
            getattr(
                self.bot,
                "maintenance_reason",
                "",
            )
            or
            "No reason configured."
        )

        embed = EmbedFactory.warning(
            "Maintenance Control",
            (
                f"**Current State:** "
                f"{EMOJI['approved']} `NORMAL`\n\n"
                f"**Current Reason:**\n"
                f"> {truncate(reason, 700)}\n\n"
                "Enabling maintenance will persist "
                "the state to ScyllaDB."
            ),
        )

        await self.render(
            interaction,
            embed,
            SystemMaintenanceView(
                self,
                interaction.user.id,
            ),
        )

    async def enable_maintenance(
        self,
        interaction,
        reason: str,
    ):

        try:

            if db.variables is None:
                raise RuntimeError(
                    "The maintenance repository "
                    "is unavailable."
                )

            await db.variables.set_maintenance(
                True,
                reason=reason,
                changed_by=interaction.user.id,
            )

            self.bot.maintenance_mode = True
            self.bot.maintenance_reason = reason

            try:

                if db.audit is not None:

                    await db.audit.record(
                        (
                            interaction.guild.id
                            if interaction.guild
                            else 0
                        ),
                        actor_id=interaction.user.id,
                        action="maintenance_enable",
                        target_id=None,
                        reason=reason,
                        metadata={
                            "source": "system.py"
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
                    f"> {truncate(reason, 700)}\n\n"
                    f"{EMOJI['security']} "
                    "The state has been persisted to ScyllaDB."
                ),
            )

        except Exception as exc:

            logger.exception(
                "Failed to enable maintenance"
            )

            embed = EmbedFactory.error(
                "Maintenance Failed",
                (
                    "```text\n"
                    f"{truncate(exc, 1200)}"
                    "\n```"
                ),
            )

        await self.render(
            interaction,
            embed,
            SystemMaintenanceView(
                self,
                interaction.user.id,
            ),
            delay=MAINTENANCE_LOADING,
        )

    async def show_eval_help(
        self,
        interaction,
    ):

        view = EvalHelpView(
            self,
            interaction.user.id,
        )

        await self.render(
            interaction,
            view.build_embed(),
            view,
        )

    @commands.command(
        name="eval",
        aliases=("ev",),
    )
    async def eval_command(
        self,
        ctx: commands.Context,
        *,
        code: Optional[str] = None,
    ):

        if ctx.author.id not in OWNERS:

            await ctx.reply(
                (
                    f"{EMOJI['denied']} "
                    "You do not have permission "
                    "to use this command."
                )
            )

            return

        if not code:

            view = EvalHelpView(
                self,
                ctx.author.id,
            )

            await ctx.reply(
                embed=view.build_embed(),
                view=view,
            )

            return

        code = code.strip()

        if code.startswith(
            "```"
        ):

            lines = (
                code.splitlines()[1:]
            )

            if (
                lines
                and
                lines[-1].strip()
                == "```"
            ):
                lines.pop()

            code = "\n".join(
                lines
            )

        env = {
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

        try:

            result = eval(
                code,
                {
                    "__builtins__": {}
                },
                env,
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
                    f"{truncate("
                        "'None'"
                        " if "
                        "result is None"
                        " else "
                        "repr(result)"
                        ", "
                        "3900"
                    )}"
                    "\n```"
                ),
                inline=False,
            )

        except Exception as exc:

            embed = EmbedFactory.error(
                "Eval Error",
                (
                    "```py\n"
                    f"{truncate("
                        "type(exc).__name__"
                        " + "
                        "': '"
                        " + "
                        "str(exc)"
                        ", "
                        "3900"
                    )}"
                    "\n```"
                ),
            )

        await ctx.reply(
            embed=embed
        )


async def setup(
    bot: commands.Bot,
) -> None:

    await bot.add_cog(
        System(bot)
    )
