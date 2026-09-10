from __future__ import annotations

import time

from types import MappingProxyType

import discord

from discord import app_commands
from discord.ext import commands


# ============================================================
# BOT INFORMATION
# ============================================================

BOT = MappingProxyType({
    "name": "Lunaranime Bot",
    "version": "1.0.0",

    "developers": (
        {
            "name": "Vireon",
            "discord": "https://discord.com/users/960946185768685618",
            "telegram": "tg://user?id=6497734480",
        },
        {
            "name": "Thanon",
            "discord": "https://discord.com/users/1419744000977403994",
            "telegram": "tg://user?id=8533417360",
        },
    ),
})


# ============================================================
# PROCESS START
# ============================================================

_PROCESS_STARTED = time.monotonic()


# ============================================================
# DEVELOPERS
# ============================================================

def get_developers(
    platform: str = "discord",
) -> str:

    if platform not in {
        "discord",
        "telegram",
    }:
        raise ValueError(
            "platform must be 'discord' or 'telegram'"
        )

    result = []

    for developer in BOT["developers"]:

        link = developer[
            platform
        ]

        result.append(
            f"[{developer['name']}]({link})"
        )

    return "\n".join(
        result
    )


# ============================================================
# UPTIME
# ============================================================

def get_uptime() -> str:

    total = int(
        time.monotonic()
        - _PROCESS_STARTED
    )

    days, remainder = divmod(
        total,
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

    parts.append(
        f"{seconds}s"
    )

    return " ".join(
        parts
    )


# ============================================================
# COG
# ============================================================

class Info(commands.Cog):

    def __init__(
        self,
        bot: commands.Bot,
    ):
        self.bot = bot

# ============================================================
# SETUP
# ============================================================

async def setup(bot: commands.Bot):
    await bot.add_cog(Info(bot))
