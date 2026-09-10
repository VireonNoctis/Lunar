from __future__ import annotations

import logging
import os
from typing import Sequence

import discord
from discord.ext import commands

from cogs.utilities.randomizer import CryptographicRandomizer


log = logging.getLogger(__name__)


# ============================================================
# CONFIGURATION
# ============================================================

TARGET_USER_ID = 756535229933551656

# Optional environment configuration:
#
# COLLECTION_GIFS=
# https://example.com/gif1.gif
# https://example.com/gif2.gif
# https://example.com/gif3.gif
#
# Newline-separated is recommended, but commas also work.

RAW_COLLECTION_GIFS = (
  
)


def load_collection() -> tuple[str, ...]:
    """
    Load the GIF collection from the environment.

    Supports:
        one URL per line
        comma-separated URLs
    """

    if not RAW_COLLECTION_GIFS.strip():
        return ()

    values: list[str] = []

    for line in RAW_COLLECTION_GIFS.replace(
        ",",
        "\n",
    ).splitlines():

        value = line.strip()

        if not value:
            continue

        if value not in values:
            values.append(value)

    return tuple(values)


COLLECTION_GIFS: Sequence[str] = load_collection()


# ============================================================
# COG
# ============================================================

class CollectionReply(commands.Cog):
    """
    Automatically replies to messages from one configured
    Discord user with a cryptographically randomized GIF.
    """

    def __init__(
        self,
        bot: commands.Bot,
    ):
        self.bot = bot

        if not COLLECTION_GIFS:
            log.warning(
                "Collection GIF responder loaded with an empty collection."
            )

        else:
            log.info(
                "Collection GIF responder loaded with %d GIF(s).",
                len(COLLECTION_GIFS),
            )

    # ========================================================
    # MESSAGE LISTENER
    # ========================================================

    @commands.Cog.listener()
    async def on_message(
        self,
        message: discord.Message,
    ) -> None:

        # ----------------------------------------------------
        # Ignore bots / webhooks
        # ----------------------------------------------------

        if message.author.bot:
            return

        if message.webhook_id is not None:
            return

        # ----------------------------------------------------
        # Only target the configured user
        # ----------------------------------------------------

        if message.author.id != TARGET_USER_ID:
            return

        # ----------------------------------------------------
        # Optional: guild-only
        #
        # Remove this if you also want it to work in DMs.
        # ----------------------------------------------------

        if message.guild is None:
            return

        # ----------------------------------------------------
        # Nothing to select from
        # ----------------------------------------------------

        if not COLLECTION_GIFS:
            log.warning(
                "Target user %s triggered the responder, "
                "but COLLECTION_GIFS is empty.",
                TARGET_USER_ID,
            )
            return

        # ----------------------------------------------------
        # Cryptographically secure selection
        # ----------------------------------------------------

        try:
            selected_gif, proof = (
                CryptographicRandomizer.choose(
                    COLLECTION_GIFS,
                    context=(
                        f"LUNAR-COLLECTION|"
                        f"{message.guild.id}|"
                        f"{message.channel.id}|"
                        f"{message.id}|"
                        f"{message.author.id}"
                    ),
                )
            )

        except Exception:
            log.exception(
                "Failed to select a collection GIF."
            )
            return

        # ----------------------------------------------------
        # Reply
        # ----------------------------------------------------

        try:
            await message.reply(
                selected_gif,
                mention_author=False,
                allowed_mentions=discord.AllowedMentions(
                    users=False,
                    roles=False,
                    everyone=False,
                ),
            )

        except discord.Forbidden:
            log.warning(
                "Missing permission to reply in channel %s.",
                message.channel.id,
            )

        except discord.HTTPException:
            log.exception(
                "Discord rejected the collection GIF reply."
            )

        else:
            log.debug(
                "Collection GIF sent for message %s "
                "(proof=%s).",
                message.id,
                proof,
            )


# ============================================================
# SETUP
# ============================================================

async def setup(
    bot: commands.Bot,
) -> None:
    await bot.add_cog(
        CollectionReply(bot)
    )
