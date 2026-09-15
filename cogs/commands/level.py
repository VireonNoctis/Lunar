from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any, Optional

import discord
from discord import app_commands
from discord.ext import commands

from cogs.integrations.guild_xp import GuildXP
from cogs.utilities.database import db
from cogs.utilities.level_card import (
    BothLevelCardData,
    LevelCardData,
    LunarLevelCardData,
    render_both_level_card,
    render_guild_level_card,
    render_lunar_level_card,
)
from cogs.utilities.xp import format_xp


log = logging.getLogger("lunar.level")


class Level(
    commands.Cog
):
    """
    Unified Lunar level command.

    Guild XP:
        Authoritative Discord guild XP from Scylla.

    Lunar XP:
        Authoritative Lunar website XP fetched from the
        Lunar profile API.

    Both:
        Renders both progression systems together.
    """

    def __init__(
        self,
        bot: commands.Bot,
    ):
        self.bot = bot

    # ==========================================================
    # GENERIC RECORD HELPERS
    # ==========================================================

    @staticmethod
    def _get_value(
        record: Any,
        key: str,
        default: Any = None,
    ) -> Any:
        """
        Supports both repository objects and mapping-style
        records without forcing the database layer into a
        specific return type.
        """

        if record is None:
            return default

        if isinstance(
            record,
            Mapping,
        ):
            return record.get(
                key,
                default,
            )

        return getattr(
            record,
            key,
            default,
        )

    # ==========================================================
    # GUILD XP
    # ==========================================================

    async def get_guild_data(
        self,
        member: discord.Member,
    ) -> dict[str, Any]:
        """
        Load Guild XP from Scylla.

        The stored XP is the user's lifetime Guild XP.
        Current level progress is derived from the authoritative
        GuildXP progression helpers.
        """

        record = await db.guild_xp.get(
            member.guild.id,
            member.id,
        )

        if record is None:
            required_xp = GuildXP.required_xp_for_level(
                1
            )

            record = await db.guild_xp.ensure(
                member.guild.id,
                member.id,
                level=1,
                required_xp=required_xp,
            )

        total_xp = int(
            self._get_value(
                record,
                "xp",
                0,
            )
            or 0
        )

        progression = (
            GuildXP.progress_from_xp(
                total_xp
            )
        )

        level = int(
            progression.get(
                "level",
                self._get_value(
                    record,
                    "level",
                    1,
                ),
            )
            or 1
        )

        current_xp = int(
            progression.get(
                "xp",
                0,
            )
            or 0
        )

        required_xp = int(
            progression.get(
                "required_xp",
                GuildXP.required_xp_for_level(
                    level
                ),
            )
            or GuildXP.required_xp_for_level(
                level
            )
        )

        rank = await db.guild_xp.rank(
            member.guild.id,
            member.id,
        )

        total_messages = int(
            self._get_value(
                record,
                "total_messages",
                0,
            )
            or 0
        )

        return {
            "level": level,
            "current_xp": current_xp,
            "required_xp": required_xp,
            "total_xp": total_xp,
            "rank": int(rank or 0),
            "total_messages": total_messages,
        }

    # ==========================================================
    # LUNAR WEBSITE XP
    # ==========================================================

    async def get_lunar_data(
        self,
        member: discord.Member,
    ) -> Optional[dict[str, Any]]:
        """
        Resolve the user's linked Lunar account from Scylla,
        then fetch the authoritative website profile.

        The Lunar website remains the source of truth for
        Lunar level and XP.
        """

        account = await db.account_links.get(
            member.id
        )

        if account is None:
            return None

        verified = bool(
            self._get_value(
                account,
                "verified",
                False,
            )
        )

        if not verified:
            return None

        username = (
            self._get_value(
                account,
                "lunar_username",
                None,
            )
            or self._get_value(
                account,
                "username",
                None,
            )
        )

        if not username:
            log.warning(
                "Linked Lunar account for Discord user %s "
                "has no username.",
                member.id,
            )
            return None

        xp_cog = self.bot.get_cog(
            "XP"
        )

        if xp_cog is None:
            log.error(
                "XP integration cog is not loaded."
            )
            return None

        get_profile = getattr(
            xp_cog,
            "get_lunar_profile",
            None,
        )

        if not callable(
            get_profile
        ):
            log.error(
                "XP integration does not provide "
                "get_lunar_profile()."
            )
            return None

        profile = await get_profile(
            str(username)
        )

        if not isinstance(
            profile,
            Mapping,
        ):
            return None

        level = int(
            profile.get(
                "level",
                0,
            )
            or 0
        )

        xp = int(
            profile.get(
                "xp",
                0,
            )
            or 0
        )

        required_xp = int(
            profile.get(
                "required_xp",
                0,
            )
            or 0
        )

        if level <= 0:
            log.warning(
                "Lunar profile returned an invalid level "
                "for %s.",
                username,
            )
            return None

        return {
            "username": str(
                profile.get(
                    "username",
                    username,
                )
            ),
            "lunar_uuid": profile.get(
                "lunar_uuid"
            ),
            "level": level,
            "xp": xp,
            "current_xp": xp,
            "required_xp": required_xp,
            "total_xp": xp,
            "rank": profile.get(
                "rank"
            ),
            "avatar_url": profile.get(
                "avatar_url"
            ),
            "banner": profile.get(
                "banner"
            ),
            "title": profile.get(
                "title"
            ),
        }

    # ==========================================================
    # CARD DATA
    # ==========================================================

    @staticmethod
    def build_guild_card_data(
        member: discord.Member,
        data: Mapping[str, Any],
    ) -> LevelCardData:
        return LevelCardData(
            username=member.display_name,
            level=int(
                data.get(
                    "level",
                    1,
                )
            ),
            current_xp=int(
                data.get(
                    "current_xp",
                    0,
                )
            ),
            required_xp=int(
                data.get(
                    "required_xp",
                    0,
                )
            ),
            rank=int(
                data.get(
                    "rank",
                    0,
                )
                or 0
            ),
            total_xp=int(
                data.get(
                    "total_xp",
                    0,
                )
            ),
            avatar_url=str(
                member.display_avatar.url
            ),
        )

    @staticmethod
    def build_lunar_card_data(
        data: Mapping[str, Any],
    ) -> LunarLevelCardData:
        return LunarLevelCardData(
            username=str(
                data.get(
                    "username",
                    "Lunar User",
                )
            ),
            level=int(
                data.get(
                    "level",
                    1,
                )
            ),
            current_xp=int(
                data.get(
                    "current_xp",
                    data.get(
                        "xp",
                        0,
                    ),
                )
                or 0
            ),
            required_xp=int(
                data.get(
                    "required_xp",
                    0,
                )
                or 0
            ),
            total_xp=int(
                data.get(
                    "total_xp",
                    data.get(
                        "xp",
                        0,
                    ),
                )
                or 0
            ),
            rank=(
                int(
                    data["rank"]
                )
                if data.get(
                    "rank"
                ) is not None
                else None
            ),
            avatar_url=(
                str(
                    data["avatar_url"]
                )
                if data.get(
                    "avatar_url"
                )
                else None
            ),
        )

    # ==========================================================
    # EMBEDS
    # ==========================================================

    @staticmethod
    def build_guild_embed(
        member: discord.Member,
        data: Mapping[str, Any],
    ) -> discord.Embed:
        embed = discord.Embed(
            title="Guild XP",
            description=(
                f"{member.mention}'s Guild progression"
            ),
            colour=0x7C3AED,
        )

        level = int(
            data.get(
                "level",
                1,
            )
        )

        current_xp = int(
            data.get(
                "current_xp",
                0,
            )
        )

        required_xp = int(
            data.get(
                "required_xp",
                0,
            )
        )

        total_xp = int(
            data.get(
                "total_xp",
                0,
            )
        )

        rank = int(
            data.get(
                "rank",
                0,
            )
            or 0
        )

        embed.add_field(
            name="Level",
            value=f"`{level}`",
            inline=True,
        )

        embed.add_field(
            name="Rank",
            value=(
                f"`#{rank}`"
                if rank > 0
                else "`Unranked`"
            ),
            inline=True,
        )

        embed.add_field(
            name="Total XP",
            value=f"`{format_xp(total_xp)}`",
            inline=True,
        )

        embed.add_field(
            name="Progress",
            value=(
                f"`{format_xp(current_xp)}` / "
                f"`{format_xp(required_xp)} XP`"
            ),
            inline=False,
        )

        embed.set_thumbnail(
            url=member.display_avatar.url
        )

        embed.set_footer(
            text="Lunar • Guild XP"
        )

        return embed

    @staticmethod
    def build_lunar_embed(
        member: discord.Member,
        data: Mapping[str, Any],
    ) -> discord.Embed:
        embed = discord.Embed(
            title="Lunar Website XP",
            description=(
                f"{member.mention}'s Lunar website progression"
            ),
            colour=0x06B6D4,
        )

        level = int(
            data.get(
                "level",
                1,
            )
        )

        xp = int(
            data.get(
                "xp",
                0,
            )
        )

        required_xp = int(
            data.get(
                "required_xp",
                0,
            )
        )

        username = str(
            data.get(
                "username",
                "Unknown",
            )
        )

        embed.add_field(
            name="Username",
            value=f"`{username}`",
            inline=True,
        )

        embed.add_field(
            name="Level",
            value=f"`{level}`",
            inline=True,
        )

        embed.add_field(
            name="XP",
            value=(
                f"`{format_xp(xp)}` / "
                f"`{format_xp(required_xp)}`"
            ),
            inline=True,
        )

        title = data.get(
            "title"
        )

        if title:
            embed.add_field(
                name="Title",
                value=f"`{title}`",
                inline=True,
            )

        embed.set_thumbnail(
            url=(
                data.get(
                    "avatar_url"
                )
                or member.display_avatar.url
            )
        )

        embed.set_footer(
            text="Lunar • Website XP"
        )

        return embed

    # ==========================================================
    # COMMAND
    # ==========================================================

    @app_commands.command(
        name="level",
        description=(
            "View a user's Guild XP or Lunar website level."
        ),
    )
    @app_commands.describe(
        user="The user to view.",
        view="Which level system to display.",
    )
    @app_commands.choices(
        view=[
            app_commands.Choice(
                name="Guild XP",
                value="guild",
            ),
            app_commands.Choice(
                name="Lunar XP",
                value="lunar",
            ),
            app_commands.Choice(
                name="Both",
                value="both",
            ),
        ]
    )
    async def level(
        self,
        interaction: discord.Interaction,
        user: Optional[discord.Member] = None,
        view: app_commands.Choice[str] | None = None,
    ) -> None:
        member = user or interaction.user

        if not isinstance(
            member,
            discord.Member,
        ):
            await interaction.response.send_message(
                "I couldn't resolve that user.",
                ephemeral=True,
            )
            return

        selected_view = (
            view.value
            if view is not None
            else "guild"
        )

        await interaction.response.defer()

        try:
            guild_data: Optional[
                dict[str, Any]
            ] = None

            lunar_data: Optional[
                dict[str, Any]
            ] = None

            # --------------------------------------------------
            # LOAD ONLY WHAT THE SELECTED VIEW NEEDS
            # --------------------------------------------------

            if selected_view in (
                "guild",
                "both",
            ):
                guild_data = (
                    await self.get_guild_data(
                        member
                    )
                )

            if selected_view in (
                "lunar",
                "both",
            ):
                lunar_data = (
                    await self.get_lunar_data(
                        member
                    )
                )

            # --------------------------------------------------
            # GUILD
            # --------------------------------------------------

            if selected_view == "guild":
                assert guild_data is not None

                card = (
                    await render_guild_level_card(
                        self.build_guild_card_data(
                            member,
                            guild_data,
                        )
                    )
                )

                await interaction.followup.send(
                    embed=self.build_guild_embed(
                        member,
                        guild_data,
                    ),
                    file=discord.File(
                        card,
                        filename="lunar-guild-level.png",
                    ),
                )

                return

            # --------------------------------------------------
            # LUNAR
            # --------------------------------------------------

            if selected_view == "lunar":
                if lunar_data is None:
                    await interaction.followup.send(
                        (
                            "This user does not have a "
                            "verified Lunar account linked."
                        ),
                        ephemeral=True,
                    )
                    return

                card = (
                    await render_lunar_level_card(
                        self.build_lunar_card_data(
                            lunar_data
                        )
                    )
                )

                await interaction.followup.send(
                    embed=self.build_lunar_embed(
                        member,
                        lunar_data,
                    ),
                    file=discord.File(
                        card,
                        filename="lunar-website-level.png",
                    ),
                )

                return

            # --------------------------------------------------
            # BOTH
            # --------------------------------------------------

            if selected_view == "both":
                if guild_data is None:
                    await interaction.followup.send(
                        "Guild XP could not be loaded.",
                        ephemeral=True,
                    )
                    return

                if lunar_data is None:
                    await interaction.followup.send(
                        (
                            "This user has Guild XP, but "
                            "does not have a verified Lunar "
                            "account linked."
                        ),
                        ephemeral=True,
                    )
                    return

                guild_card_data = (
                    self.build_guild_card_data(
                        member,
                        guild_data,
                    )
                )

                lunar_card_data = (
                    self.build_lunar_card_data(
                        lunar_data
                    )
                )

                combined = BothLevelCardData(
                    username=member.display_name,
                    avatar_url=str(
                        member.display_avatar.url
                    ),
                    guild=guild_card_data,
                    lunar=lunar_card_data,
                )

                card = (
                    await render_both_level_card(
                        combined
                    )
                )

                embed = discord.Embed(
                    title="Lunar Progression",
                    description=(
                        f"{member.mention}'s Guild and "
                        "Lunar website progression"
                    ),
                    colour=0x7C3AED,
                )

                embed.add_field(
                    name="Guild XP",
                    value=(
                        f"Level `{guild_data['level']}`\n"
                        f"{format_xp(guild_data['current_xp'])} / "
                        f"{format_xp(guild_data['required_xp'])} XP"
                    ),
                    inline=True,
                )

                embed.add_field(
                    name="Lunar XP",
                    value=(
                        f"Level `{lunar_data['level']}`\n"
                        f"{format_xp(lunar_data['xp'])} / "
                        f"{format_xp(lunar_data['required_xp'])} XP"
                    ),
                    inline=True,
                )

                embed.set_thumbnail(
                    url=member.display_avatar.url
                )

                embed.set_footer(
                    text="Lunar • Guild + Website"
                )

                await interaction.followup.send(
                    embed=embed,
                    file=discord.File(
                        card,
                        filename="lunar-both-level.png",
                    ),
                )

                return

            await interaction.followup.send(
                "Unknown level view.",
                ephemeral=True,
            )

        except discord.HTTPException:
            log.exception(
                "Discord error while executing /level "
                "for user %s.",
                member.id,
            )

            await interaction.followup.send(
                "I couldn't display the level information.",
                ephemeral=True,
            )

        except Exception:
            log.exception(
                "Unexpected error while executing /level "
                "for user %s.",
                member.id,
            )

            await interaction.followup.send(
                "Something went wrong while loading level information.",
                ephemeral=True,
            )


async def setup(
    bot: commands.Bot,
) -> None:
    await bot.add_cog(
        Level(bot)
    )