from __future__ import annotations

import asyncio

import discord

from discord import app_commands
from discord.ext import commands

from cogs.utilities.emoji import EMOJI


# ============================================================
# CONFIG
# ============================================================

FAKE_LOADING_TIME = 1.0


# ============================================================
# CLOSE COG
# ============================================================

class Close(
    commands.Cog
):

    def __init__(
        self,
        bot: commands.Bot,
    ):
        self.bot = bot

    # ========================================================
    # /close
    # ========================================================

    @app_commands.command(
        name="close",
        description="Close and lock the current thread.",
    )
    @app_commands.default_permissions(
        manage_threads=True
    )
    async def close(
        self,
        interaction: discord.Interaction,
    ):

        # ----------------------------------------------------
        # Thread Check
        # ----------------------------------------------------

        if not isinstance(
            interaction.channel,
            discord.Thread,
        ):

            await interaction.response.send_message(
                f"{EMOJI['denied']} "
                "This command can only be used inside a thread.",
                ephemeral=True,
            )

            return

        thread = interaction.channel

        # ----------------------------------------------------
        # Permission Check
        # ----------------------------------------------------

        if not isinstance(
            interaction.user,
            discord.Member,
        ):

            await interaction.response.send_message(
                f"{EMOJI['denied']} "
                "I couldn't verify your permissions.",
                ephemeral=True,
            )

            return

        if not interaction.user.guild_permissions.manage_threads:

            await interaction.response.send_message(
                f"{EMOJI['denied']} "
                "You need **Manage Threads** permission "
                "to close this thread.",
                ephemeral=True,
            )

            return

        # ----------------------------------------------------
        # Loading
        # ----------------------------------------------------

        await interaction.response.send_message(
            f"{EMOJI['loading']} "
            "Closing and locking thread...",
            ephemeral=True,
        )

        await asyncio.sleep(
            FAKE_LOADING_TIME
        )

        # ----------------------------------------------------
        # Closing Message
        # ----------------------------------------------------

        try:

            await thread.send(
                embed=discord.Embed(
                    title=(
                        f"{EMOJI['approved']} "
                        "Thread Closed"
                    ),
                    description=(
                        f"{EMOJI['denied']} "
                        "This thread has been **closed and locked**.\n\n"
                        f"{EMOJI['staff']} "
                        f"Closed by {interaction.user.mention}."
                    ),
                    color=discord.Color.red(),
                    timestamp=discord.utils.utcnow(),
                )
            )

        except discord.Forbidden:

            await interaction.edit_original_response(
                content=(
                    f"{EMOJI['error']} "
                    "I don't have permission to send messages "
                    "in this thread."
                )
            )

            return

        except discord.HTTPException:

            await interaction.edit_original_response(
                content=(
                    f"{EMOJI['error']} "
                    "I couldn't send the closing message."
                )
            )

            return

        # ----------------------------------------------------
        # Lock + Archive
        # ----------------------------------------------------

        try:

            await thread.edit(
                locked=True,
                archived=True,
                reason=(
                    f"Thread closed by "
                    f"{interaction.user}"
                ),
            )

        except discord.Forbidden:

            await interaction.edit_original_response(
                content=(
                    f"{EMOJI['error']} "
                    "I couldn't lock this thread. "
                    "Make sure I have **Manage Threads** permission."
                )
            )

            return

        except discord.HTTPException:

            await interaction.edit_original_response(
                content=(
                    f"{EMOJI['error']} "
                    "Discord rejected the thread close request."
                )
            )

            return

        # ----------------------------------------------------
        # Done
        # ----------------------------------------------------

        await interaction.edit_original_response(
            content=(
                f"{EMOJI['approved']} "
                "Thread closed and locked successfully."
            )
        )


# ============================================================
# SETUP
# ============================================================

async def setup(
    bot: commands.Bot,
):

    await bot.add_cog(
        Close(bot)
    )