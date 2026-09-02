from __future__ import annotations

import aiohttp
import discord

from discord import app_commands
from discord.ext import commands

from cogs.utilities.emoji import EMOJI


# ============================================================
# CONFIG
# ============================================================

DAD_JOKE_API = (
    "https://icanhazdadjoke.com/"
)


# ============================================================
# DAD JOKE COG
# ============================================================

class DadJoke(
    commands.Cog
):

    def __init__(
        self,
        bot: commands.Bot,
    ):
        self.bot = bot

    # ========================================================
    # /dadJoke
    # ========================================================

    @app_commands.command(
        name="dadjoke",
        description="Get a random dad joke.",
    )
    async def dadjoke(
        self,
        interaction: discord.Interaction,
    ):

        await interaction.response.send_message(
            f"{EMOJI['loading']} "
            "Finding a dad joke...",
            ephemeral=True,
        )

        try:

            async with aiohttp.ClientSession() as session:

                async with session.get(
                    DAD_JOKE_API,
                    headers={
                        "Accept": "text/plain",
                    },
                    timeout=aiohttp.ClientTimeout(
                        total=10
                    ),
                ) as response:

                    if response.status != 200:

                        await interaction.edit_original_response(
                            content=(
                                f"{EMOJI['error']} "
                                "I couldn't fetch a dad joke right now."
                            )
                        )

                        return

                    joke = await response.text()

            joke = joke.strip()

            if not joke:

                await interaction.edit_original_response(
                    content=(
                        f"{EMOJI['error']} "
                        "The dad joke service returned nothing."
                    )
                )

                return

            await interaction.edit_original_response(
                content=joke
            )

        except (
            aiohttp.ClientError,
            TimeoutError,
        ):

            await interaction.edit_original_response(
                content=(
                    f"{EMOJI['error']} "
                    "The dad joke service is unavailable right now."
                )
            )


# ============================================================
# SETUP
# ============================================================

async def setup(
    bot: commands.Bot,
):

    await bot.add_cog(
        DadJoke(bot)
    )
