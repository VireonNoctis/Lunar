from __future__ import annotations

import asyncio

import discord

from discord import app_commands
from discord.ext import commands

from cogs.utilities.emoji import EMOJI
from cogs.utilities.randomizer import (
    CryptographicRandomizer,
)


# ============================================================
# CONFIG
# ============================================================

FAKE_LOADING_TIME = 1.0


# ============================================================
# 8BALL RESPONSES
# ============================================================

EIGHT_BALL_RESPONSES = (
    "Definitely.",
    "Without a doubt.",
    "Absolutely.",
    "Most likely.",
    "Signs point to yes.",
    "It looks promising.",
    "Probably.",
    "Yes.",
    "Ask again later.",
    "Hard to tell right now.",
    "The answer is unclear.",
    "Maybe.",
    "Don't count on it.",
    "Probably not.",
    "Signs point to no.",
    "Very unlikely.",
    "No.",
    "Definitely not.",
)


# ============================================================
# HELPERS
# ============================================================

async def loading(
    interaction: discord.Interaction,
    message: str,
):
    await interaction.response.send_message(
        f"{EMOJI['loading']} {message}",
        ephemeral=True,
    )

    await asyncio.sleep(
        FAKE_LOADING_TIME
    )


def result_embed(
    title: str,
    description: str,
    *,
    color: discord.Color,
) -> discord.Embed:

    embed = discord.Embed(
        title=title,
        description=description,
        color=color,
        timestamp=discord.utils.utcnow(),
    )

    embed.set_footer(
        text="Lunar • Cryptographic Randomizer"
    )

    return embed


# ============================================================
# FUN COG
# ============================================================

class Fun(
    commands.Cog
):

    def __init__(
        self,
        bot: commands.Bot,
    ):
        self.bot = bot

    # ========================================================
    # /8BALL
    # ========================================================

    @app_commands.command(
        name="8ball",
        description="Ask the magic 8-ball a question.",
    )
    @app_commands.describe(
        question="The question you want to ask.",
    )
    async def eight_ball(
        self,
        interaction: discord.Interaction,
        question: str,
    ):

        question = question.strip()

        if not question:

            await interaction.response.send_message(
                f"{EMOJI['error']} "
                "You need to ask a question.",
                ephemeral=True,
            )

            return

        await loading(
            interaction,
            "Consulting the 8-ball...",
        )

        selection = (
            CryptographicRandomizer.select(
                [
                    str(index)
                    for index in range(
                        len(EIGHT_BALL_RESPONSES)
                    )
                ],
                1,
                context=(
                    "8ball:"
                    f"{interaction.user.id}:"
                    f"{question}"
                ),
            )
        )

        answer_index = int(
            selection.winners[0]
        )

        answer = (
            EIGHT_BALL_RESPONSES[
                answer_index
            ]
        )

        embed = result_embed(
            f"{EMOJI['question']} Magic 8-Ball",
            (
                f"**Question**\n"
                f"> {question}\n\n"
                f"{EMOJI['approved']} **Answer**\n"
                f"> **{answer}**"
            ),
            color=discord.Color.blurple(),
        )

        await interaction.edit_original_response(
            content=None,
            embed=embed,
        )

    # ========================================================
    # /DICE
    # ========================================================

    @app_commands.command(
        name="dice",
        description="Roll a cryptographically selected die.",
    )
    @app_commands.describe(
        sides="Number of sides on the die. Defaults to 6.",
    )
    async def dice(
        self,
        interaction: discord.Interaction,
        sides: app_commands.Range[int, 2, 1000] = 6,
    ):

        await loading(
            interaction,
            f"Rolling a {sides}-sided die...",
        )

        values = [
            str(value)
            for value in range(
                1,
                sides + 1,
            )
        ]

        selection = (
            CryptographicRandomizer.select(
                values,
                1,
                context=(
                    "dice:"
                    f"{interaction.user.id}:"
                    f"{sides}"
                ),
            )
        )

        result = int(
            selection.winners[0]
        )

        embed = result_embed(
            f"{EMOJI['lunar']} Dice Roll",
            (
                f"{EMOJI['approved']} "
                f"You rolled a **{result}** "
                f"on a **d{sides}**."
            ),
            color=discord.Color.gold(),
        )

        embed.add_field(
            name="Result",
            value=f"`{result}`",
            inline=True,
        )

        embed.add_field(
            name="Die",
            value=f"`d{sides}`",
            inline=True,
        )

        await interaction.edit_original_response(
            content=None,
            embed=embed,
        )

    # ========================================================
    # /RATE
    # ========================================================

    @app_commands.command(
        name="rate",
        description="Give something a cryptographically selected rating.",
    )
    @app_commands.describe(
        thing="What you want Lunar to rate.",
    )
    async def rate(
        self,
        interaction: discord.Interaction,
        thing: str,
    ):

        thing = thing.strip()

        if not thing:

            await interaction.response.send_message(
                f"{EMOJI['error']} "
                "Give me something to rate.",
                ephemeral=True,
            )

            return

        await loading(
            interaction,
            "Calculating the rating...",
        )

        # Select from every integer rating from 0 to 100.
        values = [
            str(value)
            for value in range(
                0,
                101,
            )
        ]

        selection = (
            CryptographicRandomizer.select(
                values,
                1,
                context=(
                    "rate:"
                    f"{interaction.user.id}:"
                    f"{thing}"
                ),
            )
        )

        rating = int(
            selection.winners[0]
        )

        # ----------------------------------------------------
        # Rating label
        # ----------------------------------------------------

        if rating >= 90:
            label = "Exceptional"
            color = discord.Color.green()

        elif rating >= 75:
            label = "Great"
            color = discord.Color.green()

        elif rating >= 60:
            label = "Good"
            color = discord.Color.gold()

        elif rating >= 40:
            label = "Average"
            color = discord.Color.orange()

        elif rating >= 20:
            label = "Not great"
            color = discord.Color.red()

        else:
            label = "Terrible"
            color = discord.Color.dark_red()

        embed = result_embed(
            f"{EMOJI['yellowstar']} Lunar Rating",
            (
                f"**Subject**\n"
                f"> {thing}\n\n"
                f"{EMOJI['approved']} **Rating**\n"
                f"> **{rating}/100**\n\n"
                f"**Verdict**\n"
                f"> {label}"
            ),
            color=color,
        )

        # ----------------------------------------------------
        # Visual rating bar
        # ----------------------------------------------------

        filled = rating // 10
        empty = 10 - filled

        bar = (
            "█" * filled
            + "░" * empty
        )

        embed.add_field(
            name="Score",
            value=f"`{bar}` **{rating}%**",
            inline=False,
        )

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
        Fun(bot)
    )