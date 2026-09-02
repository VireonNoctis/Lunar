import asyncio
import time

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

from utilities.database import db
from cogs.utilities.emoji import EMOJI


# ============================================================
# BOT INFORMATION
# ============================================================

BOT_NAME = "Lunaranime Bot"
BOT_VERSION = "3.0.0"

DEVELOPERS = (
    "Vireon",
    "Thanon",
)

LUNAR_WEBSITE = "https://lunarx.to"
LUNAR_API = "https://api.lunarx.to"

HTTP_TIMEOUT = aiohttp.ClientTimeout(
    total=10,
    connect=5,
    sock_connect=5,
    sock_read=5,
)

STARTED_AT = time.time()


# ============================================================
# HELPERS
# ============================================================

def get_uptime() -> str:

    elapsed = int(
        time.time() - STARTED_AT
    )

    days, remainder = divmod(
        elapsed,
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
        parts.append(f"{days}d")

    if hours:
        parts.append(f"{hours}h")

    if minutes:
        parts.append(f"{minutes}m")

    if seconds or not parts:
        parts.append(f"{seconds}s")

    return " ".join(parts)


def get_developers() -> str:
    return "\n".join(
        f"{EMOJI['dev']} `{developer}`"
        for developer in DEVELOPERS
    )


def get_registered_command_count(
    bot: commands.Bot,
) -> int:

    return sum(
        1
        for command in bot.tree.walk_commands()
    )


async def fetch_endpoint_status(
    session: aiohttp.ClientSession,
    url: str,
) -> tuple[int | None, float | None]:

    started = time.perf_counter()

    try:

        async with session.get(
            url,
            allow_redirects=True,
        ) as response:

            latency = (
                time.perf_counter() - started
            ) * 1000

            return (
                response.status,
                round(latency, 2),
            )

    except Exception:

        return (
            None,
            None,
        )


async def fetch_lunar_status() -> dict[str, object]:

    async with aiohttp.ClientSession(
        timeout=HTTP_TIMEOUT
    ) as session:

        website_task = fetch_endpoint_status(
            session,
            LUNAR_WEBSITE,
        )

        api_task = fetch_endpoint_status(
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


def format_service(
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
# ABOUT COG
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
        # FAKE LOADING
        # ----------------------------------------------------

        await interaction.response.send_message(
            f"{EMOJI['loading']} Loading Lunar information...",
            ephemeral=True,
        )

        await asyncio.sleep(1)

        # ----------------------------------------------------
        # BASIC BOT STATS
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

        command_count = get_registered_command_count(
            self.bot
        )

        gateway_latency = round(
            self.bot.latency * 1000
        )

        uptime = get_uptime()

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
                await fetch_lunar_status()
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

        services_online = (
            website_status == 200
            and api_status == 200
        )

        # ----------------------------------------------------
        # CURRENT WATCHING STATUS
        # ----------------------------------------------------

        watching_status = "Unknown"

        if self.bot.activity is not None:

            if isinstance(
                self.bot.activity,
                discord.Activity,
            ):

                if self.bot.activity.type == (
                    discord.ActivityType.watching
                ):

                    watching_status = (
                        self.bot.activity.name
                        or "Unknown"
                    )

        # ----------------------------------------------------
        # LOADED COGS
        # ----------------------------------------------------

        loaded_cog_count = len(
            self.bot.cogs
        )

        # ----------------------------------------------------
        # EMBED
        # ----------------------------------------------------

        embed = discord.Embed(
            title=(
                f"{EMOJI['lunar']} "
                f"{BOT_NAME}"
            ),
            description=(
                f"{EMOJI['moon']} "
                "Lunar's central Discord infrastructure "
                "and service information."
            ),
            color=(
                discord.Color.green()
                if services_online
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
                f"**Version:** `{BOT_VERSION}`\n"
                f"**Uptime:** `{uptime}`\n"
                f"**Developers:**\n"
                f"{get_developers()}"
            ),
            inline=False,
        )

        # ----------------------------------------------------
        # DISCORD STATISTICS
        # ----------------------------------------------------

        embed.add_field(
            name=f"{EMOJI['staff']} Discord",
            value=(
                f"**Servers:** `{guild_count:,}`\n"
                f"**Users:** `{user_count:,}`\n"
                f"**Channels:** `{channel_count:,}`\n"
                f"**Loaded Cogs:** `{loaded_cog_count}`"
            ),
            inline=True,
        )

        # ----------------------------------------------------
        # COMMAND STATISTICS
        # ----------------------------------------------------

        embed.add_field(
            name=f"{EMOJI['dev']} Commands",
            value=(
                f"**Registered:** `{command_count:,}`\n"
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
                f"**Discord:** `{gateway_latency}ms`"
            ),
            inline=True,
        )

        # ----------------------------------------------------
        # WEBSITE
        # ----------------------------------------------------

        embed.add_field(
            name=f"{EMOJI['lunar']} Website",
            value=format_service(
                website_status,
                website_latency,
            ),
            inline=True,
        )

        # ----------------------------------------------------
        # API
        # --------------------------------------------------------

        embed.add_field(
            name=f"{EMOJI['dev']} API",
            value=format_service(
                api_status,
                api_latency,
            ),
            inline=True,
        )

        # ----------------------------------------------------
        # WATCHING STATUS
        # ----------------------------------------------------

        embed.add_field(
            name=f"{EMOJI['moon']} Current Presence",
            value=(
                f"Watching `{watching_status}`"
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
        # SEND
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
