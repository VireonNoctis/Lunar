from __future__ import annotations

import logging
from typing import Any, Optional

import discord
from discord.ext import commands

from cogs.utilities.database import db, json_loads
from cogs.utilities.emoji import EMOJI
from cogs.utilities import lunarapi


log = logging.getLogger("lunar.giveaway_rewards")


# ============================================================
# Configuration
# ============================================================

WEBSITE_DONATOR_ROLE_ID = 1515063228223455442
WINNER_ANNOUNCE_ROLE_ID = 1521244395272405164

REWARD_TYPES: dict[str, dict[str, str]] = {
    "gacha": {"label": "Gacha Card", "emoji": EMOJI["cards"]},
    "xp": {"label": "XP", "emoji": EMOJI["xp"]},
    "coins": {"label": "Coins", "emoji": EMOJI["coins"]},
    "donator_role": {"label": "Donator Role", "emoji": EMOJI["donator"]},
    "other": {"label": "Other / Manual", "emoji": EMOJI["gift"]},
}


# ============================================================
# Reward config UI
# ============================================================

class RewardTypeSelect(discord.ui.Select):
    def __init__(self, owner_id: int, on_pick) -> None:
        self.owner_id = owner_id
        self.on_pick = on_pick

        options = [
            discord.SelectOption(
                label=meta["label"],
                value=key,
                emoji=meta["emoji"],
            )
            for key, meta in REWARD_TYPES.items()
        ]

        super().__init__(
            placeholder="Choose what winners receive...",
            options=options,
            min_values=1,
            max_values=1,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                f"{EMOJI['error']} This isn't your session.",
                ephemeral=True,
            )
            return

        await self.on_pick(interaction, self.values[0])


class RewardConfigView(discord.ui.View):
    """First step: select a reward type."""

    def __init__(self, owner_id: int, on_pick) -> None:
        super().__init__(timeout=180)
        self.add_item(RewardTypeSelect(owner_id, on_pick))


# ============================================================
# Reward detail modals
# ============================================================

class GachaRewardModal(discord.ui.Modal, title="Gacha Card Reward"):
    template = discord.ui.TextInput(
        label="Which Gacha Card?",
        placeholder="Card name or template ID, e.g. Amon / amon",
        max_length=100,
    )

    def __init__(self, on_submit) -> None:
        super().__init__()
        self._on_submit = on_submit

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await self._on_submit(interaction, str(self.template))


class CoinsRewardModal(discord.ui.Modal, title="Coins Reward"):
    amount = discord.ui.TextInput(
        label="Amount of coins (per winner)",
        placeholder="e.g. 500",
        max_length=10,
    )

    def __init__(self, on_submit) -> None:
        super().__init__()
        self._on_submit = on_submit

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await self._on_submit(interaction, str(self.amount))


class XPRewardModal(discord.ui.Modal, title="XP Reward"):
    amount = discord.ui.TextInput(
        label="Amount of XP (per winner)",
        placeholder="e.g. 1000",
        max_length=10,
    )

    def __init__(self, on_submit) -> None:
        super().__init__()
        self._on_submit = on_submit

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await self._on_submit(interaction, str(self.amount))


class OtherRewardModal(discord.ui.Modal, title="Other Reward"):
    description = discord.ui.TextInput(
        label="What do winners receive?",
        placeholder="e.g. Discord Nitro (1 month) — fulfilled manually",
        style=discord.TextStyle.paragraph,
        max_length=200,
    )

    def __init__(self, on_submit) -> None:
        super().__init__()
        self._on_submit = on_submit

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await self._on_submit(interaction, str(self.description))


# ============================================================
# Card verification
# ============================================================

async def resolve_gacha_card(query: str) -> Optional[dict[str, Any]]:
    """Look up a card against the live Lunar catalog."""

    result = await lunarapi.get_gacha_cards()

    if not result:
        return None

    cards = result.get("cards")

    if not isinstance(cards, list):
        return None

    query_norm = query.strip().lower()

    for card in cards:
        if str(card.get("template_id", "")).lower() == query_norm:
            return card

    for card in cards:
        if str(card.get("name", "")).lower() == query_norm:
            return card

    for card in cards:
        if query_norm in str(card.get("name", "")).lower():
            return card

    return None


# ============================================================
# Reward distribution
# ============================================================

async def _get_lunar_identity(
    discord_id: int,
) -> Optional[tuple[str, Optional[str]]]:
    """Resolve a Discord user to their linked, verified Lunar account."""

    account = await db.account_links.get(discord_id)

    if account is None or not account.verified:
        return None

    lunar_uuid = getattr(account, "lunar_uuid", None)

    if lunar_uuid is None:
        return None

    metadata = json_loads(
        getattr(account, "metadata", None),
        default={},
    )

    username = (
        metadata.get("username")
        if isinstance(metadata, dict)
        else None
    )

    return str(lunar_uuid), username


async def _grant_one(
    bot: commands.Bot,
    guild: Optional[discord.Guild],
    winner_id: str,
    rewards: dict[str, Any],
) -> dict[str, Any]:
    """Apply the configured reward to one winner; return the outcome."""

    reward_type = rewards.get("type")
    meta = REWARD_TYPES.get(reward_type, {})

    result: dict[str, Any] = {
        "user_id": winner_id,
        "type": reward_type,
        "success": False,
        "label": meta.get("label", "Reward"),
        "emoji": meta.get("emoji", EMOJI["gift"]),
        "reason": None,
    }

    try:
        discord_id = int(winner_id)

        # Manual fulfillment requires no linked Lunar account.
        if reward_type == "other":
            result["success"] = True
            result["detail"] = rewards.get("description", "a reward")
            return result

        identity = await _get_lunar_identity(discord_id)

        if identity is None:
            result["reason"] = "not linked/verified"
            return result

        lunar_uuid, lunar_username = identity

        if reward_type == "coins":
            amount = int(rewards.get("amount", 0))
            grant = await lunarapi.set_coins(
                lunar_uuid, amount, action="add"
            )

            if grant:
                result["success"] = True
                result["detail"] = f"{amount:,} coins"
            else:
                result["reason"] = "coins API call failed"

        elif reward_type == "xp":
            amount = int(rewards.get("amount", 0))
            grant = await lunarapi.give_xp(lunar_uuid, amount)

            if grant:
                result["success"] = True
                result["detail"] = f"{amount:,} XP"
            else:
                result["reason"] = "XP API call failed"

        elif reward_type == "gacha":
            template_id = str(rewards.get("template_id", ""))
            card_name = rewards.get("card_name", template_id)

            if not lunar_username:
                result["reason"] = (
                    "no cached Lunar username for this account — "
                    "gifting via lunar_uuid as a fallback; verify "
                    "this works with /api/gacha/admin/gift"
                )
                recipient = lunar_uuid
            else:
                recipient = lunar_username

            grant = await lunarapi.gift_gacha_card(
                recipient, template_id
            )

            if grant and grant.get("success"):
                result["success"] = True
                result["detail"] = card_name
            else:
                result["reason"] = (
                    grant.get("message")
                    if grant
                    else "gacha gift API call failed"
                )

        elif reward_type == "donator_role":
            if guild is None:
                result["reason"] = "no guild context"
                return result

            member = guild.get_member(discord_id)

            if member is None:
                try:
                    member = await guild.fetch_member(discord_id)
                except discord.HTTPException:
                    member = None

            if member is None:
                result["reason"] = "winner is not in the server"
                return result

            role = guild.get_role(WEBSITE_DONATOR_ROLE_ID)

            if role is None:
                result["reason"] = "donator role not found in guild"
                return result

            await member.add_roles(role, reason="Giveaway reward")

            result["success"] = True
            result["detail"] = role.name

        else:
            result["reason"] = f"unknown reward type: {reward_type}"

    except Exception as error:
        result["reason"] = f"unexpected error: {error}"

        from cogs.utilities.error import log_error

        await log_error(
            error,
            context="Giveaway Reward Grant",
            bot=bot,
            guild=guild,
            extra={
                "Winner ID": winner_id,
                "Reward Type": reward_type,
            },
        )

    return result


async def apply_giveaway_rewards(
    bot: commands.Bot,
    guild: Optional[discord.Guild],
    winner_ids: list[str],
    rewards: dict[str, Any],
) -> list[dict[str, Any]]:
    """Grant the configured reward to each winner and return outcomes."""

    results = []

    for winner_id in winner_ids:
        results.append(
            await _grant_one(bot, guild, winner_id, rewards)
        )

    return results


def build_rewards_summary(results: list[dict[str, Any]]) -> str:
    """Build a per-winner summary showing successful and failed rewards."""

    if not results:
        return ""

    lines = []

    for entry in results:
        mention = f"<@{entry['user_id']}>"
        emoji = entry.get("emoji", EMOJI["gift"])

        if entry["success"]:
            detail = entry.get("detail", entry["label"])
            lines.append(
                f"{EMOJI['approved']} {mention} received "
                f"{emoji} **{detail}**"
            )
        else:
            lines.append(
                f"{EMOJI['error']} {mention} — "
                f"**{entry.get('reason', 'failed')}**"
            )

    return "\n".join(lines)
