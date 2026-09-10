from __future__ import annotations

import asyncio
import re
from typing import Optional

import aiohttp
import discord

from discord import app_commands
from discord.ext import commands

from utilities.database import db
from cogs.utilities.emoji import EMOJI
from cogs.utilities.randomizer import (
    CryptographicRandomizer,
)


# ============================================================
# CONFIG
# ============================================================

LUNAR_PROFILE_API = (
    "https://api.lunarx.to/api/animes/profile"
)

ANILIST_API = (
    "https://graphql.anilist.co"
)

REQUEST_TIMEOUT = aiohttp.ClientTimeout(
    total=15,
    connect=5,
    sock_connect=5,
    sock_read=10,
)

LOADING_TIME = 2.5


# ============================================================
# ANILIST QUERIES
# ============================================================

RANDOM_ANIME_QUERY = """
query {
    Page(
        page: 1
        perPage: 50
    ) {
        media(
            type: ANIME
            sort: RANDOM
            isAdult: false
        ) {
            id

            title {
                romaji
                english
                native
            }

            description(asHtml: false)

            episodes
            duration
            status
            averageScore
            genres

            coverImage {
                large
            }

            siteUrl
        }
    }
}
"""


RECOMMENDATION_QUERY = """
query ($id: Int!) {
    Media(
        id: $id
        type: ANIME
    ) {
        id

        title {
            romaji
            english
            native
        }

        description(asHtml: false)

        episodes
        duration
        status
        averageScore
        genres

        coverImage {
            large
        }

        siteUrl

        recommendations(
            sort: RATING_DESC
            perPage: 25
        ) {
            nodes {
                mediaRecommendation {
                    id

                    title {
                        romaji
                        english
                        native
                    }

                    description(asHtml: false)

                    episodes
                    duration
                    status
                    averageScore
                    genres

                    coverImage {
                        large
                    }

                    siteUrl
                }
            }
        }
    }
}
"""


# ============================================================
# TEXT HELPERS
# ============================================================

def clean_text(
    value: Optional[str],
) -> str:

    if not value:
        return ""

    value = re.sub(
        r"<[^>]+>",
        "",
        value,
    )

    value = re.sub(
        r"\s+",
        " ",
        value,
    )

    return value.strip()


def get_title(
    anime: dict,
) -> str:

    title = anime.get(
        "title",
        {},
    )

    return (
        title.get("english")
        or title.get("romaji")
        or title.get("native")
        or "Unknown Anime"
    )


def get_url(
    anime: dict,
) -> str:

    anime_id = anime.get(
        "id"
    )

    return (
        anime.get("siteUrl")
        or f"https://anilist.co/anime/{anime_id}"
    )


# ============================================================
# ANIME EMBED
# ============================================================

def build_anime_embed(
    anime: dict,
    *,
    heading: str,
    color: discord.Color,
) -> discord.Embed:

    description = clean_text(
        anime.get(
            "description"
        )
    )

    if len(description) > 700:
        description = (
            description[:697]
            + "..."
        )

    if not description:
        description = (
            "No description available."
        )

    embed = discord.Embed(
        title=(
            f"{heading} "
            f"{get_title(anime)}"
        ),
        url=get_url(
            anime
        ),
        description=description,
        color=color,
    )

    cover = (
        anime.get(
            "coverImage",
            {},
        ).get(
            "large"
        )
    )

    if cover:
        embed.set_thumbnail(
            url=cover
        )

    score = anime.get(
        "averageScore"
    )

    score_text = (
        f"{score}/100"
        if score is not None
        else "N/A"
    )

    episodes = (
        anime.get(
            "episodes"
        )
        or "?"
    )

    duration = (
        anime.get(
            "duration"
        )
        or "?"
    )

    status = (
        anime.get(
            "status"
        )
        or "UNKNOWN"
    )

    genres = anime.get(
        "genres"
    ) or []

    genre_text = (
        ", ".join(
            genres[:5]
        )
        if genres
        else "Unknown"
    )

    embed.add_field(
        name="Information",
        value=(
            f"**Episodes:** `{episodes}`\n"
            f"**Duration:** `{duration} min`\n"
            f"**Status:** `{status}`\n"
            f"**Score:** `{score_text}`"
        ),
        inline=True,
    )

    embed.add_field(
        name="Genres",
        value=genre_text,
        inline=True,
    )

    embed.set_footer(
        text="Lunar Anime • Powered by AniList"
    )

    return embed


# ============================================================
# HTTP
# ============================================================

async def anilist_request(
    session: aiohttp.ClientSession,
    query: str,
    variables: Optional[dict] = None,
) -> Optional[dict]:

    try:

        async with session.post(
            ANILIST_API,
            json={
                "query": query,
                "variables": variables or {},
            },
        ) as response:

            if response.status != 200:
                return None

            payload = await response.json()

            if payload.get("errors"):
                return None

            data = payload.get(
                "data"
            )

            if not isinstance(
                data,
                dict,
            ):
                return None

            return data

    except (
        aiohttp.ClientError,
        asyncio.TimeoutError,
    ):

        return None


async def fetch_lunar_profile(
    username: str,
) -> Optional[dict]:

    try:

        async with aiohttp.ClientSession(
            timeout=REQUEST_TIMEOUT
        ) as session:

            async with session.get(
                LUNAR_PROFILE_API,
                params={
                    "username": username,
                },
            ) as response:

                if response.status != 200:
                    return None

                payload = await response.json()

                if not isinstance(
                    payload,
                    dict,
                ):
                    return None

                profile = payload.get(
                    "data"
                )

                if not isinstance(
                    profile,
                    dict,
                ):
                    return None

                return profile

    except (
        aiohttp.ClientError,
        asyncio.TimeoutError,
    ):

        return None


# ============================================================
# DATABASE
# ============================================================

async def get_linked_username(
    user_id: int,
) -> Optional[str]:

    try:

        return await db.account_links.get_username(
            str(user_id)
        )

    except Exception:
        return None


# ============================================================
# WATCHLIST
# ============================================================

def extract_anime_ids(
    value,
) -> set[int]:

    found: set[int] = set()

    def walk(
        current,
    ):

        if isinstance(
            current,
            dict,
        ):

            for key in (
                "animeId",
                "anime_id",
                "mediaId",
                "media_id",
                "anilistId",
                "anilist_id",
            ):

                candidate = current.get(
                    key
                )

                if isinstance(
                    candidate,
                    int,
                ):

                    found.add(
                        candidate
                    )

                elif (
                    isinstance(
                        candidate,
                        str,
                    )
                    and candidate.isdigit()
                ):

                    found.add(
                        int(candidate)
                    )

            if current.get(
                "type"
            ) == "ANIME":

                anime_id = current.get(
                    "id"
                )

                if isinstance(
                    anime_id,
                    int,
                ):

                    found.add(
                        anime_id
                    )

                elif (
                    isinstance(
                        anime_id,
                        str,
                    )
                    and anime_id.isdigit()
                ):

                    found.add(
                        int(anime_id)
                    )

            for child in current.values():
                walk(
                    child
                )

        elif isinstance(
            current,
            list,
        ):

            for child in current:
                walk(
                    child
                )

    walk(
        value
    )

    return found


def extract_watchlist_ids(
    profile: dict,
) -> set[int]:

    anilist_profile = profile.get(
        "anilist_profile"
    )

    if not anilist_profile:
        return set()

    if isinstance(
        anilist_profile,
        dict,
    ):

        preferred = (
            "watchlist",
            "watch_list",
            "anime_watchlist",
            "media",
            "lists",
            "entries",
        )

        for key in preferred:

            value = (
                anilist_profile.get(
                    key
                )
            )

            if value:

                ids = extract_anime_ids(
                    value
                )

                if ids:
                    return ids

    return extract_anime_ids(
        anilist_profile
    )


# ============================================================
# RANDOM ANIME
# ============================================================

async def get_random_anime() -> Optional[dict]:

    async with aiohttp.ClientSession(
        timeout=REQUEST_TIMEOUT
    ) as session:

        data = await anilist_request(
            session,
            RANDOM_ANIME_QUERY,
        )

        if not data:
            return None

        media = (
            data.get(
                "Page",
                {},
            ).get(
                "media",
                [],
            )
        )

        media = [
            anime
            for anime in media
            if anime.get("id") is not None
        ]

        if not media:
            return None

        anime_ids = [
            str(
                anime["id"]
            )
            for anime in media
        ]

        selection = (
            CryptographicRandomizer.select(
                anime_ids,
                1,
                context="anime.random",
            )
        )

        selected_id = int(
            selection.winners[0]
        )

        for anime in media:

            if anime.get(
                "id"
            ) == selected_id:

                return anime

    return None


# ============================================================
# RECOMMENDATION ENGINE
# ============================================================

async def get_recommendation(
    watchlist_ids: set[int],
) -> Optional[dict]:

    if not watchlist_ids:
        return None

    seed_ids = list(
        watchlist_ids
    )

    seed_count = min(
        5,
        len(seed_ids),
    )

    seed_selection = (
        CryptographicRandomizer.select(
            [
                str(
                    anime_id
                )
                for anime_id in seed_ids
            ],
            seed_count,
            context="anime.rec.seeds",
        )
    )

    selected_seeds = [
        int(
            value
        )
        for value in seed_selection.winners
    ]

    candidates: dict[int, dict] = {}

    async with aiohttp.ClientSession(
        timeout=REQUEST_TIMEOUT
    ) as session:

        for seed_id in selected_seeds:

            data = await anilist_request(
                session,
                RECOMMENDATION_QUERY,
                {
                    "id": seed_id,
                },
            )

            if not data:
                continue

            media = data.get(
                "Media"
            )

            if not media:
                continue

            nodes = (
                media
                .get(
                    "recommendations",
                    {},
                )
                .get(
                    "nodes",
                    [],
                )
            )

            for node in nodes:

                anime = (
                    node.get(
                        "mediaRecommendation"
                    )
                )

                if not anime:
                    continue

                anime_id = anime.get(
                    "id"
                )

                if not anime_id:
                    continue

                if anime_id in watchlist_ids:
                    continue

                candidates[
                    anime_id
                ] = anime

    if not candidates:
        return None

    ranked = sorted(
        candidates.values(),
        key=lambda anime: (
            anime.get(
                "averageScore"
            )
            or 0
        ),
        reverse=True,
    )

    top_candidates = ranked[
        :min(
            10,
            len(ranked),
        )
    ]

    if not top_candidates:
        return None

    selected = (
        CryptographicRandomizer.select(
            [
                str(
                    anime["id"]
                )
                for anime in top_candidates
            ],
            1,
            context="anime.rec.result",
        )
    )

    selected_id = int(
        selected.winners[0]
    )

    for anime in top_candidates:

        if anime.get(
            "id"
        ) == selected_id:

            return anime

    return None


# ============================================================
# MODE SELECTION VIEW
# ============================================================

class AnimeModeView(
    discord.ui.View
):

    def __init__(
        self,
        cog: "Anime",
    ):

        super().__init__(
            timeout=60
        )

        self.cog = cog

    @discord.ui.button(
        label="Recommendation",
        style=discord.ButtonStyle.primary,
        emoji="💜",
    )
    async def recommendation(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):

        await self.cog.run_recommendation(
            interaction
        )

    @discord.ui.button(
        label="Random Anime",
        style=discord.ButtonStyle.secondary,
        emoji="🎲",
    )
    async def random(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):

        await self.cog.run_random(
            interaction
        )

    async def on_timeout(
        self,
    ):

        for item in self.children:
            item.disabled = True


# ============================================================
# ANIME COG
# ============================================================

class Anime(
    commands.Cog
):

    def __init__(
        self,
        bot: commands.Bot,
    ):

        self.bot = bot

    # ========================================================
    # /ANIME
    # ========================================================

    @app_commands.command(
        name="anime",
        description="Get an anime recommendation or random anime.",
    )
    @app_commands.describe(
        mode="Choose recommendation or random.",
    )
    @app_commands.choices(
        mode=[
            app_commands.Choice(
                name="Recommendation",
                value="rec",
            ),
            app_commands.Choice(
                name="Random",
                value="random",
            ),
        ]
    )
    async def anime(
        self,
        interaction: discord.Interaction,
        mode: Optional[
            app_commands.Choice[str]
        ] = None,
    ):

        # ----------------------------------------------------
        # No mode selected
        # ----------------------------------------------------

        if mode is None:

            embed = discord.Embed(
                title=(
                    f"{EMOJI['lunar']} "
                    "Anime Archives"
                ),
                description=(
                    f"{EMOJI['aniheart']} "
                    "What are you looking for?\n\n"
                    "**Recommendation**\n"
                    "> I'll analyze your Lunar watchlist "
                    "and find something suited to it.\n\n"
                    "**Random Anime**\n"
                    "> Let the archive choose something "
                    "completely random."
                ),
                color=discord.Color.blurple(),
            )

            embed.set_footer(
                text="Choose an option below"
            )

            await interaction.response.send_message(
                embed=embed,
                view=AnimeModeView(
                    self
                ),
                ephemeral=True,
            )

            return

        if mode.value == "rec":

            await self.run_recommendation(
                interaction
            )

            return

        await self.run_random(
            interaction
        )

    # ========================================================
    # RANDOM
    # ========================================================

    async def run_random(
        self,
        interaction: discord.Interaction,
    ):

        # ----------------------------------------------------
        # INITIAL RESPONSE
        # ----------------------------------------------------

        if not interaction.response.is_done():

            await interaction.response.send_message(
                f"{EMOJI['loading']} "
                "Searching the anime archives...",
                ephemeral=True,
            )

        else:

            await interaction.edit_original_response(
                content=(
                    f"{EMOJI['loading']} "
                    "Searching the anime archives..."
                ),
                embed=None,
                view=None,
            )

        await asyncio.sleep(
            LOADING_TIME
        )

        # ----------------------------------------------------
        # FETCH
        # ----------------------------------------------------

        anime = await get_random_anime()

        if not anime:

            embed = discord.Embed(
                title=(
                    f"{EMOJI['error']} "
                    "Random Search Failed"
                ),
                description=(
                    f"{EMOJI['denied']} "
                    "AniList didn't return a valid "
                    "anime right now.\n\n"
                    "Please try again."
                ),
                color=discord.Color.red(),
            )

            await interaction.edit_original_response(
                content=None,
                embed=embed,
                view=None,
            )

            return

        # ----------------------------------------------------
        # RESULT
        # ----------------------------------------------------

        embed = build_anime_embed(
            anime,
            heading=(
                f"{EMOJI['lunar']} Random Pick:"
            ),
            color=discord.Color.blurple(),
        )

        embed.description = (
            f"{EMOJI['approved']} "
            "The archive selected this anime for you.\n\n"
            + (
                embed.description
                or ""
            )
        )

        await interaction.edit_original_response(
            content=None,
            embed=embed,
            view=None,
        )

    # ========================================================
    # RECOMMENDATION
    # ========================================================

    async def run_recommendation(
        self,
        interaction: discord.Interaction,
    ):

        # ----------------------------------------------------
        # INITIAL RESPONSE
        # ----------------------------------------------------

        if not interaction.response.is_done():

            await interaction.response.send_message(
                f"{EMOJI['loading']} "
                "Checking your Lunar account...",
                ephemeral=True,
            )

        else:

            await interaction.edit_original_response(
                content=(
                    f"{EMOJI['loading']} "
                    "Checking your Lunar account..."
                ),
                embed=None,
                view=None,
            )

        await asyncio.sleep(
            LOADING_TIME
        )

        # ----------------------------------------------------
        # LINKED USERNAME
        # ----------------------------------------------------

        username = await get_linked_username(
            interaction.user.id
        )

        if not username:

            embed = discord.Embed(
                title=(
                    f"{EMOJI['question']} "
                    "Lunar Account Required"
                ),
                description=(
                    f"{EMOJI['denied']} "
                    "You need a verified Lunar account "
                    "to use personalized recommendations.\n\n"
                    "Use `/link` to connect your account."
                ),
                color=discord.Color.orange(),
            )

            await interaction.edit_original_response(
                content=None,
                embed=embed,
                view=None,
            )

            return

        # ----------------------------------------------------
        # PROFILE
        # ----------------------------------------------------

        await interaction.edit_original_response(
            content=(
                f"{EMOJI['loading']} "
                f"Reading `{username}`'s Lunar profile..."
            ),
            embed=None,
            view=None,
        )

        await asyncio.sleep(
            LOADING_TIME
        )

        profile = await fetch_lunar_profile(
            username
        )

        if not profile:

            embed = discord.Embed(
                title=(
                    f"{EMOJI['error']} "
                    "Lunar Profile Unavailable"
                ),
                description=(
                    f"{EMOJI['denied']} "
                    f"I couldn't retrieve `{username}` "
                    "from Lunar right now."
                ),
                color=discord.Color.red(),
            )

            await interaction.edit_original_response(
                content=None,
                embed=embed,
                view=None,
            )

            return

        # ----------------------------------------------------
        # WATCHLIST
        # ----------------------------------------------------

        watchlist_ids = (
            extract_watchlist_ids(
                profile
            )
        )

        if not watchlist_ids:

            embed = discord.Embed(
                title=(
                    f"{EMOJI['question']} "
                    "AniList Watchlist Unavailable"
                ),
                description=(
                    f"{EMOJI['denied']} "
                    "Lunar returned your profile, but "
                    "there isn't an AniList watchlist "
                    "available to analyze.\n\n"
                    "Connect AniList to Lunar and try again."
                ),
                color=discord.Color.orange(),
            )

            embed.set_footer(
                text=f"Lunar Account • {username}"
            )

            await interaction.edit_original_response(
                content=None,
                embed=embed,
                view=None,
            )

            return

        # ----------------------------------------------------
        # RECOMMENDATION
        # ----------------------------------------------------

        await interaction.edit_original_response(
            content=(
                f"{EMOJI['loading']} "
                f"Analyzed `{len(watchlist_ids):,}` anime.\n"
                "Finding something you haven't watched..."
            ),
            embed=None,
            view=None,
        )

        await asyncio.sleep(
            LOADING_TIME
        )

        recommendation = (
            await get_recommendation(
                watchlist_ids
            )
        )

        if not recommendation:

            embed = discord.Embed(
                title=(
                    f"{EMOJI['question']} "
                    "No Recommendation Found"
                ),
                description=(
                    f"{EMOJI['denied']} "
                    "I couldn't find a suitable anime "
                    "outside your watchlist."
                ),
                color=discord.Color.orange(),
            )

            await interaction.edit_original_response(
                content=None,
                embed=embed,
                view=None,
            )

            return

        # ----------------------------------------------------
        # RESULT
        # ----------------------------------------------------

        embed = build_anime_embed(
            recommendation,
            heading=(
                f"{EMOJI['aniheart']} "
                "Recommended:"
            ),
            color=discord.Color.gold(),
        )

        embed.description = (
            f"{EMOJI['approved']} "
            "Based on your Lunar watchlist.\n"
            f"{EMOJI['moon']} "
            f"Analyzed `{len(watchlist_ids):,}` anime.\n\n"
            + (
                embed.description
                or ""
            )
        )

        embed.set_footer(
            text=(
                f"Lunar Recommendation • {username}"
            )
        )

        await interaction.edit_original_response(
            content=None,
            embed=embed,
            view=None,
        )


# ============================================================
# SETUP
# ============================================================

async def setup(
    bot: commands.Bot,
):

    await bot.add_cog(
        Anime(bot)
    )
