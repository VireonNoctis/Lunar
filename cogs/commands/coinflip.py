from __future__ import annotations

import asyncio

import discord

from discord import app_commands
from discord.ext import commands

from cogs.utilities.emoji import EMOJI
from cogs.utilities.randomizer import (
    CryptographicRandomizer,
)


class Coinflip(
    commands.Cog
):
    """
    Cryptographically secure coin-flip command.
    """

    def __init__(
        self,
        bot: commands.Bot,
    ):
        self.bot = bot

    @app_commands.command(
        name="coinflip",
        description="Flip a cryptographically secure coin.",
    )
    async def coinflip(
        self,
        interaction: discord.Interaction,
    ):
        await interaction.response.defer()

        loading_messages = [
            "Generating secure entropy...",
            "Initializing random state...",
            "Preparing the coin...",
            "Performing cryptographic selection...",
        ]

        for message in loading_messages:

            await interaction.edit_original_response(
                embed=discord.Embed(
                    title=(
                        f"{EMOJI['loading']} Coinflip"
                    ),
                    description=message,
                    color=discord.Color.blurple(),
                )
            )

            await asyncio.sleep(
                0.45
            )

        seed = (
            CryptographicRandomizer
            .generate_seed()
        )

        result, proof = (
            CryptographicRandomizer.coinflip(
                seed=seed
            )
        )

        if result == "heads":

            face = "HEADS"

        else:

            face = "TAILS"

        embed = discord.Embed(
            title=(
                f"{EMOJI['lunar']} Coinflip"
            ),
            description=(
                f"# {face}\n\n"
                "The coin has landed."
            ),
            color=discord.Color.gold(),
        )

        embed.add_field(
            name="Result",
            value=(
                f"**{face}**"
            ),
            inline=True,
        )

        embed.add_field(
            name="Randomizer",
            value=(
                f"`{CryptographicRandomizer.algorithm}`"
            ),
            inline=True,
        )

        embed.add_field(
            name="Proof",
            value=f"`{proof}`",
            inline=False,
        )

        embed.set_footer(
            text=(
                "Cryptographically generated • "
                "No Math.random() equivalent used"
            )
        )

        await interaction.edit_original_response(
            embed=embed
        )


async def setup(
    bot: commands.Bot,
):
    await bot.add_cog(
        Coinflip(bot)
    )
