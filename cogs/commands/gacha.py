from __future__ import annotations

import logging
import time
from typing import Any, Optional

import discord
from discord import app_commands
from discord.ext import commands

from cogs.utilities.emoji import EMOJI
from cogs.utilities.lunarapi import lunarapi


log = logging.getLogger("lunar.gacha")


# ============================================================
# Configuration
# ============================================================

CACHE_SECONDS = 120  # admin card/cover lists change rarely
PAGE_SIZE = 10
VIEW_TIMEOUT = 300

# ------------------------------------------------------------
# Rarity design — one star emoji + one embed color per rarity,
# climbing in intensity from common (1) to mythic (6+).
# ------------------------------------------------------------

RARITY_STAR_EMOJI = {
    1: EMOJI["greenstar"],
    2: EMOJI["greenstar"],
    3: EMOJI["cyanstar"],
    4: EMOJI["purplestar"],
    5: EMOJI["orangestar"],
    6: EMOJI["redstar"],
}

RARITY_COLOR = {
    1: 0x9CA3AF,  # slate — common
    2: 0x22C55E,  # green — uncommon
    3: 0x38BDF8,  # cyan  — rare
    4: 0xA855F7,  # purple — epic
    5: 0xF97316,  # orange — legendary
    6: 0xEF4444,  # red   — mythic
}

DEFAULT_STAR = EMOJI["pinkstar"]
DEFAULT_COLOR = 0xF5C518


def rarity_stars(rarity: int) -> str:
    emoji = RARITY_STAR_EMOJI.get(rarity, DEFAULT_STAR)
    return emoji * max(1, rarity)


def rarity_color(rarity: int) -> discord.Color:
    return discord.Color(
        RARITY_COLOR.get(rarity, DEFAULT_COLOR)
    )


# ============================================================
# Small in-memory cache
# ============================================================

class _Cache:
    def __init__(self) -> None:
        self.cards: list[dict[str, Any]] = []
        self.covers: list[dict[str, Any]] = []
        self.cards_at: float = 0.0
        self.covers_at: float = 0.0

    def cards_stale(self) -> bool:
        return (time.monotonic() - self.cards_at) > CACHE_SECONDS

    def covers_stale(self) -> bool:
        return (time.monotonic() - self.covers_at) > CACHE_SECONDS


_cache = _Cache()


async def _get_cards(*, force: bool = False) -> list[dict[str, Any]]:
    if not force and _cache.cards and not _cache.cards_stale():
        return _cache.cards

    result = await lunarapi.get_gacha_cards()

    if result is None:
        # Serve stale data over nothing, if we have it.
        return _cache.cards

    cards = result.get("cards")

    if isinstance(cards, list):
        _cache.cards = cards
        _cache.cards_at = time.monotonic()

    return _cache.cards


async def _get_covers(*, force: bool = False) -> list[dict[str, Any]]:
    if not force and _cache.covers and not _cache.covers_stale():
        return _cache.covers

    result = await lunarapi.get_gacha_card_covers()

    if result is None:
        return _cache.covers

    covers = result.get("cards")

    if isinstance(covers, list):
        _cache.covers = covers
        _cache.covers_at = time.monotonic()

    return _cache.covers


def _find_card(
    cards: list[dict[str, Any]],
    query: str,
) -> Optional[dict[str, Any]]:
    query = query.strip().lower()

    if not query:
        return None

    for card in cards:
        if str(card.get("template_id", "")).lower() == query:
            return card

    for card in cards:
        if str(card.get("name", "")).lower() == query:
            return card

    for card in cards:
        if query in str(card.get("name", "")).lower():
            return card

    return None


# ============================================================
# Embed builders
# ============================================================

def build_card_embed(card: dict[str, Any]) -> discord.Embed:
    name = str(card.get("name", "Unknown Card"))
    rarity = int(card.get("rarity") or 0)
    template_id = str(card.get("template_id", "unknown"))
    card_class = str(card.get("class", "Unknown"))
    image_url = card.get("image_url") or None

    copies = card.get("copies")
    copies_text = "Unlimited" if copies is None else f"{copies:,}"

    embed = discord.Embed(
        title=f"{rarity_stars(rarity)}  {name}",
        description=f"**{card_class}** • `{template_id}`",
        color=rarity_color(rarity),
    )

    embed.add_field(
        name="⚔️ Attack",
        value=f"`{card.get('base_attack', 0)}` "
        f"(+{card.get('growth_attack', 0)}/lvl)",
        inline=True,
    )
    embed.add_field(
        name="🛡️ Defense",
        value=f"`{card.get('base_defense', 0)}` "
        f"(+{card.get('growth_defense', 0)}/lvl)",
        inline=True,
    )
    embed.add_field(
        name="❤️ HP",
        value=f"`{card.get('base_hp', 0)}` "
        f"(+{card.get('growth_hp', 0)}/lvl)",
        inline=True,
    )

    embed.add_field(
        name="Max Level",
        value=f"`{card.get('max_level', '?')}`",
        inline=True,
    )
    embed.add_field(
        name="Copies",
        value=f"`{copies_text}`",
        inline=True,
    )
    embed.add_field(
        name="Custom",
        value="Yes" if card.get("custom") else "No",
        inline=True,
    )

    skills = card.get("skills")

    if isinstance(skills, list) and skills:
        skill_lines = []

        for skill in skills[:4]:
            skill_name = str(skill.get("name", "Unknown"))
            skill_desc = str(skill.get("description", ""))

            if len(skill_desc) > 300:
                skill_desc = skill_desc[:297] + "..."

            skill_lines.append(f"**{skill_name}**\n{skill_desc}")

        embed.add_field(
            name="✨ Skills",
            value="\n\n".join(skill_lines)[:1024],
            inline=False,
        )

    if image_url:
        embed.set_thumbnail(url=image_url)

    embed.set_footer(text="☾ Lunar Gacha")

    return embed


def build_serials_embed(
    template_id: str,
    data: dict[str, Any],
    page: int,
) -> discord.Embed:
    name = str(data.get("name", template_id))
    rarity = int(data.get("rarity") or 0)
    listed = data.get("listed", 0)
    total = data.get("total", 0)
    max_copies = data.get("max_copies")

    max_copies_text = (
        "Unlimited" if max_copies is None else f"{max_copies:,}"
    )

    entries = data.get("entries")
    entries = entries if isinstance(entries, list) else []

    embed = discord.Embed(
        title=f"{rarity_stars(rarity)}  {name} — Owners",
        description=(
            f"**Listed:** `{listed}` • "
            f"**Minted:** `{total}` • "
            f"**Max Copies:** `{max_copies_text}`"
        ),
        color=rarity_color(rarity),
    )

    image_url = data.get("image_url")

    if image_url:
        embed.set_thumbnail(url=image_url)

    start = page * PAGE_SIZE
    page_entries = entries[start : start + PAGE_SIZE]

    if not page_entries:
        embed.add_field(
            name="No copies minted yet",
            value="Nobody owns a copy of this card.",
            inline=False,
        )

    else:
        lines = []

        for entry in page_entries:
            mint = entry.get("mint_number", "?")
            username = entry.get("username", "Unknown")
            lines.append(f"`#{mint}` — **{username}**")

        embed.add_field(
            name=f"Copies ({start + 1}-{start + len(page_entries)} "
            f"of {len(entries)})",
            value="\n".join(lines),
            inline=False,
        )

    total_pages = max(1, -(-len(entries) // PAGE_SIZE))

    embed.set_footer(
        text=f"☾ Lunar Gacha • Page {page + 1}/{total_pages}"
    )

    return embed


def build_browse_embed(
    covers: list[dict[str, Any]],
    page: int,
) -> discord.Embed:
    start = page * PAGE_SIZE
    page_covers = covers[start : start + PAGE_SIZE]

    embed = discord.Embed(
        title="🎴 Gacha Card Catalog",
        color=DEFAULT_COLOR,
    )

    if not page_covers:
        embed.description = "No cards found."

    else:
        lines = []

        for card in page_covers:
            rarity = int(card.get("rarity") or 0)
            name = str(card.get("name", "Unknown"))
            template_id = str(card.get("template_id", "unknown"))

            lines.append(
                f"{rarity_stars(rarity)} **{name}** "
                f"— `{template_id}`"
            )

        embed.description = "\n".join(lines)

    total_pages = max(1, -(-len(covers) // PAGE_SIZE))

    embed.set_footer(
        text=f"☾ Lunar Gacha • Page {page + 1}/{total_pages} "
        f"• {len(covers)} cards"
    )

    return embed


# ============================================================
# Pagination view
# ============================================================

class GachaPageView(discord.ui.View):
    """
    Generic Previous/Next paginator shared by /gacha owners and
    /gacha list — the two commands whose data can span more than
    one page.
    """

    def __init__(
        self,
        owner_id: int,
        total_items: int,
        render,
    ) -> None:
        super().__init__(timeout=VIEW_TIMEOUT)

        self.owner_id = owner_id
        self.total_items = total_items
        self.render = render
        self.page = 0

        self.previous_button = discord.ui.Button(
            label="Previous",
            emoji=EMOJI["left"],
            style=discord.ButtonStyle.secondary,
        )
        self.next_button = discord.ui.Button(
            label="Next",
            emoji=EMOJI["right"],
            style=discord.ButtonStyle.secondary,
        )

        self.previous_button.callback = self._previous
        self.next_button.callback = self._next

        self.add_item(self.previous_button)
        self.add_item(self.next_button)

        self._update_buttons()

    def _max_page(self) -> int:
        return max(0, -(-self.total_items // PAGE_SIZE) - 1)

    def _update_buttons(self) -> None:
        self.previous_button.disabled = self.page <= 0
        self.next_button.disabled = self.page >= self._max_page()

    async def interaction_check(
        self,
        interaction: discord.Interaction,
    ) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                f"{EMOJI['error']} This isn't your session.",
                ephemeral=True,
            )
            return False

        return True

    async def _previous(self, interaction: discord.Interaction) -> None:
        self.page = max(0, self.page - 1)
        await self._refresh(interaction)

    async def _next(self, interaction: discord.Interaction) -> None:
        self.page = min(self._max_page(), self.page + 1)
        await self._refresh(interaction)

    async def _refresh(self, interaction: discord.Interaction) -> None:
        self._update_buttons()

        await interaction.response.edit_message(
            embed=self.render(self.page),
            view=self,
        )

    async def on_timeout(self) -> None:
        for item in self.children:
            item.disabled = True


# ============================================================
# Gacha Cog
# ============================================================

class Gacha(commands.Cog):
    """
    /gacha — card lookup, ownership, and catalog browsing, backed
    by the Lunar gacha admin/public endpoints via lunarapi.
    """

    group = app_commands.Group(
        name="gacha",
        description="Look up Lunar gacha cards.",
    )

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # --------------------------------------------------------
    # Autocomplete
    # --------------------------------------------------------

    async def card_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        cards = await _get_covers()

        current = current.strip().lower()

        matches = [
            card
            for card in cards
            if current in str(card.get("name", "")).lower()
            or current in str(card.get("template_id", "")).lower()
        ]

        return [
            app_commands.Choice(
                name=str(card.get("name", "Unknown"))[:100],
                value=str(card.get("template_id", "")),
            )
            for card in matches[:25]
        ]

    # --------------------------------------------------------
    # /gacha card
    # --------------------------------------------------------

    @group.command(
        name="card",
        description="Look up a gacha card's stats and skills.",
    )
    @app_commands.describe(template="Card name or template ID")
    @app_commands.autocomplete(template=card_autocomplete)
    async def card(
        self,
        interaction: discord.Interaction,
        template: str,
    ) -> None:
        await interaction.response.defer()

        cards = await _get_cards()

        if not cards:
            await interaction.followup.send(
                f"{EMOJI['error']} Couldn't reach the Lunar gacha API."
            )
            return

        card = _find_card(cards, template)

        if card is None:
            await interaction.followup.send(
                f"{EMOJI['error']} No card matching `{template}` found."
            )
            return

        await interaction.followup.send(embed=build_card_embed(card))

    # --------------------------------------------------------
    # /gacha owners
    # --------------------------------------------------------

    @group.command(
        name="owners",
        description="See who owns copies of a gacha card.",
    )
    @app_commands.describe(template="Card name or template ID")
    @app_commands.autocomplete(template=card_autocomplete)
    async def owners(
        self,
        interaction: discord.Interaction,
        template: str,
    ) -> None:
        await interaction.response.defer()

        cards = await _get_cards()
        card = _find_card(cards, template) if cards else None

        template_id = (
            str(card.get("template_id"))
            if card is not None
            else template.strip().lower()
        )

        data = await lunarapi.get_gacha_serials(template_id)

        if data is None:
            await interaction.followup.send(
                f"{EMOJI['error']} No serials found for "
                f"`{template_id}` — check the card name/ID."
            )
            return

        entries = data.get("entries")
        total_items = len(entries) if isinstance(entries, list) else 0

        view = GachaPageView(
            interaction.user.id,
            total_items,
            lambda page: build_serials_embed(
                template_id, data, page
            ),
        )

        await interaction.followup.send(
            embed=build_serials_embed(template_id, data, 0),
            view=view,
        )

    # --------------------------------------------------------
    # /gacha list
    # --------------------------------------------------------

    @group.command(
        name="list",
        description="Browse the full gacha card catalog.",
    )
    @app_commands.describe(rarity="Only show cards of this rarity (1-6+)")
    async def list_cards(
        self,
        interaction: discord.Interaction,
        rarity: Optional[int] = None,
    ) -> None:
        await interaction.response.defer()

        covers = await _get_covers()

        if not covers:
            await interaction.followup.send(
                f"{EMOJI['error']} Couldn't reach the Lunar gacha API."
            )
            return

        if rarity is not None:
            covers = [
                card
                for card in covers
                if int(card.get("rarity") or 0) == rarity
            ]

            if not covers:
                await interaction.followup.send(
                    f"{EMOJI['error']} No cards of rarity `{rarity}` found."
                )
                return

        covers = sorted(
            covers,
            key=lambda c: (
                -int(c.get("rarity") or 0),
                str(c.get("name", "")),
            ),
        )

        view = GachaPageView(
            interaction.user.id,
            len(covers),
            lambda page: build_browse_embed(covers, page),
        )

        await interaction.followup.send(
            embed=build_browse_embed(covers, 0),
            view=view,
        )


# ============================================================
# Cog Setup
# ============================================================

async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Gacha(bot))
