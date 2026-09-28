from __future__ import annotations

import math
import re
from datetime import timedelta
from typing import Optional

from cogs.integrations.guild_xp import (
    GuildXP,
)


# ─────────────────────────────────────────────────────────────
# AUTHORITATIVE GUILD XP REFERENCES
# ─────────────────────────────────────────────────────────────

BASE_XP = GuildXP.BASE_XP
BASE_REQUIRED_XP = GuildXP.BASE_REQUIRED_XP
LEVEL_GROWTH = GuildXP.LEVEL_GROWTH


def required_xp_for_level(level: int) -> int:
    """
    Use the authoritative Guild XP progression curve.
    """

    return GuildXP.required_xp_for_level(level)


def total_xp_for_level(level: int) -> int:
    """
    Total lifetime XP required to reach the beginning of `level`.
    """

    return GuildXP.total_xp_for_level(level)


def level_from_total_xp(
    total_xp: int,
) -> tuple[int, int, int]:
    """
    Return:

        level
        XP currently inside that level
        XP required for that level
    """

    return GuildXP.level_from_xp(total_xp)


def xp_progress(
    total_xp: int,
) -> tuple[int, int, int, float]:
    """
    Return:

        level
        current XP
        required XP
        progress percentage
    """

    level, current_xp, required_xp = (
        GuildXP.level_from_xp(total_xp)
    )

    percentage = (
        (current_xp / required_xp) * 100
        if required_xp > 0
        else 0.0
    )

    return (
        level,
        current_xp,
        required_xp,
        min(
            100.0,
            max(0.0, percentage),
        ),
    )


# ─────────────────────────────────────────────────────────────
# XP DISPLAY
# ─────────────────────────────────────────────────────────────

def format_xp(
    amount: int,
) -> str:
    return f"{max(0, int(amount)):,}"


def format_xp_progress(
    current_xp: int,
    required_xp: int,
) -> str:
    return (
        f"{format_xp(current_xp)}"
        f" / "
        f"{format_xp(required_xp)}"
    )


def level_progress_bar(
    current_xp: int,
    required_xp: int,
    *,
    length: int = 18,
    filled: str = "━",
    empty: str = "─",
) -> str:
    """
    Build a compact text progress bar.
    """

    required_xp = max(
        1,
        int(required_xp),
    )

    current_xp = min(
        required_xp,
        max(0, int(current_xp)),
    )

    ratio = current_xp / required_xp

    filled_count = int(
        round(ratio * length)
    )

    filled_count = min(
        length,
        max(0, filled_count),
    )

    return (
        filled * filled_count
        + empty * (
            length - filled_count
        )
    )


def percentage(
    current: float,
    maximum: float,
) -> float:
    """
    Convert a value into a 0-100 percentage.
    """

    if maximum <= 0:
        return 0.0

    return min(
        100.0,
        max(
            0.0,
            (current / maximum) * 100.0,
        ),
    )


# ─────────────────────────────────────────────────────────────
# GENERIC MULTIPLIERS
# ─────────────────────────────────────────────────────────────

def clamp_multiplier(
    multiplier: float,
    *,
    minimum: float = 0.0,
    maximum: float = 10.0,
) -> float:
    """
    Safely clamp an XP multiplier.
    """

    try:
        multiplier = float(multiplier)
    except (TypeError, ValueError):
        return minimum

    if not math.isfinite(multiplier):
        return minimum

    return min(
        maximum,
        max(
            minimum,
            multiplier,
        ),
    )


def combine_multipliers(
    *multipliers: float,
) -> float:
    """
    Multiply multiple XP multipliers together.

    Example:

        combine_multipliers(1.25, 2.0)
        -> 2.5
    """

    result = 1.0

    for multiplier in multipliers:
        try:
            value = float(multiplier)
        except (TypeError, ValueError):
            continue

        if not math.isfinite(value):
            continue

        result *= max(
            0.0,
            value,
        )

    return result


# ─────────────────────────────────────────────────────────────
# COOLDOWNS
# ─────────────────────────────────────────────────────────────

def cooldown_remaining(
    last_awarded_at: Optional[float],
    now: float,
    cooldown_seconds: float,
) -> float:
    """
    Return remaining cooldown in seconds.
    """

    if last_awarded_at is None:
        return 0.0

    elapsed = max(
        0.0,
        float(now) - float(last_awarded_at),
    )

    return max(
        0.0,
        float(cooldown_seconds) - elapsed,
    )


def cooldown_ready(
    last_awarded_at: Optional[float],
    now: float,
    cooldown_seconds: float,
) -> bool:
    return (
        cooldown_remaining(
            last_awarded_at,
            now,
            cooldown_seconds,
        )
        <= 0
    )


# ─────────────────────────────────────────────────────────────
# MESSAGE HELPERS
# ─────────────────────────────────────────────────────────────

def normalize_message(
    content: str,
) -> str:
    """
    Normalize a message for comparisons and statistics.
    """

    content = content.lower().strip()

    if not content:
        return ""

    content = re.sub(
        r"<a?:\w+:\d+>",
        " ",
        content,
    )

    content = re.sub(
        r"https?://\S+",
        " ",
        content,
    )

    content = re.sub(
        r"\s+",
        " ",
        content,
    )

    return content.strip()


def word_count(
    content: str,
) -> int:
    return len(
        re.findall(
            r"\b[\w'-]+\b",
            content,
        )
    )


def message_similarity(
    first: str,
    second: str,
) -> float:
    """
    Jaccard-style token similarity.
    """

    first_words = set(
        normalize_message(first).split()
    )

    second_words = set(
        normalize_message(second).split()
    )

    if not first_words or not second_words:
        return 0.0

    union = first_words | second_words

    if not union:
        return 0.0

    return len(
        first_words & second_words
    ) / len(union)


# ─────────────────────────────────────────────────────────────
# DURATION HELPERS
# ─────────────────────────────────────────────────────────────

_DURATION_PATTERN = re.compile(
    r"^\s*(\d+)\s*"
    r"(s|sec|secs|second|seconds|"
    r"m|min|mins|minute|minutes|"
    r"h|hr|hrs|hour|hours|"
    r"d|day|days)\s*$",
    re.IGNORECASE,
)


def parse_duration(
    value: str,
) -> Optional[timedelta]:
    """
    Parse:

        30s
        5m
        2h
        7d
        15 minutes
        3 hours
    """

    if not value:
        return None

    match = _DURATION_PATTERN.match(
        value
    )

    if not match:
        return None

    amount = int(
        match.group(1)
    )

    unit = match.group(2).lower()

    if unit in {
        "s",
        "sec",
        "secs",
        "second",
        "seconds",
    }:
        return timedelta(
            seconds=amount
        )

    if unit in {
        "m",
        "min",
        "mins",
        "minute",
        "minutes",
    }:
        return timedelta(
            minutes=amount
        )

    if unit in {
        "h",
        "hr",
        "hrs",
        "hour",
        "hours",
    }:
        return timedelta(
            hours=amount
        )

    if unit in {
        "d",
        "day",
        "days",
    }:
        return timedelta(
            days=amount
        )

    return None


def format_duration(
    duration: timedelta | int | float,
) -> str:
    """
    Format a duration into a compact string.
    """

    if isinstance(
        duration,
        timedelta,
    ):
        seconds = int(
            duration.total_seconds()
        )
    else:
        seconds = int(duration)

    seconds = max(
        0,
        seconds,
    )

    days, seconds = divmod(
        seconds,
        86400,
    )

    hours, seconds = divmod(
        seconds,
        3600,
    )

    minutes, seconds = divmod(
        seconds,
        60,
    )

    parts: list[str] = []

    if days:
        parts.append(
            f"{days}d"
        )

    if hours:
        parts.append(
            f"{hours}h"
        )

    if minutes:
        parts.append(
            f"{minutes}m"
        )

    if seconds and len(parts) < 2:
        parts.append(
            f"{seconds}s"
        )

    return " ".join(parts) or "0s"


# ─────────────────────────────────────────────────────────────
# LEVEL CHANGES
# ─────────────────────────────────────────────────────────────

def level_up_count(
    previous_level: int,
    current_level: int,
) -> int:
    return max(
        0,
        int(current_level)
        - int(previous_level),
    )


def did_level_up(
    previous_level: int,
    current_level: int,
) -> bool:
    return (
        int(current_level)
        > int(previous_level)
    )


# ─────────────────────────────────────────────────────────────
# REQUIREMENT HELPERS
# ─────────────────────────────────────────────────────────────

def xp_until_next_level(
    total_xp: int,
) -> int:
    """
    Return how much lifetime XP remains before the next level.
    """

    _, current_xp, required_xp = (
        GuildXP.level_from_xp(
            total_xp
        )
    )

    return max(
        0,
        required_xp - current_xp,
    )


def progress_ratio(
    total_xp: int,
) -> float:
    """
    Return progress toward the next level as 0.0-1.0.
    """

    _, current_xp, required_xp = (
        GuildXP.level_from_xp(
            total_xp
        )
    )

    if required_xp <= 0:
        return 0.0

    return min(
        1.0,
        max(
            0.0,
            current_xp / required_xp,
        ),
    )


# ─────────────────────────────────────────────────────────────
# LEVEL-UP COIN REWARDS
# ─────────────────────────────────────────────────────────────
#
# Shared by the website XP grant (cogs/integrations/xp.py) and
# the Guild XP system (cogs/integrations/guild_xp.py), so both
# "level up" paths pay out the same curve of coins.
# ─────────────────────────────────────────────────────────────

BASE_LEVEL_UP_COINS = 25
LEVEL_UP_COIN_GROWTH = 0.08  # +8% per level, compounding

MAX_LEVEL_UP_COINS = 5_000  # hard ceiling per single level crossed


def coins_for_level(
    level: int,
) -> int:
    """
    Coins awarded for reaching `level`.

    Grows with level so higher levels are worth more:

        level 1  -> 25
        level 10 -> ~50
        level 25 -> ~158
        level 50 -> ~1,174

    Capped by MAX_LEVEL_UP_COINS so runaway levels can't mint an
    unbounded amount of coins in one grant.
    """

    level = max(1, int(level))

    raw = BASE_LEVEL_UP_COINS * (
        (1 + LEVEL_UP_COIN_GROWTH)
        ** (level - 1)
    )

    return min(
        MAX_LEVEL_UP_COINS,
        max(
            BASE_LEVEL_UP_COINS,
            int(raw),
        ),
    )


def coins_for_level_range(
    previous_level: int,
    new_level: int,
) -> int:
    """
    Total coin reward for going from `previous_level` to
    `new_level`, summing the reward for every level crossed.

    Handles multi-level jumps (e.g. a big manual XP grant that
    pushes someone up several levels at once) fairly, rather than
    only paying out for the final level reached.
    """

    previous_level = max(1, int(previous_level))
    new_level = max(previous_level, int(new_level))

    if new_level <= previous_level:
        return 0

    return sum(
        coins_for_level(level)
        for level in range(
            previous_level + 1,
            new_level + 1,
        )
    )


def format_coins(
    amount: int,
) -> str:
    return f"{max(0, int(amount)):,}"


# ─────────────────────────────────────────────────────────────
# ROLE BONUS MULTIPLIERS
# ─────────────────────────────────────────────────────────────
#
# Shared by every XP/coin grant path (website message XP, website
# message coins, Guild XP, and level-up coin rewards) so a member
# gets the same bonus no matter which system pays them out.
#
# Stacks additively: having both roles is better than either
# alone. 1.0 = no bonus, so e.g. 0.50 == +50%.
# ─────────────────────────────────────────────────────────────

ROLE_BONUS_MULTIPLIERS: dict[int, float] = {
    1515063228223455442: 0.50,  # Website Donator -> +50%
    1368999154788995093: 0.25,  # Server Booster   -> +25%
}


def role_bonus_multiplier(
    role_ids,
) -> float:
    """
    Sum the configured bonus percentages for any of the given
    role IDs and return it as a multiplier (1.0 = no bonus).
    """

    bonus = 0.0

    for role_id in role_ids:
        try:
            bonus += ROLE_BONUS_MULTIPLIERS.get(
                int(role_id),
                0.0,
            )
        except (TypeError, ValueError):
            continue

    return 1.0 + bonus


def member_bonus_multiplier(
    member,
) -> float:
    """
    Convenience wrapper: pull role IDs off a discord.Member-like
    object (anything with a `.roles` iterable of objects that
    have an `.id`). Returns 1.0 (no bonus) for anything else,
    such as a plain discord.User with no roles attribute.
    """

    roles = getattr(member, "roles", None)

    if not roles:
        return 1.0

    return role_bonus_multiplier(
        role.id for role in roles
    )
