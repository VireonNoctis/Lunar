from __future__ import annotations

import asyncio
import aiohttp

import discord

from discord import app_commands
from discord.ext import commands

from utilities.database import db
from cogs.utilities.emoji import EMOJI
from cogs.utilities.info import (
    BOT,
    get_developers,
    get_uptime,
)


# ============================================================
# CONFIG
# ============================================================

LUNAR_WEBSITE = "https://lunarx.to"
LUNAR_API = "https://api.lunarx.to"

HTTP_TIMEOUT = aiohttp.ClientTimeout(
    total=10,
    connect=5,
    sock_connect=5,
    sock_read=5,
)


# ============================================================
# STATUS
# ============================================================

async def fetch_status(
    session: aiohttp.ClientSession,
    url: str,
) -> tuple[int | None, float | None]:

    started = asyncio.get_running_loop().time()

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
                round(elapsed, 2),
            )

    except Exception:

        return (
            None,
            None,
        )


async def get_lunar_status() -> dict[str, object]:

    async with aiohttp.ClientSession(
        timeout=HTTP_TIMEOUT
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
        "api_status": api[0],
        "api_latency": api[1],
    }


def format_status(
    status: int | None,
    latency: float | None,
) -> str:

    if status == 200:

        latency_text = (
            f"`{latency}ms`"
            if latency is not None
            else "`N/A`"
        )

        return (
            f"{EMOJI['approved']} **Up**\n"
            f"HTTP `{status}` • {latency_text}"
        )

    if status is None:

        return (
            f"{EMOJI['question']} **Unknown**\n"
            "Unable to reach service"
        )

    latency_text = (
        f"`{latency}ms`"
        if latency is not None
        else "`N/A`"
    )

    return (
        f"{EMOJI['denied']} **Down**\n"
        f"HTTP `{status}` • {latency_text}"
    )


# ============================================================
# ABOUT
# ============================================================

class About(commands.Cog):

    def __init__(
        self,
        bot: commands.Bot,
    ):
        self.bot = bot

    # --------------------------------------------------------
    # /about
    # --------------------------------------------------------

    @app_commands.command(
        name="about",
        description="View information and live statistics about Lunar.",
    )
    async def about(
        self,
        interaction: discord.Interaction,
    ):

        # ----------------------------------------------------
        # LOADING
        # ----------------------------------------------------

        await interaction.response.send_message(
            f"{EMOJI['loading']} Loading Lunar information...",
            ephemeral=True,
        )

        await asyncio.sleep(1)

        # ----------------------------------------------------
        # BOT INFORMATION
        # ----------------------------------------------------

        bot_name = BOT["name"]
        bot_version = BOT["version"]

        developers = get_developers(
            "discord"
        )

        uptime = get_uptime()

        # ----------------------------------------------------
        # DISCORD STATISTICS
        # ----------------------------------------------------

        guild_count = len(
            self.bot.guilds
        )

        user_count = sum(
            guild.member_count or 0
            for guild in self.bot.guilds
        )

        channel_count = sum(
            len(guild.channels)
            for guild in self.bot.guilds
        )

        loaded_cogs = len(
            self.bot.cogs
        )

        registered_commands = sum(
            1
            for _ in self.bot.tree.walk_commands()
        )

        gateway_latency = round(
            self.bot.latency * 1000
        )

        # ----------------------------------------------------
        # COMMAND USAGE
        # ----------------------------------------------------

        try:

            total_commands_used = (
                await db.command_stats.total()
            )

        except Exception:

            total_commands_used = 0

        # ----------------------------------------------------
        # LUNAR STATUS
        # ----------------------------------------------------

        try:

            lunar_status = (
                await get_lunar_status()
            )

        except Exception:

            lunar_status = {
                "website_status": None,
                "website_latency": None,
                "api_status": None,
                "api_latency": None,
            }

        website_status = (
            lunar_status["website_status"]
        )

        website_latency = (
            lunar_status["website_latency"]
        )

        api_status = (
            lunar_status["api_status"]
        )

        api_latency = (
            lunar_status["api_latency"]
        )

        # ----------------------------------------------------
        # OVERALL STATUS
        # ----------------------------------------------------

        systems_online = (
            website_status == 200
            and api_status == 200
        )

        # ----------------------------------------------------
        # CURRENT PRESENCE
        # ----------------------------------------------------

        current_presence = "Unknown"

        if self.bot.activity is not None:

            if (
                self.bot.activity.type
                == discord.ActivityType.watching
            ):

                current_presence = (
                    self.bot.activity.name
                    or "Unknown"
                )

        # ----------------------------------------------------
        # EMBED
        # ----------------------------------------------------

        embed = discord.Embed(
            title=(
                f"{EMOJI['lunar']} "
                f"{bot_name}"
            ),
            description=(
                f"{EMOJI['moon']} "
                "Lunar's Discord infrastructure, "
                "statistics and service status."
            ),
            color=(
                discord.Color.green()
                if systems_online
                else discord.Color.red()
            ),
            timestamp=discord.utils.utcnow(),
        )

        # ----------------------------------------------------
        # INFORMATION
        # ----------------------------------------------------

        embed.add_field(
            name=f"{EMOJI['lunar']} Information",
            value=(
                f"**Version:** `{bot_version}`\n"
                f"**Uptime:** `{uptime}`\n"
                f"**Developers:**\n"
                f"{developers}"
            ),
            inline=False,
        )

        # ----------------------------------------------------
        # DISCORD
        # ----------------------------------------------------

        embed.add_field(
            name=f"{EMOJI['staff']} Discord",
            value=(
                f"**Servers:** `{guild_count:,}`\n"
                f"**Users:** `{user_count:,}`\n"
                f"**Channels:** `{channel_count:,}`\n"
                f"**Loaded Cogs:** `{loaded_cogs}`"
            ),
            inline=True,
        )

        # ----------------------------------------------------
        # COMMANDS
        # ----------------------------------------------------

        embed.add_field(
            name=f"{EMOJI['dev']} Commands",
            value=(
                f"**Registered:** "
                f"`{registered_commands:,}`\n"
                f"**Total Used:** "
                f"`{total_commands_used:,}`"
            ),
            inline=True,
        )

        # ----------------------------------------------------
        # LATENCY
        # ----------------------------------------------------

        embed.add_field(
            name=f"{EMOJI['loading']} Latency",
            value=(
                f"**Discord:** "
                f"`{gateway_latency}ms`"
            ),
            inline=True,
        )

        # ----------------------------------------------------
        # WEBSITE
        # ----------------------------------------------------

        embed.add_field(
            name=f"{EMOJI['lunar']} Website",
            value=format_status(
                website_status,
                website_latency,
            ),
            inline=True,
        )

        # ----------------------------------------------------
        # API
        # ----------------------------------------------------

        embed.add_field(
            name=f"{EMOJI['dev']} API",
            value=format_status(
                api_status,
                api_latency,
            ),
            inline=True,
        )

        # ----------------------------------------------------
        # PRESENCE
        # ----------------------------------------------------

        embed.add_field(
            name=f"{EMOJI['moon']} Current Presence",
            value=(
                f"Watching `{current_presence}`"
            ),
            inline=True,
        )

        # ----------------------------------------------------
        # FOOTER
        # ----------------------------------------------------

        embed.set_footer(
            text=(
                "Lunar Infrastructure "
                "• Imperial Systems"
            )
        )

        # ----------------------------------------------------
        # RESPONSE
        # ----------------------------------------------------

        await interaction.edit_original_response(
            content=None,
            embed=embed,
        )


# ============================================================
# SETUP
# ============================================================

async def setup(
    bot: commands.Bot,
):

    await bot.add_cog(
        About(bot)
    )
