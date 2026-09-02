from __future__ import annotations

import random

import aiohttp
import discord

from discord import app_commands
from discord.ext import commands

from cogs.utilities.database import db


SUBREDDITS = [
    "darkmemers",
    "memes",
    "dankmemes",
    "me_irl",
    "funny",
    "Animemes",
    "AnarchyChess",
    "stonks",
    "GymMemes",
    "RelationshipMemes",
    "CoupleMemes",
    "CollegeMemes",
    "antimeme",
    "Random_Memes",
    "badmemes",
    "cursedmemes",
    "DeepFriedMemes",
    "ShitMemers",
    "MemeVideos",
    "depressionmemes",
    "PhilosophyMemes",
    "nukedmemes",
    "GenZHumor",
    "SipsTea",
    "perfectlycutscreams",
    "blursed_videos",
    "sadposting",
]


EXTENSION_NAMESPACE = "random_meme"


class RandomMeme(commands.Cog):
    def __init__(
        self,
        bot: commands.Bot,
    ):
        self.bot = bot

    async def save_meme_state(
        self,
        guild_id: int | None,
        subreddit: str,
        meme: dict,
    ):
        try:
            await db.extensions.set(
                EXTENSION_NAMESPACE,
                str(guild_id or "dm"),
                "last_meme",
                {
                    "subreddit": subreddit,
                    "title": str(
                        meme.get(
                            "title",
                            "Random Meme",
                        )
                    ),
                    "url": str(
                        meme.get(
                            "url",
                            "",
                        )
                    ),
                    "author": str(
                        meme.get(
                            "author",
                            "Unknown",
                        )
                    ),
                    "ups": str(
                        meme.get(
                            "ups",
                            0,
                        )
                    ),
                },
            )

        except Exception:
            # Meme delivery should not fail because database
            # telemetry/storage failed.
            pass

    @app_commands.command(
        name="randommeme",
        description="Fetch a random meme.",
    )
    async def random_meme(
        self,
        interaction: discord.Interaction,
    ):
        if interaction.channel is None:
            await interaction.response.send_message(
                "This command cannot be used here.",
                ephemeral=True,
            )
            return

        subreddit = random.choice(
            SUBREDDITS
        )

        await interaction.response.send_message(
            f"Fetching Meme from r/{subreddit}..."
        )

        meme_message = (
            await interaction.original_response()
        )

        api_url = (
            f"https://meme-api.com/gimme/"
            f"{subreddit}/1"
        )

        try:
            timeout = aiohttp.ClientTimeout(
                total=10
            )

            async with aiohttp.ClientSession(
                timeout=timeout
            ) as session:

                async with session.get(
                    api_url
                ) as response:

                    if response.status != 200:
                        await meme_message.edit(
                            content=(
                                f"Failed to fetch from "
                                f"r/{subreddit}."
                            ),
                        )
                        return

                    data = await response.json()

        except (
            aiohttp.ClientError,
            aiohttp.ContentTypeError,
            TimeoutError,
        ):
            await meme_message.edit(
                content=(
                    f"Failed to fetch from "
                    f"r/{subreddit}."
                ),
            )
            return

        memes = data.get(
            "memes",
            [],
        )

        if not memes:
            await meme_message.edit(
                content=(
                    f"No meme was returned from "
                    f"r/{subreddit}."
                ),
            )
            return

        meme = memes[0]

        is_nsfw = bool(
            meme.get(
                "nsfw",
                False,
            )
        )

        if (
            is_nsfw
            and isinstance(
                interaction.channel,
                discord.TextChannel,
            )
            and not interaction.channel.is_nsfw()
        ):
            await meme_message.edit(
                content=(
                    f"The selected meme from "
                    f"r/{subreddit} is not available "
                    "in this channel."
                ),
            )
            return

        image_url = meme.get(
            "url"
        )

        if not image_url:
            await meme_message.edit(
                content=(
                    f"The meme from r/{subreddit} "
                    "did not contain an image URL."
                ),
            )
            return

        title = meme.get(
            "title",
            "Random Meme",
        )

        author = meme.get(
            "author",
            "Unknown",
        )

        ups = meme.get(
            "ups",
            0,
        )

        meme_subreddit = meme.get(
            "subreddit",
            subreddit,
        )

        embed = discord.Embed(
            title=title,
            color=discord.Color.blurple(),
        )

        embed.set_image(
            url=image_url
        )

        embed.set_footer(
            text=(
                f"⬆ {ups} | "
                f"by {author} | "
                f"r/{meme_subreddit}"
            )
        )

        await self.save_meme_state(
            interaction.guild_id,
            subreddit,
            meme,
        )

        await meme_message.edit(
            content="",
            embed=embed,
        )


async def setup(
    bot: commands.Bot,
):
    await bot.add_cog(
        RandomMeme(bot)
    )
