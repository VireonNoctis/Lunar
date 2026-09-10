from __future__ import annotations

import re

import aiohttp
import discord

from discord import app_commands
from discord.ext import commands

from cogs.utilities.emoji import EMOJI


# ============================================================
# CONFIG
# ============================================================

REQUEST_TIMEOUT = aiohttp.ClientTimeout(
    total=15,
    connect=5,
    sock_connect=5,
    sock_read=10,
)


# ============================================================
# EMOJI PARSING
# ============================================================

def parse_custom_emoji(
    value: str,
) -> discord.PartialEmoji | None:

    value = value.strip()

    try:
        emoji = discord.PartialEmoji.from_str(
            value
        )
    except Exception:
        return None

    if not emoji.id:
        return None

    return emoji


def emoji_from_match(
    match: re.Match,
) -> discord.PartialEmoji:

    full = match.group(0)

    return discord.PartialEmoji(
        name=match.group(1),
        id=int(match.group(2)),
        animated=full.startswith("<a:"),
    )


# ============================================================
# DOWNLOAD
# ============================================================

async def download_emoji(
    emoji: discord.PartialEmoji,
) -> bytes | None:

    if not emoji.url:
        return None

    try:

        async with aiohttp.ClientSession(
            timeout=REQUEST_TIMEOUT
        ) as session:

            async with session.get(
                str(emoji.url)
            ) as response:

                if response.status != 200:
                    return None

                return await response.read()

    except (
        aiohttp.ClientError,
        TimeoutError,
    ):

        return None


# ============================================================
# SUCCESS EMBED
# ============================================================

def success_embed(
    emoji: discord.Emoji,
) -> discord.Embed:

    embed = discord.Embed(
        title=(
            f"{EMOJI['approved']} Emoji Added"
        ),
        description=(
            f"{emoji}\n\n"
            f"**{emoji.name}** has been added "
            "to this server."
        ),
        color=discord.Color.green(),
    )

    embed.set_footer(
        text="Lunar • Emoji Manager"
    )

    return embed


# ============================================================
# COG
# ============================================================

class Steal(
    commands.Cog
):

    def __init__(
        self,
        bot: commands.Bot,
    ):
        self.bot = bot

    # ========================================================
    # CORE STEAL
    # ========================================================

    async def steal_emoji(
        self,
        guild: discord.Guild,
        emoji: discord.PartialEmoji,
    ) -> tuple[
        discord.Emoji | None,
        str | None,
    ]:

        # ----------------------------------------------------
        # Bot permissions
        # ----------------------------------------------------

        me = guild.me

        if me is None:

            return (
                None,
                "I couldn't resolve my member in this server.",
            )

        if not me.guild_permissions.manage_emojis_and_stickers:

            return (
                None,
                "I need **Manage Expressions** permission "
                "to add emojis.",
            )

        # ----------------------------------------------------
        # Download
        # ----------------------------------------------------

        image_data = await download_emoji(
            emoji
        )

        if image_data is None:

            return (
                None,
                "I couldn't download that emoji.",
            )

        # ----------------------------------------------------
        # Create
        # ----------------------------------------------------

        try:

            created = (
                await guild.create_custom_emoji(
                    name=(
                        emoji.name
                        or "stolen_emoji"
                    ),
                    image=image_data,
                    reason="Emoji stolen through Lunar",
                )
            )

            return (
                created,
                None,
            )

        except discord.Forbidden:

            return (
                None,
                "Discord denied permission to add the emoji.",
            )

        except discord.HTTPException as exc:

            if exc.status == 30008:

                return (
                    None,
                    "This server has reached its emoji limit.",
                )

            return (
                None,
                f"Discord rejected the emoji: `{exc}`",
            )

        except Exception:

            return (
                None,
                "Something went wrong while adding the emoji.",
            )

    # ========================================================
    # /steal
    # ========================================================

    @app_commands.command(
        name="steal",
        description="Steal a custom emoji and add it to this server.",
    )
    @app_commands.describe(
        emoji="The custom emoji you want to steal.",
    )
    @app_commands.default_permissions(
        manage_emojis_and_stickers=True
    )
    async def slash_steal(
        self,
        interaction: discord.Interaction,
        emoji: str,
    ):

        await interaction.response.send_message(
            f"{EMOJI['loading']} "
            "Stealing emoji...",
            ephemeral=True,
        )

        # ----------------------------------------------------
        # Guild
        # ----------------------------------------------------

        if interaction.guild is None:

            await interaction.edit_original_response(
                content=(
                    f"{EMOJI['denied']} "
                    "This command can only be used in a server."
                )
            )

            return

        # ----------------------------------------------------
        # User permissions
        # ----------------------------------------------------

        if not isinstance(
            interaction.user,
            discord.Member,
        ):

            await interaction.edit_original_response(
                content=(
                    f"{EMOJI['denied']} "
                    "I couldn't verify your permissions."
                )
            )

            return

        if not interaction.user.guild_permissions.manage_emojis_and_stickers:

            await interaction.edit_original_response(
                content=(
                    f"{EMOJI['denied']} "
                    "You need **Manage Expressions** permission "
                    "to steal emojis."
                )
            )

            return

        # ----------------------------------------------------
        # Parse
        # ----------------------------------------------------

        parsed = parse_custom_emoji(
            emoji
        )

        if parsed is None:

            await interaction.edit_original_response(
                content=(
                    f"{EMOJI['error']} "
                    "That isn't a valid custom Discord emoji.\n\n"
                    "Example: `<:lunar:123456789>`"
                )
            )

            return

        # ----------------------------------------------------
        # Steal
        # ----------------------------------------------------

        created, error = await self.steal_emoji(
            interaction.guild,
            parsed,
        )

        if error:

            await interaction.edit_original_response(
                content=(
                    f"{EMOJI['error']} "
                    f"{error}"
                )
            )

            return

        await interaction.edit_original_response(
            content=None,
            embed=success_embed(
                created
            ),
        )

    # ========================================================
    # ?steal
    # ========================================================

    @commands.command(
        name="steal",
    )
    @commands.guild_only()
    @commands.has_guild_permissions(
        manage_emojis_and_stickers=True
    )
    async def prefix_steal(
        self,
        ctx: commands.Context,
        *args: str,
    ):

        found: discord.PartialEmoji | None = None

        # ====================================================
        # METHOD 1
        # ?steal <:emoji:id>
        # ====================================================

        if args:

            raw_emoji = " ".join(
                args
            ).strip()

            found = parse_custom_emoji(
                raw_emoji
            )

        # ====================================================
        # METHOD 2
        # Reply to emoji message + ?steal
        # ====================================================

        elif ctx.message.reference is not None:

            reference = (
                ctx.message.reference
            )

            try:

                if (
                    reference.cached_message
                    is not None
                ):

                    message = (
                        reference.cached_message
                    )

                else:

                    message = (
                        await ctx.channel.fetch_message(
                            reference.message_id
                        )
                    )

            except (
                discord.NotFound,
                discord.Forbidden,
                discord.HTTPException,
            ):

                await ctx.reply(
                    f"{EMOJI['error']} "
                    "I couldn't retrieve the message you're replying to."
                )

                return

            # ------------------------------------------------
            # Search message content
            # ------------------------------------------------

            matches = list(
                re.finditer(
                    r"<a?:([A-Za-z0-9_]+):(\d+)>",
                    message.content,
                )
            )

            if matches:

                found = emoji_from_match(
                    matches[0]
                )

            # ------------------------------------------------
            # Search reactions
            # ------------------------------------------------

            if found is None:

                for reaction in (
                    message.reactions
                ):

                    reaction_emoji = (
                        reaction.emoji
                    )

                    if isinstance(
                        reaction_emoji,
                        discord.Emoji,
                    ):

                        found = (
                            discord.PartialEmoji(
                                name=(
                                    reaction_emoji.name
                                ),
                                id=(
                                    reaction_emoji.id
                                ),
                                animated=(
                                    reaction_emoji.animated
                                ),
                            )
                        )

                        break

                    if isinstance(
                        reaction_emoji,
                        discord.PartialEmoji,
                    ):

                        found = (
                            reaction_emoji
                        )

                        break

        # ====================================================
        # No argument / no reply
        # ====================================================

        else:

            await ctx.reply(
                f"{EMOJI['question']} "
                "Give me a custom emoji or reply to a message "
                "containing one.\n\n"
                "Example:\n"
                "`?steal <:emoji:123456789>`"
            )

            return

        # ====================================================
        # Invalid emoji
        # ====================================================

        if found is None:

            await ctx.reply(
                f"{EMOJI['error']} "
                "I couldn't find a valid custom emoji."
            )

            return

        # ====================================================
        # STEAL
        # ====================================================

        async with ctx.typing():

            created, error = await self.steal_emoji(
                ctx.guild,
                found,
            )

        if error:

            await ctx.reply(
                f"{EMOJI['error']} "
                f"{error}"
            )

            return

        await ctx.reply(
            embed=success_embed(
                created
            )
        )

    # ========================================================
    # PREFIX ERROR HANDLER
    # ========================================================

    @prefix_steal.error
    async def prefix_steal_error(
        self,
        ctx: commands.Context,
        error: commands.CommandError,
    ):

        if isinstance(
            error,
            commands.MissingPermissions,
        ):

            await ctx.reply(
                f"{EMOJI['denied']} "
                "You need **Manage Expressions** permission "
                "to use `?steal`."
            )

            return

        if isinstance(
            error,
            commands.NoPrivateMessage,
        ):

            await ctx.reply(
                f"{EMOJI['denied']} "
                "This command can only be used in a server."
            )

            return

        raise error


# ============================================================
# SETUP
# ============================================================

async def setup(
    bot: commands.Bot,
):

    await bot.add_cog(
        Steal(bot)
    )
