from __future__ import annotations

import logging
from typing import Optional

import discord

from cogs.utilities.emoji import EMOJI
from cogs.utilities.xp import (
    format_xp,
    level_progress_bar,
)


log = logging.getLogger("lunar.xp_announcement")


class XPAnnouncement:
    """
    Handles Guild XP level-up announcements.

    XP calculation and database updates belong to GuildXP.
    This class is presentation-only.
    """

    # Set this to the Discord channel where level-ups should be sent.
 
    ANNOUNCEMENT_CHANNEL_ID = 0

    EMBED_COLOR = 0x7C3AED

    PROGRESS_BAR_LENGTH = 18

    def __init__(
        self,
        bot: discord.Client,
    ):
        self.bot = bot

    # ==============================================================
    # CHANNEL
    # ==============================================================

    def get_channel(
        self,
    ) -> Optional[discord.abc.Messageable]:
        """
        Resolve the configured announcement channel.
        """

        if not self.ANNOUNCEMENT_CHANNEL_ID:
            return None

        channel = self.bot.get_channel(
            self.ANNOUNCEMENT_CHANNEL_ID
        )

        if isinstance(
            channel,
            discord.abc.Messageable,
        ):
            return channel

        return None

    # ==============================================================
    # EMBED
    # ==============================================================

    def build_embed(
        self,
        member: discord.Member,
        *,
        level: int,
        previous_level: int,
        current_xp: int,
        required_xp: int,
        total_xp: int,
    ) -> discord.Embed:
        """
        Build the Lunar-styled level-up embed.
        """

        progress_bar = level_progress_bar(
            current_xp,
            required_xp,
            length=self.PROGRESS_BAR_LENGTH,
        )

        level_difference = max(
            1,
            level - previous_level,
        )

        if level_difference == 1:
            title = "Level Up"
            description = (
                f"{member.mention} reached "
                f"**Level {level}**."
            )
        else:
            title = "Multiple Levels Gained"
            description = (
                f"{member.mention} advanced "
                f"**{level_difference} levels** "
                f"and reached **Level {level}**."
            )

        embed = discord.Embed(
            title=title,
            description=description,
            colour=self.EMBED_COLOR,
        )

        embed.add_field(
            name="Level",
            value=(
                f"`{previous_level}` → "
                f"`{level}`"
            ),
            inline=True,
        )

        embed.add_field(
            name="XP",
            value=(
                f"`{format_xp(current_xp)}` / "
                f"`{format_xp(required_xp)}`"
            ),
            inline=True,
        )

        embed.add_field(
            name="Total XP",
            value=(
                f"`{format_xp(total_xp)}`"
            ),
            inline=True,
        )

        embed.add_field(
            name="Progress",
            value=(
                f"`{progress_bar}`\n"
                f"{format_xp(current_xp)} / "
                f"{format_xp(required_xp)} XP"
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

    # ==============================================================
    # SEND
    # ==============================================================

    async def announce(
        self,
        member: discord.Member,
        *,
        level: int,
        previous_level: int,
        current_xp: int,
        required_xp: int,
        total_xp: int,
    ) -> Optional[discord.Message]:
        """
        Send a level-up announcement.

        Returns the created Discord message, or None when
        announcements are disabled/unavailable.
        """

        channel = self.get_channel()

        if channel is None:
            return None

        embed = self.build_embed(
            member,
            level=level,
            previous_level=previous_level,
            current_xp=current_xp,
            required_xp=required_xp,
            total_xp=total_xp,
        )

        try:
            return await channel.send(
                embed=embed
            )

        except discord.Forbidden:
            log.error(
                (
                    "Cannot send Guild XP level-up "
                    "announcement to channel %s."
                ),
                self.ANNOUNCEMENT_CHANNEL_ID,
            )

        except discord.HTTPException:
            log.exception(
                "Failed to send Guild XP level-up announcement."
            )

        except Exception:
            log.exception(
                "Unexpected Guild XP announcement error."
            )

        return None

    # ==============================================================
    # RESULT HANDLER
    # ==============================================================

    async def handle_result(
        self,
        member: discord.Member,
        result: Optional[dict],
    ) -> Optional[discord.Message]:
        """
        Handle a result returned by GuildXP.process_message()
        or GuildXP.award_xp().
        """

        if not result:
            return None

        if not result.get(
            "leveled_up",
            False,
        ):
            return None

        return await self.announce(
            member,
            level=int(
                result.get(
                    "level",
                    1,
                )
            ),
            previous_level=int(
                result.get(
                    "previous_level",
                    1,
                )
            ),
            current_xp=int(
                result.get(
                    "current_level_xp",
                    result.get(
                        "xp",
                        0,
                    ),
                )
            ),
            required_xp=int(
                result.get(
                    "required_xp",
                    0,
                )
            ),
            total_xp=int(
                result.get(
                    "xp",
                    0,
                )
            ),
        )