from __future__ import annotations

import logging
import math
import re
import time
from collections import defaultdict, deque
from typing import Optional

import discord
from discord.ext import commands

from cogs.utilities.database import db


log = logging.getLogger("lunar.guild_xp")


class GuildXP(commands.Cog):
    """
    Independent Discord Guild XP system.

    Guild XP is completely separate from Lunar website XP.
    """

    # ==============================================================
    # AUTHORITATIVE XP SETTINGS
    # ==============================================================

    BASE_XP = 8
    BASE_REQUIRED_XP =100
    LEVEL_GROWTH = 1.08

    MIN_COOLDOWN = 0.5

    HISTORY_SIZE = 8
    MAX_MESSAGE_XP = 150

    XP_EXEMPT_USER_IDS: set[int] = set()

    # ==============================================================
    # INITIALIZATION
    # ==============================================================

    def __init__(self, bot: commands.Bot):
        self.bot = bot

        # (guild_id, user_id) -> monotonic timestamp
        self._last_xp_at: dict[tuple[int, int], float] = {}

        # (guild_id, user_id) -> recent normalized messages
        self._message_history: dict[
            tuple[int, int],
            deque[str],
        ] = defaultdict(
            lambda: deque(
                maxlen=self.HISTORY_SIZE
            )
        )

        # Prevent duplicate processing.
        self._processed_messages: set[int] = set()

    # ==============================================================
    # XP CURVE
    # ==============================================================

    @classmethod
    def required_xp_for_level(cls, level: int) -> int:
        """
        XP required to progress from `level` to `level + 1`.

        The curve is exponential and becomes increasingly difficult
        as levels rise.
        """

        level = max(1, int(level))

        return max(
            cls.BASE_REQUIRED_XP,
            int(
                cls.BASE_REQUIRED_XP
                * (
                    cls.LEVEL_GROWTH
                    ** (level - 1)
                )
            ),
        )

    @classmethod
    def total_xp_for_level(cls, level: int) -> int:
        """
        Total lifetime XP required to reach a level.

        Example:

            level 1 -> 0 total XP
            level 2 -> XP requirement of level 1
            level 3 -> level 1 + level 2
        """

        level = max(1, int(level))

        total = 0

        for current_level in range(1, level):
            total += cls.required_xp_for_level(
                current_level
            )

        return total

    @classmethod
    def level_from_xp(
        cls,
        total_xp: int,
    ) -> tuple[int, int, int]:
        """
        Convert lifetime XP into:

            level
            XP currently inside that level
            XP required for that level

        Example:

            (250 XP) -> level 2, 0 / 320
        """

        total_xp = max(
            0,
            int(total_xp),
        )

        level = 1
        remaining = total_xp

        while True:
            required = cls.required_xp_for_level(
                level
            )

            if remaining < required:
                return (
                    level,
                    remaining,
                    required,
                )

            remaining -= required
            level += 1

    @classmethod
    def progress_from_xp(
        cls,
        total_xp: int,
    ) -> dict[str, int | float]:
        """
        Return all progression information needed by `/level`.
        """

        level, current_xp, required_xp = (
            cls.level_from_xp(total_xp)
        )

        percentage = (
            current_xp / required_xp
            if required_xp > 0
            else 0.0
        )

        return {
            "level": level,
            "xp": current_xp,
            "required_xp": required_xp,
            "total_xp": max(
                0,
                int(total_xp),
            ),
            "progress": percentage,
        }

    # ==============================================================
    # MESSAGE NORMALIZATION
    # ==============================================================

    @staticmethod
    def normalize_message(content: str) -> str:
        """
        Normalize content for anti-spam comparisons.
        """

        content = content.lower().strip()

        if not content:
            return ""

        # Remove Discord custom emoji markup.
        content = re.sub(
            r"<a?:\w+:\d+>",
            " ",
            content,
        )

        # Remove URLs from similarity analysis.
        content = re.sub(
            r"https?://\S+",
            " ",
            content,
        )

        # Collapse whitespace.
        content = re.sub(
            r"\s+",
            " ",
            content,
        )

        return content.strip()

    @staticmethod
    def word_count(content: str) -> int:
        return len(
            re.findall(
                r"\b[\w'-]+\b",
                content,
            )
        )

    # ==============================================================
    # SIMILARITY / ANTI-SPAM
    # ==============================================================

    @staticmethod
    def message_similarity(
        first: str,
        second: str,
    ) -> float:
        """
        Jaccard token similarity.
        """

        first_words = set(
            first.lower().split()
        )

        second_words = set(
            second.lower().split()
        )

        if not first_words or not second_words:
            return 0.0

        union = first_words | second_words

        if not union:
            return 0.0

        return len(
            first_words & second_words
        ) / len(union)

    @classmethod
    def duplicate_multiplier(
        cls,
        content: str,
        recent_messages: deque[str],
    ) -> float:
        """
        Apply anti-duplicate penalties.

        Exact duplicate:
            0.05x

        >= 90% similarity:
            0.15x

        >= 75%:
            0.40x

        >= 60%:
            0.70x
        """

        normalized = cls.normalize_message(
            content
        )

        if not normalized:
            return 0.0

        multiplier = 1.0

        for previous in recent_messages:
            if normalized == previous:
                return 0.05

            similarity = cls.message_similarity(
                normalized,
                previous,
            )

            if similarity >= 0.90:
                return 0.15

            if similarity >= 0.75:
                multiplier = min(
                    multiplier,
                    0.40,
                )

            elif similarity >= 0.60:
                multiplier = min(
                    multiplier,
                    0.70,
                )

        return multiplier

    # ==============================================================
    # MESSAGE QUALITY
    # ==============================================================

    @classmethod
    def message_quality_multiplier(
        cls,
        content: str,
    ) -> float:
        """
        Reward meaningful message length while applying modest
        quality penalties.
        """

        content = content.strip()

        if not content:
            return 0.0

        characters = len(content)

        multiplier = 1.0

        # Genuine longer messages receive additional weight.
        if characters >= 20:
            multiplier += 0.10

        if characters >= 50:
            multiplier += 0.10

        if characters >= 100:
            multiplier += 0.10

        if characters >= 200:
            multiplier += 0.10

        # Diminishing benefit beyond 500 characters.
        if characters > 500:
            multiplier += min(
                (characters - 500) / 5000,
                0.20,
            )

        # Repeated-character spam.
        if re.search(
            r"(.)\1{6,}",
            content,
        ):
            multiplier *= 0.35

        compact = re.sub(
            r"\s+",
            "",
            content,
        )

        # Low-information message.
        if (
            len(compact) >= 20
            and len(set(compact)) <= 3
        ):
            multiplier *= 0.25

        return max(
            0.0,
            multiplier,
        )

    # ==============================================================
    # MESSAGE XP
    # ==============================================================

    @classmethod
    def calculate_message_xp(
        cls,
        content: str,
        *,
        recent_messages: Optional[
            deque[str]
        ] = None,
        boost_multiplier: float = 1.0,
    ) -> dict[str, int | float]:
        """
        Calculate Guild XP for a message.

        Length increases XP using diminishing returns.
        Spam and duplicate penalties are applied separately.
        """

        content = content.strip()

        if not content:
            return {
                "base_xp": cls.BASE_XP,
                "length_factor": 0.0,
                "word_factor": 0.0,
                "quality_multiplier": 0.0,
                "duplicate_multiplier": 0.0,
                "boost_multiplier": 1.0,
                "final_xp": 0,
            }

        normalized = cls.normalize_message(
            content
        )

        if not normalized:
            return {
                "base_xp": cls.BASE_XP,
                "length_factor": 0.0,
                "word_factor": 0.0,
                "quality_multiplier": 0.0,
                "duplicate_multiplier": 0.0,
                "boost_multiplier": 1.0,
                "final_xp": 0,
            }

        characters = len(normalized)

        words = cls.word_count(
            normalized
        )

        # Extremely short messages do not award XP.
        if characters < 4:
            return {
                "base_xp": cls.BASE_XP,
                "length_factor": 0.0,
                "word_factor": 0.0,
                "quality_multiplier": 0.0,
                "duplicate_multiplier": 1.0,
                "boost_multiplier": 1.0,
                "final_xp": 0,
            }

        # ----------------------------------------------------------
        # LENGTH
        # ----------------------------------------------------------

        length_factor = math.sqrt(
            characters / 20
        )

        # ----------------------------------------------------------
        # WORD COUNT
        # ----------------------------------------------------------

        word_factor = min(
            math.sqrt(
                max(words, 1) / 5
            ),
            2.5,
        )

        # ----------------------------------------------------------
        # QUALITY
        # ----------------------------------------------------------

        quality_multiplier = (
            cls.message_quality_multiplier(
                normalized
            )
        )

        # ----------------------------------------------------------
        # DUPLICATES
        # ----------------------------------------------------------

        duplicate_multiplier = (
            cls.duplicate_multiplier(
                normalized,
                recent_messages or deque(),
            )
        )

        # ----------------------------------------------------------
        # BOOST
        # ----------------------------------------------------------

        try:
            boost_multiplier = float(
                boost_multiplier
            )
        except (
            TypeError,
            ValueError,
        ):
            boost_multiplier = 1.0

        if not math.isfinite(
            boost_multiplier
        ):
            boost_multiplier = 1.0

        boost_multiplier = min(
            10.0,
            max(
                0.0,
                boost_multiplier,
            ),
        )

        # ----------------------------------------------------------
        # FINAL
        # ----------------------------------------------------------

        raw_xp = (
            cls.BASE_XP
            * length_factor
            * word_factor
            * quality_multiplier
            * duplicate_multiplier
            * boost_multiplier
        )

        final_xp = max(
            0,
            min(
                cls.MAX_MESSAGE_XP,
                int(raw_xp),
            ),
        )

        return {
            "base_xp": cls.BASE_XP,
            "length_factor": length_factor,
            "word_factor": word_factor,
            "quality_multiplier": quality_multiplier,
            "duplicate_multiplier": duplicate_multiplier,
            "boost_multiplier": boost_multiplier,
            "final_xp": final_xp,
        }

    # ==============================================================
    # ROLE MULTIPLIER
    # ==============================================================

    @staticmethod
    def role_multiplier(
        member: discord.Member,
    ) -> float:
        """
        Return the highest configured role multiplier.

        Populate the mapping with the actual Lunar role IDs later.
        """

        role_multipliers: dict[int, float] = {
            # ROLE_ID: MULTIPLIER,
        }

        multiplier = 1.0

        for role in member.roles:
            multiplier = max(
                multiplier,
                float(
                    role_multipliers.get(
                        role.id,
                        1.0,
                    )
                ),
            )

        return multiplier

    # ==============================================================
    # DATABASE
    # ==============================================================

    @classmethod
    async def ensure_user(
        cls,
        guild_id: int,
        user_id: int,
    ):
        """
        Ensure the member has a Guild XP record.
        """

        return await db.guild_xp.ensure(
            guild_id,
            user_id,
            level=1,
            required_xp=cls.required_xp_for_level(
                1
            ),
        )

    # ==============================================================
    # MESSAGE PROCESSING
    # ==============================================================

    async def process_message(
        self,
        message: discord.Message,
    ) -> Optional[dict]:
        """
        Process a Discord message and award Guild XP when eligible.
        """

        if message.guild is None:
            return None

        if message.author.bot:
            return None

        if not isinstance(
            message.author,
            discord.Member,
        ):
            return None

        if (
            message.author.id
            in self.XP_EXEMPT_USER_IDS
        ):
            return None

        if message.id in self._processed_messages:
            return None

        self._processed_messages.add(
            message.id
        )

        # Keep memory bounded.
        if len(
            self._processed_messages
        ) > 10_000:
            self._processed_messages = set(
                list(
                    self._processed_messages
                )[-5_000:]
            )

        guild_id = message.guild.id
        user_id = message.author.id

        key = (
            guild_id,
            user_id,
        )

        # ----------------------------------------------------------
        # COOLDOWN
        # ----------------------------------------------------------

        now = time.monotonic()

        last_award = self._last_xp_at.get(
            key
        )

        if last_award is not None:
            elapsed = now - last_award

            if elapsed < self.MIN_COOLDOWN:
                cooldown_remaining = (
                    self.MIN_COOLDOWN
                    - elapsed
                )
            else:
                cooldown_remaining = 0.0
        else:
            cooldown_remaining = 0.0

        history = self._message_history[
            key
        ]

        # ----------------------------------------------------------
        # HISTORY
        # ----------------------------------------------------------

        normalized = self.normalize_message(
            message.content or ""
        )

        # Always store the message before returning.
        if normalized:
            history.append(
                normalized
            )

        if cooldown_remaining > 0:
            return None

        # ----------------------------------------------------------
        # MULTIPLIERS
        # ----------------------------------------------------------

        role_multiplier = (
            self.role_multiplier(
                message.author
            )
        )

        # ----------------------------------------------------------
        # CALCULATE
        # ----------------------------------------------------------

        calculation = (
            self.calculate_message_xp(
                message.content or "",
                recent_messages=deque(
                    list(history)[:-1],
                    maxlen=self.HISTORY_SIZE,
                ),
                boost_multiplier=role_multiplier,
            )
        )

        base_amount = int(
            calculation["final_xp"]
        )

        if base_amount <= 0:
            return None

        final_amount = min(
            self.MAX_MESSAGE_XP,
            max(
                1,
                base_amount,
            ),
        )

        self._last_xp_at[key] = now

        # ----------------------------------------------------------
        # CURRENT STATE
        # ----------------------------------------------------------

        current = await self.ensure_user(
            guild_id,
            user_id,
        )

        old_total_xp = int(
            getattr(
                current,
                "xp",
                0,
            )
            or 0
        )

        old_level = int(
            getattr(
                current,
                "level",
                1,
            )
            or 1
        )

        total_messages = int(
            getattr(
                current,
                "total_messages",
                0,
            )
            or 0
        )

        # ----------------------------------------------------------
        # NEW STATE
        # ----------------------------------------------------------

        new_total_xp = (
            old_total_xp
            + final_amount
        )

        new_level, current_level_xp, required_xp = (
            self.level_from_xp(
                new_total_xp
            )
        )

        leveled_up = (
            new_level > old_level
        )

        # ----------------------------------------------------------
        # DATABASE
        # ----------------------------------------------------------

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
                total_messages + 1
            ),
        )

        result = {
            "guild_id": guild_id,
            "user_id": user_id,
            "amount": final_amount,
            "previous_xp": old_total_xp,
            "xp": new_total_xp,
            "level": new_level,
            "previous_level": old_level,
            "current_level_xp": current_level_xp,
            "required_xp": required_xp,
            "leveled_up": leveled_up,
            "role_multiplier": role_multiplier,
            "calculation": calculation,
        }

        log.debug(
            (
                "Guild XP | guild=%s user=%s "
                "+%s | total=%s | level=%s | "
                "multiplier=%.2f"
            ),
            guild_id,
            user_id,
            final_amount,
            new_total_xp,
            new_level,
            role_multiplier,
        )

        return result

    # ==============================================================
    # MANUAL XP
    # ==============================================================

    async def award_xp(
        self,
        member: discord.Member,
        amount: int,
        *,
        source: str = "manual",
    ) -> Optional[dict]:
        """
        Manually award Guild XP.
        """

        if member.guild is None:
            return None

        amount = int(amount)

        if amount <= 0:
            return None

        current = await self.ensure_user(
            member.guild.id,
            member.id,
        )

        old_total_xp = int(
            getattr(
                current,
                "xp",
                0,
            )
            or 0
        )

        old_level = int(
            getattr(
                current,
                "level",
                1,
            )
            or 1
        )

        total_messages = int(
            getattr(
                current,
                "total_messages",
                0,
            )
            or 0
        )

        new_total_xp = (
            old_total_xp + amount
        )

        new_level, current_level_xp, required_xp = (
            self.level_from_xp(
                new_total_xp
            )
        )

        await db.guild_xp.add_xp(
            member.guild.id,
            member.id,
            amount,
            level=new_level,
            required_xp=required_xp,
            source=source,
            total_messages=total_messages,
        )

        return {
            "guild_id": member.guild.id,
            "user_id": member.id,
            "amount": amount,
            "previous_xp": old_total_xp,
            "xp": new_total_xp,
            "level": new_level,
            "previous_level": old_level,
            "current_level_xp": current_level_xp,
            "required_xp": required_xp,
            "leveled_up": (
                new_level > old_level
            ),
            "role_multiplier": 1.0,
        }

    # ==============================================================
    # REMOVE XP
    # ==============================================================

    async def remove_xp(
        self,
        member: discord.Member,
        amount: int,
    ) -> Optional[dict]:
        """
        Remove Guild XP without allowing negative XP.
        """

        if member.guild is None:
            return None

        amount = max(
            0,
            int(amount),
        )

        if amount <= 0:
            return None

        current = await self.ensure_user(
            member.guild.id,
            member.id,
        )

        old_total_xp = int(
            getattr(
                current,
                "xp",
                0,
            )
            or 0
        )

        new_total_xp = max(
            0,
            old_total_xp - amount,
        )

        removed = (
            old_total_xp
            - new_total_xp
        )

        new_level, current_level_xp, required_xp = (
            self.level_from_xp(
                new_total_xp
            )
        )

        if removed > 0:
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
            "amount": removed,
            "previous_xp": old_total_xp,
            "xp": new_total_xp,
            "level": new_level,
            "current_level_xp": current_level_xp,
            "required_xp": required_xp,
        }


# ==============================================================
# COG SETUP
# ==============================================================

async def setup(
    bot: commands.Bot,
):
    await bot.add_cog(
        GuildXP(bot)
    )