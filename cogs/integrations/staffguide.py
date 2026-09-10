from __future__ import annotations

import logging
from typing import Optional

import discord
from discord.ext import commands

from cogs.utilities.emoji import EMOJI


log = logging.getLogger("lunar.staffguide")


# ============================================================
# CONFIG
# ============================================================

STAFF_ROLES: set[int] = {
    1367458664654307348,

}


# Forum channel containing the staff guides.
STAFF_GUIDE_FORUM_ID = 1542949992854192258


# Channel where the bot should mention users when their DMs
# are disabled/unavailable.
STAFF_GUIDE_FALLBACK_CHANNEL_ID = 1367458977318834256


# ============================================================
# STAFF GUIDE INTEGRATION
# ============================================================

class StaffGuideIntegration(
    commands.Cog
):

    def __init__(
        self,
        bot: commands.Bot,
    ) -> None:

        self.bot = bot

        # Prevent duplicate notifications if Discord sends
        # multiple role update events very close together.
        self._notified_roles: dict[
            int,
            set[int],
        ] = {}

    # ========================================================
    # HELPERS
    # ========================================================

    def get_forum(
        self,
    ) -> Optional[
        discord.ForumChannel
    ]:

        channel = self.bot.get_channel(
            STAFF_GUIDE_FORUM_ID
        )

        if isinstance(
            channel,
            discord.ForumChannel,
        ):

            return channel

        return None

    def get_fallback_channel(
        self,
    ) -> Optional[
        discord.TextChannel
    ]:

        channel = self.bot.get_channel(
            STAFF_GUIDE_FALLBACK_CHANNEL_ID
        )

        if isinstance(
            channel,
            discord.TextChannel,
        ):

            return channel

        return None

    def get_added_roles(
        self,
        before: discord.Member,
        after: discord.Member,
    ) -> list[discord.Role]:

        before_roles = {
            role.id
            for role in before.roles
        }

        added_roles = [
            role
            for role in after.roles
            if role.id not in before_roles
        ]

        return [
            role
            for role in added_roles
            if role.id in STAFF_ROLES
        ]

    def already_notified(
        self,
        user_id: int,
        role_id: int,
    ) -> bool:

        return role_id in (
            self._notified_roles.get(
                user_id,
                set()
            )
        )

    def mark_notified(
        self,
        user_id: int,
        role_id: int,
    ) -> None:

        self._notified_roles.setdefault(
            user_id,
            set()
        ).add(
            role_id
        )

    def build_dm_embed(
        self,
        member: discord.Member,
        roles: list[discord.Role],
        forum: Optional[
            discord.ForumChannel
        ],
    ) -> discord.Embed:

        role_text = ", ".join(
            role.mention
            for role in roles
        )

        if forum is not None:

            forum_text = (
                f"{forum.mention}"
            )

        else:

            forum_text = (
                "the **Staff Guides** forum"
            )

        embed = discord.Embed(
            title=(
                f"{EMOJI['staff']} "
                "Staff Guide Notification"
            ),
            description=(
                f"Hello **{member.display_name}**.\n\n"
                f"You have been given the following staff "
                f"role(s): {role_text}\n\n"
                f"{EMOJI['approved']} "
                "Please make sure you check the "
                f"{forum_text} and read the relevant "
                "**staff guides** before carrying out "
                "staff duties.\n\n"
                "These guides contain important information "
                "about procedures, commands, moderation, "
                "and your responsibilities as staff."
            ),
            color=0x7C5CFF,
        )

        embed.set_thumbnail(
            url=member.display_avatar.url
        )

        embed.set_footer(
            text="Lunar Staff System"
        )

        return embed

    def build_fallback_message(
        self,
        member: discord.Member,
        roles: list[discord.Role],
        forum: Optional[
            discord.ForumChannel
        ],
    ) -> str:

        role_text = ", ".join(
            role.mention
            for role in roles
        )

        if forum is not None:

            forum_text = (
                forum.mention
            )

        else:

            forum_text = (
                "**Staff Guides forum**"
            )

        return (
            f"{EMOJI['staff']} "
            f"{member.mention} You have been given "
            f"{role_text}.\n\n"
            f"Please check the {forum_text} and read "
            "**all relevant staff guides**.\n\n"
            "I attempted to send you this information "
            "through DM, but your DMs appear to be disabled."
        )

    # ========================================================
    # ROLE UPDATE LISTENER
    # ========================================================

    @commands.Cog.listener()
    async def on_member_update(
        self,
        before: discord.Member,
        after: discord.Member,
    ) -> None:

        # ----------------------------------------------------
        # Ignore Bots
        # ----------------------------------------------------

        if after.bot:
            return

        # ----------------------------------------------------
        # Find Newly Added Staff Roles
        # ----------------------------------------------------

        added_roles = self.get_added_roles(
            before,
            after,
        )

        if not added_roles:
            return

        # ----------------------------------------------------
        # Ignore Repeated Events
        # ----------------------------------------------------

        new_roles = [
            role
            for role in added_roles
            if not self.already_notified(
                after.id,
                role.id,
            )
        ]

        if not new_roles:
            return

        # ----------------------------------------------------
        # Forum
        # ----------------------------------------------------

        forum = self.get_forum()

        # ----------------------------------------------------
        # Send DM
        # ----------------------------------------------------

        try:

            await after.send(
                embed=self.build_dm_embed(
                    after,
                    new_roles,
                    forum,
                )
            )

            dm_sent = True

        except discord.Forbidden:

            dm_sent = False

        except discord.HTTPException:

            log.exception(
                "Failed sending Staff Guide DM to %s.",
                after.id,
            )

            dm_sent = False

        # ----------------------------------------------------
        # Fallback Channel
        # ----------------------------------------------------

        if not dm_sent:

            fallback_channel = (
                self.get_fallback_channel()
            )

            if fallback_channel is not None:

                try:

                    await fallback_channel.send(
                        self.build_fallback_message(
                            after,
                            new_roles,
                            forum,
                        ),
                        allowed_mentions=(
                            discord.AllowedMentions(
                                users=True
                            )
                        ),
                    )

                except discord.Forbidden:

                    log.error(
                        "No permission to send Staff Guide "
                        "fallback message in channel %s.",
                        fallback_channel.id,
                    )

                except discord.HTTPException:

                    log.exception(
                        "Failed sending Staff Guide fallback "
                        "message for %s.",
                        after.id,
                    )

        # ----------------------------------------------------
        # Mark Roles As Notified
        # ----------------------------------------------------

        for role in new_roles:

            self.mark_notified(
                after.id,
                role.id,
            )

    # ========================================================
    # CLEANUP
    # ========================================================

    @commands.Cog.listener()
    async def on_member_remove(
        self,
        member: discord.Member,
    ) -> None:

        self._notified_roles.pop(
            member.id,
            None,
        )


# ============================================================
# SETUP
# ============================================================

async def setup(
    bot: commands.Bot,
) -> None:

    await bot.add_cog(
        StaffGuideIntegration(bot)
    )
