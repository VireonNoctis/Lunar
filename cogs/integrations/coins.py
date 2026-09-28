from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any, Optional

import discord
from discord.ext import commands

from cogs.utilities.database import db
from cogs.utilities.mathematical_random import secure_rng
from cogs.utilities.xp import (
    format_coins,
    member_bonus_multiplier,
)
from cogs.utilities.lunarapi import lunarapi


log = logging.getLogger("lunar.coins")


# ============================================================
# Configuration
# ============================================================

# Fill these in once you have dedicated log/embed channels for
# coins. Left disabled (0) so nothing breaks until they're set.
COINS_LOG_CHANNEL_ID = 0
COINS_EMBED_CHANNEL_ID = 0

# ------------------------------------------------------------
# AMOUNT — how many coins a single message can award.
# ------------------------------------------------------------

MIN_MESSAGE_COINS = 1
MAX_MESSAGE_COINS = 5

# Chance (0-100) that an eligible message rolls a coin grant at
# all. Kept low relative to XP since coins are the harder/rarer
# currency.
COIN_CHANCE_THRESHOLD = 20  # roll must be > this to award coins

# ------------------------------------------------------------
# LIMIT 
# ------------------------------------------------------------

MESSAGE_COIN_COOLDOWN = 0.1  # seconds between message coin grants
DAILY_MESSAGE_COIN_LIMIT = 10000  # max coins from messages per UTC day


# ============================================================
# Coins Cog
# ============================================================

class Coins(commands.Cog):
    """
    Website coin economy.

    Mirrors the message-based Lunar XP system (cogs/integrations/xp.py):
    same account-linking rules, same "amount per grant" + "limit on
    how often/how much" shape, and the same secrets.SystemRandom-backed
    rolls used by CryptographicRandomizer/MathematicalRandomness
    (cogs/utilities/randomizer.py, cogs/utilities/mathematical_random.py)
    instead of the plain `random` module. HTTP calls go through
    cogs.utilities.lunarapi rather than rolling its own session.

    Also exposes grant_coins()/award_level_up_coins() so other cogs
    (website XP, Guild XP) can pay out level-up coin rewards through
    a single, consistent path.
    """

    def __init__(self, bot: commands.Bot):
        self.bot = bot

        # (discord_id) -> monotonic timestamp of last message grant.
        self._last_coin_at: dict[int, float] = {}

        # (discord_id) -> (utc_date_ordinal, coins_granted_today)
        self._daily_totals: dict[int, tuple[int, int]] = {}

    async def cog_load(self) -> None:
        log.info("Coins system loaded")

    # --------------------------------------------------------
    # Lunar API
    # --------------------------------------------------------

    async def grant_coins(
        self,
        lunar_uuid: str,
        amount: int,
        *,
        action: str = "add",
    ) -> Optional[dict[str, Any]]:
        """
        Give (or remove/set) coins through the Lunar admin API.

        Thin wrapper around lunarapi.set_coins() so every other
        method in this cog keeps calling `self.grant_coins(...)`
        regardless of how the underlying HTTP client works.
        """

        if amount == 0:
            return None

        return await lunarapi.set_coins(
            lunar_uuid,
            amount,
            action=action,
        )

    # --------------------------------------------------------
    # Level-up rewards (called by XP / GuildXP on level up)
    # --------------------------------------------------------

    async def award_level_up_coins(
        self,
        *,
        lunar_uuid: str,
        amount: int,
        source: str,
        username: Optional[str] = None,
    ) -> Optional[dict[str, Any]]:
        """
        Pay out a level-up coin reward and log it.

        `source` is just a label ("website_level_up" /
        "guild_level_up") for the log line below.
        """

        if amount <= 0:
            return None

        result = await self.grant_coins(
            lunar_uuid,
            amount,
            action="add",
        )

        if not result:
            log.error(
                "Failed to grant %s level-up coins to %s (%s)",
                amount,
                username or lunar_uuid,
                source,
            )
            return None

        log.info(
            "Level-up coins | user=%s | +%s coins | source=%s",
            username or lunar_uuid,
            amount,
            source,
        )

        await self._log_grant(
            username=result.get(
                "username", username or str(lunar_uuid)
            ),
            amount=amount,
            reason=f"level up ({source})",
        )

        return result

    # --------------------------------------------------------
    # Cross-cog helper: award by Discord ID
    # --------------------------------------------------------

    async def grant_coins_to_discord_user(
        self,
        discord_id: int,
        amount: int,
        *,
        source: str = "manual",
    ) -> Optional[dict[str, Any]]:
        """
        Resolve a Discord ID to a linked/verified Lunar account and
        grant coins to it. Used by systems (like Guild XP) that
        only know the Discord side of the account.
        """

        account = await db.account_links.get(discord_id)

        if account is None or not account.verified:
            return None

        lunar_uuid = getattr(account, "lunar_uuid", None)

        if lunar_uuid is None:
            return None

        return await self.award_level_up_coins(
            lunar_uuid=str(lunar_uuid),
            amount=amount,
            source=source,
        )

    # --------------------------------------------------------
    # Logging
    # --------------------------------------------------------

    async def _log_grant(
        self,
        *,
        username: str,
        amount: int,
        reason: str,
    ) -> None:
        guild = discord.utils.find(
            lambda g: g.get_channel(COINS_LOG_CHANNEL_ID)
            is not None,
            self.bot.guilds,
        )

        channel = (
            guild.get_channel(COINS_LOG_CHANNEL_ID)
            if guild
            else None
        )

        if isinstance(channel, discord.TextChannel):
            try:
                await channel.send(
                    f"Gave coins to `{username}` "
                    f"amount `+{format_coins(amount)}` "
                    f"({reason})"
                )
            except discord.HTTPException:
                log.exception("Failed to send coins log message")

    # --------------------------------------------------------
    # Limit helpers (amount + cooldown + daily cap)
    # --------------------------------------------------------

    def _daily_remaining(
        self,
        discord_id: int,
    ) -> int:
        today = datetime.now(timezone.utc).toordinal()

        day, granted = self._daily_totals.get(
            discord_id, (today, 0)
        )

        if day != today:
            granted = 0

        return max(0, DAILY_MESSAGE_COIN_LIMIT - granted)

    def _record_daily_grant(
        self,
        discord_id: int,
        amount: int,
    ) -> None:
        today = datetime.now(timezone.utc).toordinal()

        day, granted = self._daily_totals.get(
            discord_id, (today, 0)
        )

        if day != today:
            granted = 0

        self._daily_totals[discord_id] = (
            today,
            granted + amount,
        )

    # --------------------------------------------------------
    # Message-based coin grant
    # --------------------------------------------------------

    async def process_message(
        self,
        message: discord.Message,
    ) -> None:
        """Roll for, and potentially grant, coins for a message."""

        if not message.guild:
            return

        content = (message.content or "").strip()

        # Extremely short messages never qualify (same floor as
        # the website XP system's spam guard).
        if len(content) < 4:
            return

        account = await db.account_links.get(message.author.id)

        if account is None or not account.verified:
            return

        lunar_uuid = account.lunar_uuid

        if lunar_uuid is None:
            return

        discord_id = message.author.id

        # ----------------------------------------------------
        # LIMIT — cooldown
        # ----------------------------------------------------

        now = time.monotonic()

        last_grant = self._last_coin_at.get(discord_id)

        if (
            last_grant is not None
            and (now - last_grant) < MESSAGE_COIN_COOLDOWN
        ):
            return

        # ----------------------------------------------------
        # LIMIT — daily cap
        # ----------------------------------------------------

        remaining_today = self._daily_remaining(discord_id)

        if remaining_today <= 0:
            return

        # ----------------------------------------------------
        # AMOUNT — chance roll + random amount in range
        #
        # Both rolls come from secure_rng (secrets.SystemRandom,
        # OS CSPRNG) rather than the plain `random` module — the
        # same entropy source CryptographicRandomizer and
        # MathematicalRandomness use elsewhere in the bot.
        # ----------------------------------------------------

        chance = secure_rng.random() * 100

        if chance <= COIN_CHANCE_THRESHOLD:
            return

        amount = secure_rng.randint(
            MIN_MESSAGE_COINS,
            MAX_MESSAGE_COINS,
        )

        amount = int(
            amount
            * member_bonus_multiplier(message.author)
        )

        amount = min(amount, remaining_today)

        if amount <= 0:
            return

        # ----------------------------------------------------
        # GRANT
        # ----------------------------------------------------

        result = await self.grant_coins(
            str(lunar_uuid),
            amount,
            action="add",
        )

        if not result:
            return

        # Only mark the cooldown/daily usage once the grant has
        # actually succeeded against the API.
        self._last_coin_at[discord_id] = now
        self._record_daily_grant(discord_id, amount)

        username = result.get("username", str(lunar_uuid))
        new_coins = result.get("new_coins", "?")

        log.info(
            "Coins granted | user=%s | +%s | new_total=%s",
            username,
            amount,
            new_coins,
        )

        embed = discord.Embed(
            color=0xF5C518,
            description=(
                f"🪙 **{username}** earned "
                f"**+{format_coins(amount)} coins**"
            ),
        )

        if self.bot.user:
            embed.set_author(
                name="🌙 Lunar Coins",
                icon_url=self.bot.user.display_avatar.url,
            )

        embed.set_footer(text="☾ Lunar Coins")
        embed.timestamp = discord.utils.utcnow()

        embed_channel = message.guild.get_channel(
            COINS_EMBED_CHANNEL_ID
        )

        if isinstance(embed_channel, discord.TextChannel):
            try:
                await embed_channel.send(embed=embed)
            except discord.HTTPException:
                log.exception("Failed to send coins embed")

    # --------------------------------------------------------
    # Message Listener
    # --------------------------------------------------------

    @commands.Cog.listener()
    async def on_message(
        self,
        message: discord.Message,
    ) -> None:
        if message.author.bot:
            return

        try:
            await self.process_message(message)

        except Exception:
            log.exception(
                "Unhandled coins processing error for message %s",
                message.id,
            )

        # No process_commands() call here on purpose — the XP cog
        # already owns that responsibility for on_message. Adding
        # a second call here would run every command twice.


# ============================================================
# Cog Setup
# ============================================================

async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(
        Coins(bot)
    )

    # --------------------------------------------------------
    # Level-up rewards (called by XP / GuildXP on level up)
    # --------------------------------------------------------

    async def award_level_up_coins(
        self,
        *,
        lunar_uuid: str,
        amount: int,
        source: str,
        username: Optional[str] = None,
    ) -> Optional[dict[str, Any]]:
        """
        Pay out a level-up coin reward and log it.

        `source` is just a label ("website_level_up" /
        "guild_level_up") for the log line below.
        """

        if amount <= 0:
            return None

        result = await self.grant_coins(
            lunar_uuid,
            amount,
            action="add",
        )

        if not result:
            log.error(
                "Failed to grant %s level-up coins to %s (%s)",
                amount,
                username or lunar_uuid,
                source,
            )
            return None

        log.info(
            "Level-up coins | user=%s | +%s coins | source=%s",
            username or lunar_uuid,
            amount,
            source,
        )

        await self._log_grant(
            username=result.get(
                "username", username or str(lunar_uuid)
            ),
            amount=amount,
            reason=f"level up ({source})",
        )

        return result

    # --------------------------------------------------------
    # Cross-cog helper: award by Discord ID
    # --------------------------------------------------------

    async def grant_coins_to_discord_user(
        self,
        discord_id: int,
        amount: int,
        *,
        source: str = "manual",
    ) -> Optional[dict[str, Any]]:
        """
        Resolve a Discord ID to a linked/verified Lunar account and
        grant coins to it. Used by systems (like Guild XP) that
        only know the Discord side of the account.
        """

        account = await db.account_links.get(discord_id)

        if account is None or not account.verified:
            return None

        lunar_uuid = getattr(account, "lunar_uuid", None)

        if lunar_uuid is None:
            return None

        return await self.award_level_up_coins(
            lunar_uuid=str(lunar_uuid),
            amount=amount,
            source=source,
        )

    # --------------------------------------------------------
    # Logging
    # --------------------------------------------------------

    async def _log_grant(
        self,
        *,
        username: str,
        amount: int,
        reason: str,
    ) -> None:
        guild = discord.utils.find(
            lambda g: g.get_channel(COINS_LOG_CHANNEL_ID)
            is not None,
            self.bot.guilds,
        )

        channel = (
            guild.get_channel(COINS_LOG_CHANNEL_ID)
            if guild
            else None
        )

        if isinstance(channel, discord.TextChannel):
            try:
                await channel.send(
                    f"Gave coins to `{username}` "
                    f"amount `+{format_coins(amount)}` "
                    f"({reason})"
                )
            except discord.HTTPException:
                log.exception("Failed to send coins log message")

    # --------------------------------------------------------
    # Limit helpers (amount + cooldown + daily cap)
    # --------------------------------------------------------

    def _daily_remaining(
        self,
        discord_id: int,
    ) -> int:
        today = datetime.now(timezone.utc).toordinal()

        day, granted = self._daily_totals.get(
            discord_id, (today, 0)
        )

        if day != today:
            granted = 0

        return max(0, DAILY_MESSAGE_COIN_LIMIT - granted)

    def _record_daily_grant(
        self,
        discord_id: int,
        amount: int,
    ) -> None:
        today = datetime.now(timezone.utc).toordinal()

        day, granted = self._daily_totals.get(
            discord_id, (today, 0)
        )

        if day != today:
            granted = 0

        self._daily_totals[discord_id] = (
            today,
            granted + amount,
        )

    # --------------------------------------------------------
    # Message-based coin grant
    # --------------------------------------------------------

    async def process_message(
        self,
        message: discord.Message,
    ) -> None:
        """Roll for, and potentially grant, coins for a message."""

        if not message.guild:
            return

        content = (message.content or "").strip()

        # Extremely short messages never qualify (same floor as
        # the website XP system's spam guard).
        if len(content) < 4:
            return

        account = await db.account_links.get(message.author.id)

        if account is None or not account.verified:
            return

        lunar_uuid = account.lunar_uuid

        if lunar_uuid is None:
            return

        discord_id = message.author.id

        # ----------------------------------------------------
        # LIMIT — cooldown
        # ----------------------------------------------------

        now = time.monotonic()

        last_grant = self._last_coin_at.get(discord_id)

        if (
            last_grant is not None
            and (now - last_grant) < MESSAGE_COIN_COOLDOWN
        ):
            return

        # ----------------------------------------------------
        # LIMIT — daily cap
        # ----------------------------------------------------

        remaining_today = self._daily_remaining(discord_id)

        if remaining_today <= 0:
            return

        # ----------------------------------------------------
        # AMOUNT — chance roll + random amount in range
        # ----------------------------------------------------

        chance = random.random() * 100

        if chance <= COIN_CHANCE_THRESHOLD:
            return

        amount = random.randint(
            MIN_MESSAGE_COINS,
            MAX_MESSAGE_COINS,
        )

        amount = int(
            amount
            * member_bonus_multiplier(message.author)
        )

        amount = min(amount, remaining_today)

        if amount <= 0:
            return

        # ----------------------------------------------------
        # GRANT
        # ----------------------------------------------------

        result = await self.grant_coins(
            str(lunar_uuid),
            amount,
            action="add",
        )

        if not result:
            return

        # Only mark the cooldown/daily usage once the grant has
        # actually succeeded against the API.
        self._last_coin_at[discord_id] = now
        self._record_daily_grant(discord_id, amount)

        username = result.get("username", str(lunar_uuid))
        new_coins = result.get("new_coins", "?")

        log.info(
            "Coins granted | user=%s | +%s | new_total=%s",
            username,
            amount,
            new_coins,
        )

        embed = discord.Embed(
            color=0xF5C518,
            description=(
                f"🪙 **{username}** earned "
                f"**+{format_coins(amount)} coins**"
            ),
        )

        if self.bot.user:
            embed.set_author(
                name="🌙 Lunar Coins",
                icon_url=self.bot.user.display_avatar.url,
            )

        embed.set_footer(text="☾ Lunar Coins")
        embed.timestamp = discord.utils.utcnow()

        embed_channel = message.guild.get_channel(
            COINS_EMBED_CHANNEL_ID
        )

        if isinstance(embed_channel, discord.TextChannel):
            try:
                await embed_channel.send(embed=embed)
            except discord.HTTPException:
                log.exception("Failed to send coins embed")

    # --------------------------------------------------------
    # Message Listener
    # --------------------------------------------------------

    @commands.Cog.listener()
    async def on_message(
        self,
        message: discord.Message,
    ) -> None:
        if message.author.bot:
            return

        try:
            await self.process_message(message)

        except Exception:
            log.exception(
                "Unhandled coins processing error for message %s",
                message.id,
            )

        # No process_commands() call here on purpose — the XP cog
        # already owns that responsibility for on_message. Adding
        # a second call here would run every command twice.


# ============================================================
# Cog Setup
# ============================================================

async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(
        Coins(bot)
    )
