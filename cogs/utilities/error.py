from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import traceback
from collections import defaultdict
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Any, Optional
import discord
from discord import app_commands
from discord.ext import commands
from cogs.utilities.emoji import EMOJI

# ============================================================
# Configuration
# ============================================================

ERROR_LOG_CHANNEL_ID = 1499281835757404250

ERROR_LOG_FILE = Path(
    os.getenv(
        "ERROR_LOG_FILE",
        "logs/errors.log",
    )
)

# Prevent one identical error from flooding the channel.
ERROR_COOLDOWN_SECONDS = int(
    os.getenv(
        "ERROR_LOG_COOLDOWN",
        "15",
    )
)

MAX_DESCRIPTION = 3900
MAX_FIELD_VALUE = 1000


# ============================================================
# Logger
# ============================================================

ERROR_LOG_FILE.parent.mkdir(
    parents=True,
    exist_ok=True,
)

logger = logging.getLogger("lunar.errors")

if not logger.handlers:
    file_handler = logging.FileHandler(
        ERROR_LOG_FILE,
        encoding="utf-8",
    )

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    )

    file_handler.setFormatter(formatter)

    logger.addHandler(file_handler)
    logger.setLevel(logging.ERROR)


# ============================================================
# State
# ============================================================

_send_lock = asyncio.Lock()

_recent_errors: dict[str, float] = {}

_bot: Optional[commands.Bot] = None


# ============================================================
# Helpers
# ============================================================

def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def truncate(
    value: Any,
    length: int = MAX_FIELD_VALUE,
) -> str:
    text = str(value)

    if len(text) <= length:
        return text

    return (
        text[: length - 3]
        + "..."
    )


def exception_name(error: BaseException) -> str:
    return type(error).__name__


def exception_message(error: BaseException) -> str:
    message = str(error).strip()

    if not message:
        return "(no exception message)"

    return message


def build_traceback(
    error: BaseException,
) -> str:
    return "".join(
        traceback.format_exception(
            type(error),
            error,
            error.__traceback__,
        )
    )


def error_fingerprint(
    error: BaseException,
    context: str,
) -> str:
    raw = (
        f"{context}|"
        f"{type(error).__module__}|"
        f"{type(error).__qualname__}|"
        f"{str(error)}"
    )

    return hashlib.sha256(
        raw.encode("utf-8", errors="replace")
    ).hexdigest()


def compact_error(
    error: BaseException,
) -> str:
    return (
        f"{type(error).__name__}: "
        f"{exception_message(error)}"
    )


def resolve_channel(
    bot: commands.Bot,
) -> Optional[discord.abc.Messageable]:
    if not ERROR_LOG_CHANNEL_ID:
        return None

    channel = bot.get_channel(
        ERROR_LOG_CHANNEL_ID
    )

    if channel is not None:
        return channel

    return None


# ============================================================
# Main Error Logger
# ============================================================

async def log_error(
    error: BaseException,
    *,
    context: str = "Unknown",
    bot: Optional[commands.Bot] = None,
    guild: Optional[discord.Guild] = None,
    user: Optional[discord.abc.User] = None,
    channel: Optional[discord.abc.Messageable] = None,
    command: Optional[str] = None,
    interaction: Optional[discord.Interaction] = None,
    extra: Optional[dict[str, Any]] = None,
) -> None:
    """
    Central Lunar error reporter.

    Writes:
        1. Full traceback to logs/errors.log
        2. Styled Discord error embed
        3. Full traceback as a .txt attachment
    """

    target_bot = bot or _bot

    now = utc_now()

    traceback_text = build_traceback(error)

    # --------------------------------------------------------
    # Local logging
    # --------------------------------------------------------

    logger.error(
        "[%s] %s",
        context,
        traceback_text,
    )

    # --------------------------------------------------------
    # Deduplication
    # --------------------------------------------------------

    fingerprint = error_fingerprint(
        error,
        context,
    )

    timestamp = now.timestamp()

    previous = _recent_errors.get(
        fingerprint
    )

    if (
        previous is not None
        and timestamp - previous
        < ERROR_COOLDOWN_SECONDS
    ):
        return

    _recent_errors[fingerprint] = timestamp

    # Periodically clean stale fingerprints.
    stale_before = (
        timestamp
        - ERROR_COOLDOWN_SECONDS * 4
    )

    stale_keys = [
        key
        for key, value in _recent_errors.items()
        if value < stale_before
    ]

    for key in stale_keys:
        _recent_errors.pop(
            key,
            None,
        )

    # --------------------------------------------------------
    # Resolve metadata
    # --------------------------------------------------------

    if interaction is not None:
        if guild is None:
            guild = interaction.guild

        if user is None:
            user = interaction.user

        if channel is None:
            channel = interaction.channel

        if command is None:
            command_obj = interaction.command

            if command_obj is not None:
                command = getattr(
                    command_obj,
                    "qualified_name",
                    None,
                )

    if channel is None and interaction is not None:
        channel = interaction.channel

    # --------------------------------------------------------
    # Destination
    # --------------------------------------------------------

    if target_bot is None:
        return

    destination = resolve_channel(
        target_bot
    )

    if destination is None:
        logger.error(
            "ERROR_LOG_CHANNEL_ID is invalid or "
            "the bot cannot access the configured channel."
        )
        return

    # --------------------------------------------------------
    # Identity information
    # --------------------------------------------------------

    guild_name = (
        guild.name
        if guild is not None
        else "Direct Message / Unknown"
    )

    guild_id = (
        str(guild.id)
        if guild is not None
        else "N/A"
    )

    user_name = (
        str(user)
        if user is not None
        else "Unknown"
    )

    user_id = (
        str(user.id)
        if user is not None
        else "N/A"
    )

    channel_name = "Unknown"
    channel_id = "N/A"

    if channel is not None:
        channel_id = str(
            getattr(channel, "id", "N/A")
        )

        channel_name = getattr(
            channel,
            "name",
            str(channel),
        )

    # --------------------------------------------------------
    # Main embed
    # --------------------------------------------------------

    embed = discord.Embed(
        title="{EMOJI['Lunar']} Lunar System Error",
        description=(
            "An exception was raised somewhere inside "
            "the Lunar system.\n\n"
            f"```py\n"
            f"{truncate(compact_error(error), 1200)}"
            f"\n```"
        ),
        color=discord.Color.red(),
        timestamp=now,
    )

embed.add_field(
    name=f"{EMOJI['system']} Context",
    value=f"`{truncate(context, 900)}`",
    inline=True,
)
embed.add_field(
    name=f"{EMOJI['commands']} Command",
    value=f"`{truncate(command or 'N/A', 900)}`",
    inline=True,
)
embed.add_field(
    name=f"{EMOJI['health']} Error Type",
    value=f"`{exception_name(error)}`",
    inline=True,
)
embed.add_field(
    name="Server",
    value=f"**{truncate(guild_name, 700)}**\n`{guild_id}`",
    inline=True,
)
embed.add_field(
    name="Channel",
    value=f"**{truncate(channel_name, 700)}**\n`{channel_id}`",
    inline=True,
)
embed.add_field(
    name="User",
    value=f"**{truncate(user_name, 700)}**\n`{user_id}`",
    inline=True,
)
    # --------------------------------------------------------
    # Extra context
    # --------------------------------------------------------

    if extra:
        extra_lines = []

        for key, value in extra.items():
            extra_lines.append(
                f"**{key}:** "
                f"`{truncate(value, 700)}`"
            )

        extra_text = "\n".join(extra_lines)

        if extra_text:
            embed.add_field(
                name="Additional Context",
                value=truncate(
                    extra_text,
                    1000,
                ),
                inline=False,
            )

    # --------------------------------------------------------
    # Footer
    # --------------------------------------------------------

embed.set_footer(
    text=f"Lunar Error Logger • {fingerprint[:12]}"
)

    # --------------------------------------------------------
    # Full traceback attachment
    # --------------------------------------------------------

traceback_file = discord.File(
    BytesIO(traceback_text.encode("utf-8", errors="replace")),
    filename=f"lunar_error_{utc_now():%Y%m%d_%H%M%S}.txt",
)

    # --------------------------------------------------------
    # Send safely
    # --------------------------------------------------------

    async with _send_lock:
        try:
            await destination.send(
                embed=embed,
                file=traceback_file,
            )

        except Exception:
            logger.exception(
                "Failed to send error report to Discord."
            )


# ============================================================
# Global Command Error Handler
# ============================================================

async def handle_command_error(
    ctx: commands.Context,
    error: commands.CommandError,
) -> None:
    original = getattr(
        error,
        "original",
        error,
    )

    await log_error(
        original,
        context="Prefix Command",
        bot=ctx.bot,
        guild=ctx.guild,
        user=ctx.author,
        channel=ctx.channel,
        command=(
            ctx.command.qualified_name
            if ctx.command
            else None
        ),
        extra={
            "Message ID": ctx.message.id,
            "Prefix": ctx.prefix,
        },
    )


# ============================================================
# Global Application Command Error Handler
# ============================================================

async def handle_app_command_error(
    interaction: discord.Interaction,
    error: app_commands.AppCommandError,
) -> None:
    original = getattr(
        error,
        "original",
        error,
    )

    await log_error(
        original,
        context="Slash Command",
        bot=interaction.client,
        interaction=interaction,
        command=(
            interaction.command.qualified_name
            if interaction.command
            else None
        ),
        extra={
            "Interaction ID": interaction.id,
        },
    )


# ============================================================
# Event Error Handler
# ============================================================

async def handle_event_error(
    event_name: str,
    error: BaseException,
    bot: commands.Bot,
    **extra: Any,
) -> None:
    await log_error(
        error,
        context=f"Event: {event_name}",
        bot=bot,
        extra=extra or None,
    )


# ============================================================
# Asyncio Exception Handler
# ============================================================

def install_asyncio_exception_handler(
    bot: commands.Bot,
) -> None:
    loop = asyncio.get_running_loop()

    def exception_handler(
        current_loop: asyncio.AbstractEventLoop,
        context: dict[str, Any],
    ) -> None:
        error = context.get("exception")

        if error is None:
            error = RuntimeError(
                context.get(
                    "message",
                    "Unknown asyncio exception.",
                )
            )

        task = context.get(
            "future"
        ) or context.get(
            "task"
        )

        task_name = None

        if task is not None:
            try:
                task_name = task.get_name()
            except Exception:
                task_name = None

        asyncio.create_task(
            log_error(
                error,
                context="Asyncio / Background Task",
                bot=bot,
                extra={
                    "Task": task_name or "Unknown",
                    "Asyncio Message": context.get(
                        "message",
                        "N/A",
                    ),
                },
            )
        )

    loop.set_exception_handler(
        exception_handler
    )


# ============================================================
# Installer
# ============================================================

def install_error_logging(
    bot: commands.Bot,
) -> None:
    """
    Installs Lunar's global error handling.

    Call this once after creating the bot.
    """

    global _bot

    _bot = bot

    # Prefix commands.
    bot.on_command_error = handle_command_error

    # Slash / application commands.
    bot.tree.on_error = handle_app_command_error

    # asyncio background failures.
    install_asyncio_exception_handler(
        bot
    )

    logger.info(
        "Lunar global error logging installed."
    )


# ============================================================
# Optional Cog
# ============================================================

class ErrorLogging(commands.Cog):
    """
    Keeps the utility discoverable as a normal Lunar cog.
    The actual handlers are installed globally.
    """

    def __init__(
        self,
        bot: commands.Bot,
    ):
        self.bot = bot

        install_error_logging(
            bot
        )

    @commands.Cog.listener()
    async def on_error(
        self,
        event_method: str,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        """
        Catch errors raised by Discord event listeners.

        Discord.py does not route every listener exception
        through on_command_error, so this gives us another
        layer of protection.
        """

        error = RuntimeError(
            f"Unhandled event error in {event_method}"
        )

        await log_error(
            error,
            context=f"Discord Event: {event_method}",
            bot=self.bot,
            extra={
                "Arguments": repr(args),
                "Keyword Arguments": repr(kwargs),
            },
        )


async def setup(
    bot: commands.Bot,
) -> None:
    await bot.add_cog(
        Error(bot)
    )
