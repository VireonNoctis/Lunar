from __future__ import annotations

import logging
import os
import uuid
from collections import deque
from datetime import datetime, timezone
from typing import Any

import discord
from discord.ext import commands
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from cogs.utilities.api import (
    API_PREFIX,
    protected,
    register_router,
    start_api,
    unregister_router,
)


log = logging.getLogger("Lunar.Gacha")

GACHA_CHANNEL_ID = int(
    os.getenv(
        "LUNAR_GACHA_CARD_CHANNEL_ID",
        "69",
    )
)

router = APIRouter(
    prefix=f"{API_PREFIX}/gacha",
    tags=["Gacha"],
)

gacha_cog: "GachaIntegration | None" = None


class CardsRequest(BaseModel):
    class Config:
        extra = "allow"

    cards: list[dict[str, Any]] = Field(
        min_length=1,
        max_length=100,
    )
    source: str = "lunarx"
    event_id: str | None = None
    post_to_discord: bool = True


class GachaEvent(BaseModel):
    class Config:
        extra = "allow"

    event: str
    data: dict[str, Any] = Field(
        default_factory=dict,
    )
    post_to_discord: bool = True


@router.post("/cards")
async def receive_cards(
    payload: CardsRequest,
    _auth: None = Depends(protected),
) -> dict[str, Any]:
    if gacha_cog is None:
        raise HTTPException(
            status_code=503,
            detail="Gacha integration is not ready.",
        )

    result = await gacha_cog.process_cards(
        payload.cards,
        source=payload.source,
        event_id=payload.event_id,
        post_to_discord=payload.post_to_discord,
    )

    return {
        "ok": True,
        **result,
    }


@router.post("/card")
async def receive_card(
    card: dict[str, Any],
    _auth: None = Depends(protected),
) -> dict[str, Any]:
    if gacha_cog is None:
        raise HTTPException(
            status_code=503,
            detail="Gacha integration is not ready.",
        )

    result = await gacha_cog.process_cards(
        [card],
        source="lunarx",
        event_id=None,
        post_to_discord=True,
    )

    return {
        "ok": True,
        **result,
    }


@router.post("/event")
async def receive_event(
    payload: GachaEvent,
    _auth: None = Depends(protected),
) -> dict[str, Any]:
    if gacha_cog is None:
        raise HTTPException(
            status_code=503,
            detail="Gacha integration is not ready.",
        )

    result = await gacha_cog.process_event(
        payload.event,
        payload.data,
        post_to_discord=payload.post_to_discord,
    )

    return {
        "ok": True,
        **result,
    }


@router.get("/recent")
async def recent_cards(
    limit: int = 25,
    _auth: None = Depends(protected),
) -> dict[str, Any]:
    if gacha_cog is None:
        raise HTTPException(
            status_code=503,
            detail="Gacha integration is not ready.",
        )

    limit = max(
        1,
        min(limit, 100),
    )

    return {
        "ok": True,
        "count": min(
            limit,
            len(gacha_cog.recent_cards),
        ),
        "cards": list(
            gacha_cog.recent_cards
        )[-limit:],
    }


class GachaIntegration(commands.Cog):
    """LunarX gacha API integration."""

    def __init__(
        self,
        bot: commands.Bot,
    ):
        self.bot = bot
        self.recent_cards: deque[
            dict[str, Any]
        ] = deque(maxlen=250)

        global gacha_cog
        gacha_cog = self

    async def cog_load(self) -> None:
        register_router(
            router,
            "gacha",
        )

        await start_api()

        log.info(
            "Gacha API registered at %s/gacha",
            API_PREFIX,
        )

    async def cog_unload(self) -> None:
        global gacha_cog

        unregister_router("gacha")

        if gacha_cog is self:
            gacha_cog = None

    async def process_event(
        self,
        event: str,
        data: dict[str, Any],
        *,
        post_to_discord: bool = True,
    ) -> dict[str, Any]:
        normalized = event.strip().lower()

        if normalized in {
            "card",
            "card.created",
            "card_created",
        }:
            card = data.get("card")

            if not isinstance(
                card,
                dict,
            ):
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "Event data must contain "
                        "a 'card' object."
                    ),
                )

            return await self.process_cards(
                [card],
                source="lunarx",
                event_id=None,
                post_to_discord=post_to_discord,
            )

        if normalized in {
            "cards",
            "cards.created",
            "cards_created",
        }:
            cards = data.get("cards")

            if (
                not isinstance(cards, list)
                or not all(
                    isinstance(card, dict)
                    for card in cards
                )
            ):
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "Event data must contain "
                        "a 'cards' array of objects."
                    ),
                )

            return await self.process_cards(
                cards,
                source="lunarx",
                event_id=None,
                post_to_discord=post_to_discord,
            )

        log.info(
            "Received unhandled gacha event: %s",
            normalized,
        )

        return {
            "event": normalized,
            "accepted": True,
            "processed": 0,
            "posted": 0,
            "failed": 0,
        }

    async def process_cards(
        self,
        cards: list[dict[str, Any]],
        *,
        source: str,
        event_id: str | None,
        post_to_discord: bool,
    ) -> dict[str, Any]:
        batch_id = (
            event_id
            or str(uuid.uuid4())
        )

        processed = 0
        posted = 0
        failed = 0

        channel = None

        if post_to_discord:
            channel = self.bot.get_channel(
                GACHA_CHANNEL_ID
            )

            if channel is None:
                raise HTTPException(
                    status_code=503,
                    detail=(
                        f"Gacha channel "
                        f"{GACHA_CHANNEL_ID} "
                        "was not found."
                    ),
                )

            if not isinstance(
                channel,
                discord.abc.Messageable,
            ):
                raise HTTPException(
                    status_code=503,
                    detail=(
                        "Configured gacha channel "
                        "is not messageable."
                    ),
                )

        for card in cards:
            if not isinstance(
                card,
                dict,
            ):
                failed += 1
                continue

            processed += 1

            snapshot = dict(card)

            snapshot[
                "_batch_id"
            ] = batch_id

            snapshot[
                "_source"
            ] = source

            snapshot[
                "_received_at"
            ] = datetime.now(
                timezone.utc
            ).isoformat()

            self.recent_cards.append(
                snapshot
            )

            if not post_to_discord:
                continue

            try:
                await channel.send(
                    embed=self.build_card_embed(
                        card
                    )
                )
                posted += 1

            except Exception:
                failed += 1

                log.exception(
                    "Failed to post gacha card: %r",
                    card,
                )

        return {
            "batch_id": batch_id,
            "source": source,
            "processed": processed,
            "posted": posted,
            "failed": failed,
        }

    @staticmethod
    def build_card_embed(
        card: dict[str, Any],
    ) -> discord.Embed:
        name = str(
            card.get(
                "name",
                "Unknown Card",
            )
        )

        rarity = int(
            card.get(
                "rarity",
                0,
            )
            or 0
        )

        stars = str(
            card.get(
                "stars",
                "★" * rarity,
            )
        )

        role = str(
            card.get(
                "role"
            )
            or card.get(
                "class"
            )
            or "Unknown"
        )

        element = str(
            card.get(
                "element",
                "Unknown",
            )
        )

        image_url = card.get(
            "image_url"
        )

        template_id = str(
            card.get(
                "template_id",
                "Unknown",
            )
        )

        submitted_by = str(
            card.get(
                "submitted_by",
                "Unknown",
            )
        )

        copies = int(
            card.get(
                "copies",
                0,
            )
            or 0
        )

        votes = int(
            card.get(
                "votes",
                0,
            )
            or 0
        )

        attack = int(
            card.get(
                "base_attack",
                0,
            )
            or 0
        )

        defense = int(
            card.get(
                "base_defense",
                0,
            )
            or 0
        )

        hp = int(
            card.get(
                "base_hp",
                0,
            )
            or 0
        )

        embed = discord.Embed(
            title=f"{stars}  {name}",
            description=(
                f"**{role}**\n"
                f"**Element:** `{element}`"
            ),
            color=discord.Color.gold(),
        )

        if image_url:
            embed.set_thumbnail(
                url=str(image_url)
            )

        embed.add_field(
            name="⚔️ Attack",
            value=f"**{attack:,}**",
            inline=True,
        )

        embed.add_field(
            name="🛡️ Defense",
            value=f"**{defense:,}**",
            inline=True,
        )

        embed.add_field(
            name="❤️ HP",
            value=f"**{hp:,}**",
            inline=True,
        )

        embed.add_field(
            name="🌙 Card Information",
            value=(
                f"**Rarity:** {stars}\n"
                f"**Role:** {role}\n"
                f"**Element:** {element}\n"
                f"**Template:** "
                f"`{template_id}`"
            ),
            inline=False,
        )

        abilities = card.get(
            "abilities",
            []
        )

        if isinstance(
            abilities,
            list,
        ):
            valid_abilities = [
                ability
                for ability in abilities
                if isinstance(
                    ability,
                    dict,
                )
            ]

            for index, ability in enumerate(
                valid_abilities,
                start=1,
            ):
                ability_name = str(
                    ability.get(
                        "name",
                        "Ability",
                    )
                )

                ability_description = str(
                    ability.get(
                        "description",
                        "No description available.",
                    )
                )

                if len(
                    ability_description
                ) > 1024:
                    ability_description = (
                        ability_description[:1021]
                        + "..."
                    )

                if len(
                    valid_abilities
                ) == 1:
                    field_name = (
                        f"✨ {ability_name}"
                    )
                else:
                    field_name = (
                        f"✨ Ability {index} "
                        f"— {ability_name}"
                    )

                embed.add_field(
                    name=field_name,
                    value=ability_description,
                    inline=False,
                )

        elif card.get(
            "skill_name"
        ):
            skill_name = str(
                card["skill_name"]
            )

            skill_description = str(
                card.get(
                    "skill_description",
                    "No description available.",
                )
            )

            if len(
                skill_description
            ) > 1024:
                skill_description = (
                    skill_description[:1021]
                    + "..."
                )

            embed.add_field(
                name=f"✨ {skill_name}",
                value=skill_description,
                inline=False,
            )

        embed.add_field(
            name="📦 Availability",
            value=(
                f"**Copies:** "
                f"`{copies:,}`\n"
                f"**Votes:** "
                f"`{votes:,}`"
            ),
            inline=True,
        )

        embed.add_field(
            name="👤 Submitted By",
            value=f"`{submitted_by}`",
            inline=True,
        )

        embed.set_footer(
            text=f"Lunar • {template_id}"
        )

        return embed


async def setup(
    bot: commands.Bot,
) -> None:
    await bot.add_cog(
        GachaIntegration(bot)
    )
