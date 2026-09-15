from __future__ import annotations

import logging
import math
import re
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Optional

import discord
from discord.ext import commands

from cogs.utilities.database import db


log = logging.getLogger("lunar.guild_xp")


class GuildXP(commands.Cog):
    """
    Independent Discord guild XP system.

    This XP is NOT Lunar website XP.
    It is stored entirely in the bot's guild_xp tables.
    """

    BASE_XP = 8

    # Harder progression as levels increase.
    BASE_REQUIRED_XP = 250
    LEVEL_GROWTH = 1.28

    # Anti-spam.
    MIN_COOLDOWN = 0.5

    # Message history used for duplicate/similarity detection.
    HISTORY_SIZE = 8

    # Maximum amount of raw XP a single message can produce.
    MAX_MESSAGE_XP = 150

    # User IDs can be given permanent exceptions later.
    XP_EXEMPT_USER_IDS: set[int] = set()

    def __init__(self, bot: commands.Bot):
        self.bot = bot

        # (guild_id, user_id) -> timestamp
        self._last_xp_at: dict[tuple[int, int], float] = {}

        # (guild_id, user_id) -> recent normalized messages
        self._message_history: dict[
            tuple[int, int],
            deque[str],
        ] = defaultdict(lambda: deque(maxlen=self.HISTORY_SIZE))

        # Prevent multiple XP calculations for the same message.
        self._processed_messages: set[int] = set()

    # ------------------------------------------------------------------
    # XP CURVE
    # ------------------------------------------------------------------

    @classmethod
    def required_xp_for_level(cls, level: int) -> int:
        """
        Returns the XP required to advance beyond the supplied level.

        Level 1 starts at 250 XP.
        Progressively higher levels require substantially more XP.
        """

        if level <= 1:
            return cls.BASE_REQUIRED_XP

        required = cls.BASE_REQUIRED_XP * (
            cls.LEVEL_GROWTH ** (level - 1)
        )

        return max(cls.BASE_REQUIRED_XP, int(required))

    @classmethod
    def level_from_xp(cls, xp: int) -> tuple[int, int]:
        """
        Converts total XP into:

            (current_level, XP required for next level)

        This intentionally uses a loop rather than a closed-form
        calculation because it is easier to reason about and prevents
        edge-case errors around level boundaries.
        """

        xp = max(0, int(xp))
        level = 1

        while True:
            required = cls.required_xp_for_level(level)

            if xp < required:
                return level, required

            xp -= required
            level += 1

    # ------------------------------------------------------------------
    # MESSAGE ANALYSIS
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_message(content: str) -> str:
        """
        Normalize a message so spam/similarity checks are meaningful.
        """

        content = content.lower().strip()

        # Remove Discord custom emoji syntax.
        content = re.sub(r"<a?:\w+:\d+>", " ", content)

        # Remove URLs.
        content = re.sub(r"https?://\S+", " ", content)

        # Collapse whitespace.
        content = re.sub(r"\s+", " ", content)

        return content

    @staticmethod
    def _word_count(content: str) -> int:
        return len(re.findall(r"\b[\w'-]+\b", content))

    @staticmethod
    def _similarity(a: str, b: str) -> float:
        """
        Lightweight token similarity.

        Returns roughly:

            0.0 = completely different
            1.0 = effectively identical
        """

        if not a or not b:
            return 0.0

        a_words = set(a.split())
        b_words = set(b.split())

        if not a_words or not b_words:
            return 0.0

        intersection = len(a_words & b_words)
        union = len(a_words | b_words)

        if union == 0:
            return 0.0

        return intersection / union

    # ------------------------------------------------------------------
    # XP CALCULATION
    # ------------------------------------------------------------------

    def calculate_message_xp(
        self,
        *,
        content: str,
        cooldown_remaining: float,
        recent_messages: deque[str],
    ) -> int:
        """
        Calculate XP from a message.

        Longer genuine messages provide more XP, but with diminishing
        returns so extremely long messages cannot be abused.
        """

        content = content.strip()

        if not content:
            return 0

        if cooldown_remaining > 0:
            return 0

        normalized = self._normalize_message(content)

        if not normalized:
            return 0

        characters = len(normalized)
        words = self._word_count(normalized)

        # Very short messages should contribute little XP.
        if characters < 4:
            return 0

        # --------------------------------------------------------------
        # BASE LENGTH SCALING
        # --------------------------------------------------------------

        # sqrt gives strong benefit to meaningful length while creating
        # diminishing returns naturally.
        length_factor = math.sqrt(characters / 20)

        # Word contribution rewards actual language rather than padding.
        word_factor = min(math.sqrt(max(words, 1) / 5), 2.5)

        raw_xp = self.BASE_XP * length_factor * word_factor

        # --------------------------------------------------------------
        # MESSAGE QUALITY
        # --------------------------------------------------------------

        quality_multiplier = 1.0

        if characters >= 20:
            quality_multiplier += 0.10

        if characters >= 50:
            quality_multiplier += 0.10

        if characters >= 100:
            quality_multiplier += 0.10

        if characters >= 200:
            quality_multiplier += 0.10

        # Extremely long messages still have diminishing returns.
        if characters > 500:
            extra = characters - 500
            quality_multiplier += min(extra / 5000, 0.20)

        # Excessive repeated punctuation is usually low-value spam.
        if re.search(r"(.)\1{6,}", normalized):
            quality_multiplier *= 0.35

        # Messages consisting almost entirely of the same character are
        # not meaningful content.
        unique_chars = len(set(normalized.replace(" ", "")))

        if characters >= 20 and unique_chars <= 3:
            quality_multiplier *= 0.25

        # --------------------------------------------------------------
        # DUPLICATE / SIMILARITY PENALTIES
        # --------------------------------------------------------------

        duplicate_penalty = 1.0

        for previous in recent_messages:
            if normalized == previous:
                duplicate_penalty *= 0.05
                break

            similarity = self._similarity(normalized, previous)

            if similarity >= 0.90:
                duplicate_penalty *= 0.15
                break

            if similarity >= 0.75:
                duplicate_penalty *= 0.40
                break

            if similarity >= 0.60:
                duplicate_penalty *= 0.70
                break

        raw_xp *= quality_multiplier
        raw_xp *= duplicate_penalty

        # --------------------------------------------------------------
        # HARD LIMIT
        # --------------------------------------------------------------

        return max(
            0,
            min(
                self.MAX_MESSAGE_XP,
                int(raw_xp),
            ),
        )

    # ------------------------------------------------------------------
    # BOOSTS
    # ------------------------------------------------------------------

    @staticmethod
    def role_multiplier(member: discord.Member) -> float:
        """
        Calculate role-based Guild XP multiplier.

        Actual configurable XP boost roles can be added here later.
        """

        multiplier = 1.0

        # Highest applicable multiplier wins.
        #
        # These are intentionally placeholders until the actual Lunar
        # boost-role configuration is added.
        role_multipliers = {
            # role_id: multiplier
            # 123456789012345678: 1.25,
        }

        highest = 1.0

        for role in member.roles:
            highest = max(
                highest,
                role_multipliers.get(role.id, 1.0),
            )

        return highest

    # ------------------------------------------------------------------
    # DATABASE
    # ------------------------------------------------------------------

    async def _ensure_user(
        self,
        guild_id: int,
        user_id: int,
    ):
        return await db.guild_xp.ensure(
            guild_id,
            user_id,
            level=1,
            required_xp=self.required_xp_for_level(1),
        )

    # ------------------------------------------------------------------
    # MESSAGE PROCESSING
    # ------------------------------------------------------------------

    async def process_message(
        self,
        message: discord.Message,
    ) -> Optional[dict]:
        """
        Process one Discord message.

        Returns a dictionary containing the XP result, or None when
        the message should not award XP.
        """

        if message.guild is None:
            return None

        if message.author.bot:
            return None

        if not isinstance(message.author, discord.Member):
            return None

        if message.author.id in self.XP_EXEMPT_USER_IDS:
            return None

        if message.id in self._processed_messages:
            return None

        self._processed_messages.add(message.id)

        # Keep the memory set bounded.
        if len(self._processed_messages) > 10_000:
            self._processed_messages = set(
                list(self._processed_messages)[-5_000:]
            )

        guild_id = message.guild.id
        user_id = message.author.id
        key = (guild_id, user_id)

        now = time.monotonic()

        last_xp = self._last_xp_at.get(key)
        cooldown_remaining = 0.0

        if last_xp is not None:
            elapsed = now - last_xp

            if elapsed < self.MIN_COOLDOWN:
                cooldown_remaining = self.MIN_COOLDOWN - elapsed

        history = self._message_history[key]

        amount = self.calculate_message_xp(
            content=message.content or "",
            cooldown_remaining=cooldown_remaining,
            recent_messages=history,
        )

        normalized = self._normalize_message(
            message.content or ""
        )

        # Always remember the message for anti-spam checks, even if it
        # didn't earn XP.
        if normalized:
            history.append(normalized)

        if amount <= 0:
            return None

        role_multiplier = self.role_multiplier(message.author)

        final_amount = max(
            1,
            int(round(amount * role_multiplier)),
        )

        # Record cooldown only after successfully awarding XP.
        self._last_xp_at[key] = now

        current = await self._ensure_user(
            guild_id,
            user_id,
        )

        current_xp = int(
            getattr(current, "xp", 0) or 0
        )

        current_level = int(
            getattr(current, "level", 1) or 1
        )

        old_total_xp = current_xp

        new_total_xp = old_total_xp + final_amount

        new_level, required_xp = self.level_from_xp(
            new_total_xp
        )

        leveled_up = new_level > current_level

        # --------------------------------------------------------------
        # UPDATE DATABASE
        # --------------------------------------------------------------

        await db.guild_xp.add_xp(
            guild_id,
            user_id,
            final_amount,
            level=new_level,
            required_xp=required_xp,
            source="message",
            channel_id=message.channel.id,
            message_id=message.id,
            total_messages=(
                int(
                    getattr(current, "total_messages", 0)
                    or 0
                )
                + 1
            ),
        )

        result = {
            "guild_id": guild_id,
            "user_id": user_id,
            "amount": final_amount,
            "previous_xp": old_total_xp,
            "xp": new_total_xp,
            "level": new_level,
            "previous_level": current_level,
            "required_xp": required_xp,
            "leveled_up": leveled_up,
            "role_multiplier": role_multiplier,
        }

        log.debug(
            "Guild XP | user=%s guild=%s +%s XP | level=%s | multiplier=%.2f",
            user_id,
            guild_id,
            final_amount,
            new_level,
            role_multiplier,
        )

        return result

    # ------------------------------------------------------------------
    # MANUAL XP
    # ------------------------------------------------------------------

    async def award_xp(
        self,
        member: discord.Member,
        amount: int,
        *,
        source: str = "manual",
    ) -> Optional[dict]:
        """
        Manually award Guild XP.

        Intended for commands such as staff XP adjustments, events,
        giveaways, rewards, etc.
        """

        if member.guild is None:
            return None

        amount = int(amount)

        if amount <= 0:
            return None

        current = await self._ensure_user(
            member.guild.id,
            member.id,
        )

        old_xp = int(
            getattr(current, "xp", 0) or 0
        )

        old_level = int(
            getattr(current, "level", 1) or 1
        )

        new_total_xp = old_xp + amount

        new_level, required_xp = self.level_from_xp(
            new_total_xp
        )

        await db.guild_xp.add_xp(
            member.guild.id,
            member.id,
            amount,
            level=new_level,
            required_xp=required_xp,
            source=source,
            total_messages=int(
                getattr(current, "total_messages", 0)
                or 0
            ),
        )

        return {
            "guild_id": member.guild.id,
            "user_id": member.id,
            "amount": amount,
            "previous_xp": old_xp,
            "xp": new_total_xp,
            "level": new_level,
            "previous_level": old_level,
            "required_xp": required_xp,
            "leveled_up": new_level > old_level,
            "role_multiplier": 1.0,
        }

    # ------------------------------------------------------------------
    # REMOVE XP
    # ------------------------------------------------------------------

    async def remove_xp(
        self,
        member: discord.Member,
        amount: int,
    ) -> Optional[dict]:
        """
        Remove Guild XP without allowing XP to fall below zero.
        """

        if member.guild is None:
            return None

        amount = max(0, int(amount))

        if amount <= 0:
            return None

        current = await self._ensure_user(
            member.guild.id,
            member.id,
        )

        current_xp = int(
            getattr(current, "xp", 0) or 0
        )

        new_total_xp = max(
            0,
            current_xp - amount,
        )

        new_level, required_xp = self.level_from_xp(
            new_total_xp
        )

        actual_removed = current_xp - new_total_xp

        if actual_removed <= 0:
            return {
                "guild_id": member.guild.id,
                "user_id": member.id,
                "amount": 0,
                "xp": current_xp,
                "level": new_level,
                "required_xp": required_xp,
            }

        await db.guild_xp.update_progress(
            member.guild.id,
            member.id,
            xp=new_total_xp,
            level=new_level,
            required_xp=required_xp,
        )

        return {
            "guild_id": member.guild.id,
            "user_id": member.id,
            "amount": actual_removed,
            "xp": new_total_xp,
            "level": new_level,
            "required_xp": required_xp,
        }


async def setup(bot: commands.Bot):
    await bot.add_cog(GuildXP(bot))