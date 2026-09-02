from __future__ import annotations

import random

import discord

from discord import app_commands
from discord.ext import commands

from cogs.utilities.database import db
from cogs.utilities.emoji import EMOJI
from cogs.utilities.randomizer import (
    CryptographicRandomizer,
)


# ============================================================
# CONFIG
# ============================================================

METHODS = [
    "normal",
    "mischievous",
    "mathematical",
    "numerical",
    "binary",
    "beautiful",
    "anime like",
    "philosophical",
    "cursed",
    "traditional",
    "typescript",
    "ram using",
    "dark",
    "blinding",
    "monumental",
    "video producing",
    "family guy",
    "marketing",
    "red",
    "green",
    "blue",
    "pink",
    "orange",
    "golden",
    "fishy",
    "legal",
    "rough",
    "breath taking",
    "earth shattering",
    "plague giving",
]

ACTIONS = {
    "touch": "touched",
    "poke": "poked",
    "hug": "hugged",
    "punch": "punched",
    "kick": "kicked",
    "slap": "slapped",
    "pat": "patted",
    "bodyslam": "body slammed",
    "dmca": "DMCA striked",
}

EXTENSION_NAMESPACE = "interactions"


# ============================================================
# HELPERS
# ============================================================

def pick_method() -> tuple[str, int]:
    index = random.randrange(
        len(METHODS)
    )

    return (
        METHODS[index],
        index,
    )


async def save_interaction(
    interaction: discord.Interaction,
    *,
    action: str,
    target_ids: list[str],
    method: str,
    method_index: int,
) -> None:
    """
    Stores the latest interaction metadata in Scylla through
    the centralized extension system.

    Storage failures intentionally do not break the command.
    """

    try:
        guild_id = str(
            interaction.guild_id
            or "dm"
        )

        await db.extensions.set(
            EXTENSION_NAMESPACE,
            guild_id,
            "last_interaction",
            {
                "action": action,
                "author_id": str(
                    interaction.user.id
                ),
                "target_ids": ",".join(
                    target_ids
                ),
                "method": method,
                "method_index": str(
                    method_index
                ),
            },
        )

    except Exception:
        pass


def build_targets(
    targets: list[discord.User | discord.Member],
) -> str:
    return " and ".join(
        user.mention
        for user in targets
    )


# ============================================================
# COG
# ============================================================

class Interactions(
    commands.Cog
):

    def __init__(
        self,
        bot: commands.Bot,
    ):
        self.bot = bot

    # ========================================================
    # MAIN INTERACTION COMMAND
    # ========================================================

    @app_commands.command(
        name="interact",
        description="Perform a random fun interaction with another user.",
    )
    @app_commands.describe(
        action="The interaction to perform.",
        user="The first user.",
        user2="Optional second user.",
        user3="Optional third user.",
    )
    @app_commands.choices(
        action=[
            app_commands.Choice(
                name="Touch",
                value="touch",
            ),
            app_commands.Choice(
                name="Poke",
                value="poke",
            ),
            app_commands.Choice(
                name="Hug",
                value="hug",
            ),
            app_commands.Choice(
                name="Punch",
                value="punch",
            ),
            app_commands.Choice(
                name="Kick",
                value="kick",
            ),
            app_commands.Choice(
                name="Slap",
                value="slap",
            ),
            app_commands.Choice(
                name="Pat",
                value="pat",
            ),
            app_commands.Choice(
                name="Bodyslam",
                value="bodyslam",
            ),
            app_commands.Choice(
                name="DMCA Strike",
                value="dmca",
            ),
        ]
    )
    async def interact(
        self,
        interaction: discord.Interaction,
        action: app_commands.Choice[str],
        user: discord.User,
        user2: discord.User | None = None,
        user3: discord.User | None = None,
    ):
        if user.id == interaction.user.id:
            await interaction.response.send_message(
                f"{EMOJI['question']} "
                "You need to select another user.",
                ephemeral=True,
            )
            return

        targets = [
            user,
        ]

        if user2 is not None:
            targets.append(
                user2
            )

        if user3 is not None:
            targets.append(
                user3
            )

        if any(
            target.id == interaction.guild.id
            if interaction.guild
            else False
            for target in targets
        ):
            await interaction.response.send_message(
                f"{EMOJI['denied']} "
                "That target is not valid.",
                ephemeral=True,
            )
            return

        method, method_index = (
            pick_method()
        )

        action_value = action.value
        verb = ACTIONS[
            action_value
        ]

        target_text = build_targets(
            targets
        )

        if action_value == "pat":

            special_targets = {
                "dog": "<@1419744000977403994>",
                "puppy": "<@960946185768685618>",
                "kitten": "<@756535229933551656>",
            }

            if user.name.lower() in special_targets:
                target_text = (
                    special_targets[
                        user.name.lower()
                    ]
                )

        message = (
            f"{interaction.user.mention} "
            f"{verb} {target_text} "
            f"in a(n) **{method}** way "
            f"({method_index}/{len(METHODS) - 1})"
        )

        await save_interaction(
            interaction,
            action=action_value,
            target_ids=[
                str(target.id)
                for target in targets
            ],
            method=method,
            method_index=method_index,
        )

        embed = discord.Embed(
            title=(
                f"{EMOJI['lunar']} "
                f"{action_value.title()}"
            ),
            description=message,
            color=discord.Color.blurple(),
        )

        embed.add_field(
            name="Method",
            value=method,
            inline=True,
        )

        embed.add_field(
            name="Random Index",
            value=(
                f"{method_index}/"
                f"{len(METHODS) - 1}"
            ),
            inline=True,
        )

        embed.set_footer(
            text="Lunar Interactions"
        )

        await interaction.response.send_message(
            embed=embed
        )

    # ========================================================
    # INTERACTION HELP
    # ========================================================

    @app_commands.command(
        name="interaction-help",
        description="Show available interaction commands.",
    )
    async def interaction_help(
        self,
        interaction: discord.Interaction,
    ):

        embed = discord.Embed(
            title=(
                f"{EMOJI['question']} "
                "Interaction Commands"
            ),
            description=(
                "Use `/interact` and select an action."
            ),
            color=discord.Color.blurple(),
        )

        embed.add_field(
            name="Available Actions",
            value="\n".join(
                f"`{name}`"
                for name in ACTIONS
            ),
            inline=False,
        )

        await interaction.response.send_message(
            embed=embed,
            ephemeral=True,
        )


# ============================================================
# SETUP
# ============================================================

async def setup(
    bot: commands.Bot,
):
    await bot.add_cog(
        Interactions(bot)
    )
