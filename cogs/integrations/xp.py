import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
import discord
from discord.ext import commands

from cogs.utilities.database import db
from cogs.utilities.mathematical_random import secure_rng
from cogs.utilities.xp import (
    coins_for_level_range,
    member_bonus_multiplier,
)
from cogs.utilities.lunarapi import lunarapi


log = logging.getLogger("lunar.xp")


# ============================================================
# Configuration
# ============================================================

LUNAR_PROFILE_ENDPOINT = "/api/animes/profile"
XP_LOG_CHANNEL_ID = 1499281835757404250
XP_EMBED_CHANNEL_ID = 1514345477188092024


# ============================================================
# XP Cog
# ============================================================

class XP(commands.Cog):
    """
    Message-based Lunar XP system.

    HTTP calls go through cogs.utilities.lunarapi (shared session,
    shared auth) instead of managing its own aiohttp.ClientSession.
    """

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self) -> None:
        log.info("XP system loaded")

    # --------------------------------------------------------
    # Lunar API
    # --------------------------------------------------------

    async def grant_xp(
        self,
        lunar_uuid: str,
        amount: int,
    ) -> Optional[dict[str, Any]]:
        """
        Give XP through the Lunar API.

        This replaces the separate grantXP.ts file.
        """

        if amount < 0:
            return None

        return await lunarapi.give_xp(
            lunar_uuid,
            amount,
        )

    async def get_lunar_profile(
        self,
        lunar_username: str,
    ) -> Optional[dict[str, Any]]:
        """
        Fetch the authoritative Lunar website profile.

        Lunar remains the source of truth for:
        - level
        - XP
        - XP required for the next level

        The Discord bot does not store or calculate these values.
        """

        if not lunar_username:
            return None

        try:
            payload = await lunarapi.get(
                LUNAR_PROFILE_ENDPOINT,
                authed=False,
                params={
                    "username": str(lunar_username),
                },
            )

        except lunarapi.LunarAPIError:
            log.exception(
                "Lunar profile request failed for username=%s",
                lunar_username,
            )
            return None
            return None

        data = payload.get("data")

        if not isinstance(data, dict):
            log.error(
                "Lunar profile response is missing data "
                "for username=%s",
                lunar_username,
            )
            return None

        try:
            level = int(
                data.get(
                    "level",
                    0,
                )
            )

            xp = int(
                data.get(
                    "xp",
                    0,
                )
            )

            xp_required = int(
                data.get(
                    "xp_required_for_next_level",
                    0,
                )
            )

        except (
            TypeError,
            ValueError,
        ):
            log.error(
                "Invalid XP values in Lunar profile "
                "for username=%s",
                lunar_username,
            )
            return None

        return {
            "username": data.get(
                "username",
                lunar_username,
            ),
            "lunar_uuid": data.get(
                "user_id"
            ),
            "level": level,
            "xp": xp,
            "required_xp": xp_required,
            "avatar_url": data.get(
                "avatar_url"
            ),
            "banner": data.get(
                "banner"
            ),
            "title": data.get(
                "title"
            ),
        }

    # --------------------------------------------------------
    # Database
    # --------------------------------------------------------

    async def update_last_message_time(
        self,
        discord_id: int,
    ) -> None:
        """
        Update account_links.last_message_time through database.py.

        account_links uses snowflake_id as its primary key, so this
        is a direct single-row update.
        """

        await db.execute(
            """
            UPDATE account_links
            SET last_message_time = %s
            WHERE snowflake_id = %s
            """,
            (
                datetime.now(timezone.utc),
                str(discord_id),
            ),
        )

    # --------------------------------------------------------
    # Main XP calculation
    # --------------------------------------------------------

    async def process_message(self, message: discord.Message) -> None:
        """Calculate and potentially grant XP for a message."""

        if not message.guild:
            return

        # ----------------------------------------------------
        # Account lookup through database.py
        # ----------------------------------------------------

        account = await db.account_links.get(message.author.id)

        if account is None:
            return

        if not account.verified:
            return

        lunar_uuid = account.lunar_uuid

        if lunar_uuid is None:
            return

        # ----------------------------------------------------
        # Basic values
        # ----------------------------------------------------

        content = message.content or ""
        content_length = len(content)

        chance = secure_rng.random() * 100
        penalty = 1.0

        # ----------------------------------------------------
        # Message history
        # ----------------------------------------------------

        previous_message: Optional[discord.Message] = None

        try:
            messages = [
                msg
                async for msg in message.channel.history(
                    limit=2
                )
                if msg.id != message.id
            ]

            if messages:
                previous_message = messages[0]

        except (discord.Forbidden, discord.HTTPException):
            previous_message = None

        if previous_message:

            # Same exact message.
            if content == previous_message.content:
                penalty -= 0.9

                log.debug(
                    "XP penalty reduction: same message -> %.2f",
                    penalty,
                )

            # Similar beginning.
            if (
                previous_message.content
                and content.startswith(previous_message.content)
            ):
                penalty -= 0.3

                log.debug(
                    "XP penalty reduction: similar start -> %.2f",
                    penalty,
                )

            # Same sender.
            if message.author.id == previous_message.author.id:
                penalty -= 0.1

                log.debug(
                    "XP penalty reduction: same sender -> %.2f",
                    penalty,
                )

        if content_length > 1000:
            penalty -= 0.4

            log.debug(
                "XP penalty reduction: >1000 chars -> %.2f",
                penalty,
            )

        elif content_length > 500:
            penalty -= 0.2

            log.debug(
                "XP penalty reduction: >500 chars -> %.2f",
                penalty,
            )

        # ----------------------------------------------------
        # Time since previous XP message
        # ----------------------------------------------------

        now = datetime.now(timezone.utc)

        last_message_time = getattr(
            account,
            "last_message_time",
            None,
        )

        if last_message_time is None:
            last_message_time = now - timedelta(seconds=10)

        # Cassandra normally returns a datetime.
        if last_message_time.tzinfo is None:
            last_message_time = last_message_time.replace(
                tzinfo=timezone.utc
            )

        time_since_last_message = (
            now - last_message_time
        ).total_seconds()

        if time_since_last_message < 1:
            penalty -= 0.3

            log.debug(
                "XP penalty reduction: <1s -> %.2f",
                penalty,
            )

        elif time_since_last_message < 5:
            penalty -= 0.2

            log.debug(
                "XP penalty reduction: <5s -> %.2f",
                penalty,
            )

        elif time_since_last_message < 10:
            penalty -= 0.1

            log.debug(
                "XP penalty reduction: <10s -> %.2f",
                penalty,
            )

        elif time_since_last_message > 30:
            penalty += 0.1

            log.debug(
                "XP bonus: >30s -> %.2f",
                penalty,
            )

        # ----------------------------------------------------
        # Guild member information
        # ----------------------------------------------------

        guild_member = message.guild.get_member(
            message.author.id
        )

        if guild_member is None:
            return

        if guild_member.joined_at is None:
            return

        joined_at = guild_member.joined_at

        if joined_at.tzinfo is None:
            joined_at = joined_at.replace(
                tzinfo=timezone.utc
            )

        account_age = now - joined_at

        if account_age < timedelta(days=7):
            penalty += 0.2

            log.debug(
                "XP bonus: member joined within first week -> %.2f",
                penalty,
            )

        # ----------------------------------------------------
        # Basic validation
        # ----------------------------------------------------

        if content_length < 0:
            return

        # Prevent negative/zero XP after penalties.
        if penalty <= 0:
            return

        if chance > 75:
            multiplier = 1.50

        elif chance > 50:
            multiplier = 1.25

        else:
            return

        amount = int(
            (content_length / 10)
            * multiplier
            * penalty
            * member_bonus_multiplier(guild_member)
        )

        if amount <= 0:
            return

        # ----------------------------------------------------
        # Final XP grant
        # ----------------------------------------------------

        await self.grant_xp_to_user(
            message=message,
            account=account,
            amount=amount,
            chance=chance,
            penalty=penalty,
            time_since_last_message=time_since_last_message,
        )

    # --------------------------------------------------------
    # Final XP grant
    # --------------------------------------------------------

    async def grant_xp_to_user(
        self,
        message: discord.Message,
        account: Any,
        amount: int,
        chance: float,
        penalty: float,
        time_since_last_message: float,
    ) -> None:

        if amount <= 0:
            return

        lunar_uuid = account.lunar_uuid

        # ----------------------------------------------------
        # Save message time BEFORE API call.
        # ----------------------------------------------------

        try:
            await self.update_last_message_time(
                message.author.id
            )

        except Exception:
            log.exception(
                "Failed to update last_message_time for %s",
                message.author.id,
            )

        # ----------------------------------------------------
        # Logging
        # ----------------------------------------------------

        log.info(
            "XP calculation | user=%s | chance=%.2f | "
            "message_length=%s | amount=%s | penalty=%.2f | "
            "time_since_last=%.2fs",
            lunar_uuid,
            chance,
            len(message.content or ""),
            amount,
            penalty,
            time_since_last_message,
        )

        # ----------------------------------------------------
        # Lunar API
        # ----------------------------------------------------

        xp_result = await self.grant_xp(
            str(lunar_uuid),
            amount,
        )

        if not xp_result:
            return

        username = xp_result.get(
            "username",
            str(lunar_uuid),
        )

        xp_granted = int(
            xp_result.get(
                "xp_granted",
                amount,
            )
        )

        new_level = xp_result.get(
            "new_level",
            "?",
        )

        new_xp = xp_result.get(
            "new_xp",
            "?",
        )

        previous_level = xp_result.get(
            "previous_level",
            "?",
        )

        leveled_up = bool(
            xp_result.get(
                "leveled_up",
                False,
            )
        )

        # ----------------------------------------------------
        # Level-up coin reward
        # ----------------------------------------------------

        coins_awarded = 0

        if leveled_up:
            try:
                previous_level_int = int(previous_level)
                new_level_int = int(new_level)

            except (TypeError, ValueError):
                previous_level_int = None
                new_level_int = None

            if (
                previous_level_int is not None
                and new_level_int is not None
            ):
                coins_awarded = coins_for_level_range(
                    previous_level_int,
                    new_level_int,
                )

                if isinstance(
                    message.author,
                    discord.Member,
                ):
                    coins_awarded = int(
                        coins_awarded
                        * member_bonus_multiplier(
                            message.author
                        )
                    )

            coins_cog = self.bot.get_cog("Coins")

            if coins_awarded > 0 and coins_cog is not None:
                await coins_cog.award_level_up_coins(
                    lunar_uuid=str(lunar_uuid),
                    amount=coins_awarded,
                    source="website_level_up",
                    username=username,
                )

            elif coins_awarded > 0:
                log.warning(
                    "Coins cog not loaded; skipped %s "
                    "level-up coins for %s",
                    coins_awarded,
                    username,
                )

        # ----------------------------------------------------
        # Channel logging
        # ----------------------------------------------------

        xp_log_channel = message.guild.get_channel(
            XP_LOG_CHANNEL_ID
        )

        if isinstance(
            xp_log_channel,
            discord.TextChannel,
        ):
            try:
                await xp_log_channel.send(
                    f"Gave xp to `{lunar_uuid}` "
                    f"aka `{username}` "
                    f"xp given `{xp_granted}`"
                )
            except discord.HTTPException:
                log.exception(
                    "Failed to send XP log message"
                )
        # ----------------------------------------------------
        # Embed
        # ----------------------------------------------------

        embed = discord.Embed(
            color=0x7C5CFF,
            description=(
                f"<a:65270roseblooming:1369250407225884672> "
                f"**{username}** earned **+{xp_granted} XP**"
            ),
        )

        if self.bot.user:
            embed.set_author(
                name=" Lunar XP",
                icon_url=self.bot.user.display_avatar.url,
            )

        embed.add_field(
            name="<a:59120white:1369250400401620992> Level",
            value=f"**{new_level}**",
            inline=True,
        )

        embed.add_field(
            name="<a:59586leftwing:1369250402834583693> Current XP",
            value=f"**{new_xp}**",
            inline=True,
        )

        if leveled_up:
            embed.add_field(
                name="<a:72687pink:1369250415971012689> Level Up!",
                value=f":97637pink: **{previous_level}** → **{new_level}**",
                inline=False,
            )

            if coins_awarded > 0:
                embed.add_field(
                    name="🪙 Level-Up Bonus",
                    value=f"**+{coins_awarded:,} coins**",
                    inline=False,
                )

        embed.set_footer(text="☾ Lunar XP")
        embed.timestamp = discord.utils.utcnow()
        # ----------------------------------------------------
        # Send XP embed
        # ----------------------------------------------------

        xp_embed_channel = message.guild.get_channel(
            XP_EMBED_CHANNEL_ID
        )

        if isinstance(
            xp_embed_channel,
            discord.TextChannel,
        ):
            try:
                await xp_embed_channel.send(
                    embed=embed
                )
            except discord.HTTPException:
                log.exception(
                    "Failed to send XP embed"
                )

    # --------------------------------------------------------
    # Message Listener
    # --------------------------------------------------------

    @commands.Cog.listener()
    async def on_message(
        self,
        message: discord.Message,
    ) -> None:
        # Ignore bot messages.
        if message.author.bot:
            return

        try:
            await self.process_message(message)

        except Exception:
            log.exception(
                "Unhandled XP processing error for message %s",
                message.id,
            )

        # Important:
        # Since this cog implements on_message, prefix commands
        # otherwise stop being processed unless this is called.
        await self.bot.process_commands(message)


# ============================================================
# Cog Setup
# ============================================================

async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(
        XP(bot)
    )
