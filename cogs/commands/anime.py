from __future__ import annotations

import asyncio
import json
import re
import time
from typing import Optional

import aiohttp
import discord

from discord import app_commands
from discord.ext import commands

from cogs.utilities.database import db
from cogs.utilities.emoji import EMOJI
from cogs.utilities.randomizer import (
    CryptographicRandomizer,
)
from cogs.utilities.lunarapi import lunarapi


# ============================================================
# This file combines what used to be cogs/commands/anime.py and
# cogs/commands/search.py into one module:
#   - /anime  — AniList-backed recommendation/random anime tool
#   - /search — Lunar catalog search (manga + novels)
# ============================================================

# ============================================================
# CONFIG
# ============================================================

LUNAR_PROFILE_ENDPOINT = "/api/animes/profile"

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
                color
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
            color
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
                        color
                    }

                    siteUrl
                }
            }
        }
    }
}
"""


TITLE_SEARCH_QUERY = """
query ($search: String) {
    Page(
        page: 1
        perPage: 10
    ) {
        media(
            type: ANIME
            search: $search
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
                color
            }

            siteUrl
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
    color: Optional[discord.Color] = None,
) -> discord.Embed:

    resolved_color = (
        color
        if color is not None
        else discord.Color(resolve_color(anime))
    )

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
        color=resolved_color,
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

        payload = await lunarapi.get(
            LUNAR_PROFILE_ENDPOINT,
            authed=False,
            params={
                "username": username,
            },
        )

    except lunarapi.LunarAPIError:

        return None

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
# TITLE SEARCH
# ============================================================

async def search_anime_anilist(
    query: str,
) -> list[dict]:
    """
    Search AniList by title. Returns up to 10 matching anime
    media dicts (same shape as get_random_anime()'s results, so
    they drop straight into build_anime_embed()).
    """

    async with aiohttp.ClientSession(
        timeout=REQUEST_TIMEOUT
    ) as session:

        data = await anilist_request(
            session,
            TITLE_SEARCH_QUERY,
            {"search": query},
        )

    if not data:
        return []

    media = data.get("Page", {}).get("media", [])

    if not isinstance(media, list):
        return []

    return [
        anime
        for anime in media
        if anime.get("id") is not None
    ]


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
        cog: "AnimeHelper",
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
# ANIME HELPER COG (internal — no slash commands of its own;
# holds the recommendation/random flow /browse delegates to)
# ============================================================

class AnimeHelper(
    commands.Cog
):

    def __init__(
        self,
        bot: commands.Bot,
    ):

        self.bot = bot

    # ========================================================
    # ANIME MODE CHOOSER (no title given to /browse)
    # ========================================================

    async def show_anime_mode_chooser(
        self,
        interaction: discord.Interaction,
    ):

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
# CONSTANTS
# ============================================================

LUNAR_BASE = "https://lunarx.to"

CACHE_NAMESPACE = "manga_search"
NOVEL_CACHE_NAMESPACE = "novel_search"

SEARCH_CACHE_TTL = 300
MANGA_CACHE_TTL = 300
NOVEL_CACHE_TTL = 300

RESULT_LIMIT = 50
PAGE_SIZE = 10

SESSION_TIMEOUT = 60


# ============================================================
# MEMORY SESSION
# ============================================================

_sessions: dict[str, dict] = {}


# ============================================================
# HELPERS
# ============================================================

def cache_key(
    prefix: str,
    value: str,
) -> str:
    return f"{prefix}:{value.lower().strip()}"


def utc_timestamp() -> int:
    return int(time.time())


def parse_color(
    value: str | None,
) -> int | None:
    if not value:
        return None

    value = value.strip()

    if value.startswith("#"):
        value = value[1:]

    if len(value) != 6:
        return None

    try:
        return int(
            value,
            16,
        )
    except ValueError:
        return None


def gradient_fallback(
    title: str,
) -> int:
    hash_value = 0

    for char in title:
        hash_value = (
            hash_value * 31
            + ord(char)
        ) & 0xFFFFFFFF

    colors = (
        0x8B5CF6,
        0x3B82F6,
        0x10B981,
        0xF59E0B,
        0xEF4444,
    )

    return colors[
        hash_value
        % len(colors)
    ]


def resolve_color(
    media: dict,
) -> int:
    theme = (
        media.get("theme_color")
        or media.get("themecolor")
    )

    if not theme:
        cover = media.get("coverImage")

        if isinstance(cover, dict):
            theme = cover.get("color")

    parsed = parse_color(
        theme
    )

    if parsed is not None:
        return parsed

    title_value = media.get(
        "title",
        "lunar",
    )

    if isinstance(title_value, dict):
        title_value = (
            title_value.get("english")
            or title_value.get("romaji")
            or title_value.get("native")
            or "lunar"
        )

    return gradient_fallback(
        str(title_value)
    )


def truncate(
    value: str,
    length: int,
) -> str:
    if len(value) <= length:
        return value

    return value[
        :length - 3
    ] + "..."


def format_chapter(
    chapter: dict,
) -> str:
    chapter_number = chapter.get(
        "chapter_number",
        "?",
    )

    uploaded_at = chapter.get(
        "uploaded_at"
    )

    if uploaded_at:

        try:
            parsed = discord.utils.parse_time(
                uploaded_at
            )

            if parsed:

                timestamp = int(
                    parsed.timestamp()
                )

                return (
                    f"Ch {chapter_number} • "
                    f"<t:{timestamp}:R>"
                )

        except (ValueError, TypeError):
            pass

    return (
        f"Ch {chapter_number}"
    )


# ============================================================
# DATABASE CACHE
# ============================================================

async def get_cached(
    key: str,
    namespace: str = CACHE_NAMESPACE,
):
    try:
        cached = await db.extensions.get(
            namespace,
            key,
            "cache",
        )

    except Exception:
        return None

    if not cached:
        return None

    expires_at = cached.get(
        "expires_at"
    )

    if expires_at is not None:

        try:

            if int(expires_at) < utc_timestamp():
                return None

        except (
            TypeError,
            ValueError,
        ):
            return None

    return cached.get(
        "data"
    )


async def set_cached(
    key: str,
    data,
    ttl: int,
    namespace: str = CACHE_NAMESPACE,
):
    try:
        await db.extensions.set(
            namespace,
            key,
            "cache",
            {
                "expires_at": (
                    utc_timestamp()
                    + ttl
                ),
                "data": data,
            },
        )

    except Exception:
        pass


# ============================================================
# LUNAR API
# ============================================================

async def lunar_get(
    endpoint: str,
) -> dict | None:
    try:
        result = await lunarapi.get(
            endpoint,
            authed=False,
        )

    except lunarapi.LunarAPIError:
        return None

    return result if isinstance(result, dict) else None


async def search_manga(
    query: str,
) -> list[dict]:

    key = cache_key(
        "search",
        query,
    )

    cached = await get_cached(
        key
    )

    if cached is not None:
        return cached

    data = await lunar_get(
        f"/api/manga/search?q={aiohttp.helpers.quote(query)}"
    )

    if not data:
        return []

    results = data.get(
        "manga",
        [],
    )

    if not isinstance(
        results,
        list,
    ):
        return []

    results = results[
        :RESULT_LIMIT
    ]

    await set_cached(
        key,
        results,
        SEARCH_CACHE_TTL,
    )

    return results


async def fetch_manga(
    slug: str,
) -> dict | None:

    key = cache_key(
        "manga",
        slug,
    )

    cached = await get_cached(
        key
    )

    if cached is not None:
        return cached

    data = await lunar_get(
        f"/api/manga/{aiohttp.helpers.quote(slug)}"
    )

    if not data:
        return None

    await set_cached(
        key,
        data,
        MANGA_CACHE_TTL,
    )

    return data


async def search_novels(
    query: str,
) -> list[dict]:

    key = cache_key(
        "novel_search",
        query,
    )

    cached = await get_cached(
        key,
        namespace=NOVEL_CACHE_NAMESPACE,
    )

    if cached is not None:
        return cached

    data = await lunarapi.search_novels(
        query
    )

    if not data:
        return []

    results = data.get(
        "novels",
        [],
    )

    if not isinstance(
        results,
        list,
    ):
        return []

    results = results[
        :RESULT_LIMIT
    ]

    await set_cached(
        key,
        results,
        SEARCH_CACHE_TTL,
        namespace=NOVEL_CACHE_NAMESPACE,
    )

    return results


async def fetch_novel(
    slug: str,
) -> dict | None:

    key = cache_key(
        "novel",
        slug,
    )

    cached = await get_cached(
        key,
        namespace=NOVEL_CACHE_NAMESPACE,
    )

    if cached is not None:
        return cached

    data = await lunarapi.get_novel(
        slug
    )

    if not data:
        return None

    novel = data.get("novel")

    if not isinstance(novel, dict):
        return None

    await set_cached(
        key,
        novel,
        NOVEL_CACHE_TTL,
        namespace=NOVEL_CACHE_NAMESPACE,
    )

    return novel


# ============================================================
# SESSION
# ============================================================

def set_session(
    session_id: str,
    data: dict,
):
    _sessions[
        session_id
    ] = {
        **data,
        "expires_at": (
            utc_timestamp()
            + SESSION_TIMEOUT
        ),
    }


def get_session(
    session_id: str,
) -> dict | None:

    session = _sessions.get(
        session_id
    )

    if not session:
        return None

    if (
        session["expires_at"]
        < utc_timestamp()
    ):

        _sessions.pop(
            session_id,
            None,
        )

        return None

    session["expires_at"] = (
        utc_timestamp()
        + SESSION_TIMEOUT
    )

    return session


def delete_session(
    session_id: str,
):
    _sessions.pop(
        session_id,
        None,
    )


# ============================================================
# EMBEDS
# ============================================================

def build_home(
    results: list[dict],
    query: str,
    page: int = 0,
) -> discord.Embed:

    start = page * PAGE_SIZE
    end = start + PAGE_SIZE

    visible = results[
        start:end
    ]

    embed = discord.Embed(
        title=(
            f"{EMOJI['mangatype']} Lunar Manga Catalog"
        ),
        description=(
            f"Search: **{query}**\n"
            f"Results: **{len(results)}**\n\n"
            "Select a title below."
        ),
        color=0x8B5CF6,
    )

    if visible:

        lines = []

        for index, manga in enumerate(
            visible,
            start=start + 1,
        ):

            title = truncate(
                str(
                    manga.get(
                        "title",
                        "Unknown",
                    )
                ),
                80,
            )

            lines.append(
                f"`{index:02}` {title}"
            )

        embed.add_field(
            name="Titles",
            value="\n".join(
                lines
            ),
            inline=False,
        )

    embed.set_footer(
        text=(
            f"Page {page + 1} • "
            f"{min(end, len(results))}/{len(results)}"
        )
    )

    return embed


def build_info(
    manga: dict,
    chapters: list[dict],
) -> discord.Embed:

    latest = (
        chapters[0]
        if chapters
        else {}
    )

    uploader = latest.get(
        "uploader_profile"
    ) or {}

    embed = discord.Embed(
        title=(
            f"{EMOJI['moon']} "
            f"{manga.get('title', 'Unknown')}"
        ),
        url=(
            f"{LUNAR_BASE}/manga/"
            f"{manga.get('slug', '')}"
        ),
        description=truncate(
            str(
                manga.get(
                    "description",
                    "No description",
                )
                or "No description"
            ),
            350,
        ),
        color=resolve_color(
            manga
        ),
    )

    cover_url = manga.get(
        "cover_url"
    )

    banner_url = manga.get(
        "banner_url"
    )

    if cover_url:
        embed.set_thumbnail(
            url=cover_url
        )

    if banner_url:
        embed.set_image(
            url=banner_url
        )

    embed.add_field(
        name=f"{EMOJI['question']} Info",
        value=(
            f"Author: "
            f"{manga.get('author', '?')}\n"
            f"Artist: "
            f"{manga.get('artist', '?')}\n"
            f"Status: "
            f"{manga.get('publication_status', '?')}\n"
            f"Year: "
            f"{manga.get('publication_year', '?')}"
        ),
        inline=False,
    )

    embed.add_field(
        name="Stats",
        value=(
            f"Chapters: "
            f"{len(chapters)}\n"
            f"Rating: "
            f"{manga.get('rating', '?')}"
        ),
        inline=True,
    )

    embed.add_field(
        name="Uploader",
        value=(
            f"User: "
            f"{uploader.get('username', '?')}\n"
            f"Level: "
            f"{uploader.get('level', '?')}"
        ),
        inline=True,
    )

    return embed


def build_chapters(
    manga: dict,
    chapters: list[dict],
    page: int = 0,
) -> discord.Embed:

    visible = chapters[
        page * PAGE_SIZE:
        page * PAGE_SIZE + PAGE_SIZE
    ]

    embed = discord.Embed(
        title=(
            f"{EMOJI['aniheart']} "
            "Chapters"
        ),
        description=(
            "\n".join(
                format_chapter(
                    chapter
                )
                for chapter in visible
            )
            if visible
            else "No chapters available."
        ),
        color=resolve_color(
            manga
        ),
    )

    embed.set_footer(
        text=(
            f"Page {page + 1} • "
            f"{len(chapters)} total chapters"
        )
    )

    return embed


def build_languages(
    manga: dict,
    chapters: list[dict],
) -> discord.Embed:

    languages = sorted(
        {
            str(
                chapter.get(
                    "language",
                    "Unknown",
                )
            )
            for chapter in chapters
        }
    )

    return discord.Embed(
        title=(
            f"{EMOJI['moon']} Languages"
        ),
        description=(
            ", ".join(
                languages
            )
            if languages
            else "No languages available."
        ),
        color=resolve_color(
            manga
        ),
    )


def build_stats(
    manga: dict,
    chapters: list[dict],
) -> discord.Embed:

    return discord.Embed(
        title=(
            f"{EMOJI['moon']} Stats"
        ),
        description=(
            f"Rating: "
            f"{manga.get('rating', '?')}\n"
            f"Status: "
            f"{manga.get('publication_status', '?')}\n"
            f"Year: "
            f"{manga.get('publication_year', '?')}\n"
            f"Chapters: "
            f"{len(chapters)}"
        ),
        color=resolve_color(
            manga
        ),
    )


# ============================================================
# NOVEL EMBEDS
# ============================================================

def parse_json_list(
    value,
) -> list[str]:
    """
    The novel API stores genres/themes/alternative_titles as a
    JSON-encoded string (e.g. '["Action","Adventure"]') rather
    than a real array. Decode it defensively — malformed or
    missing data just becomes an empty list.
    """

    if isinstance(value, list):
        return [str(item) for item in value]

    if not value:
        return []

    try:
        parsed = json.loads(str(value))

    except (TypeError, ValueError, json.JSONDecodeError):
        return []

    if isinstance(parsed, list):
        return [str(item) for item in parsed]

    return []


def build_novel_home(
    results: list[dict],
    query: str,
    page: int = 0,
) -> discord.Embed:

    start = page * PAGE_SIZE
    end = start + PAGE_SIZE

    visible = results[start:end]

    embed = discord.Embed(
        title=f"{EMOJI['noveltype']} Lunar Novel Catalog",
        description=(
            f"Search: **{query}**\n"
            f"Results: **{len(results)}**\n\n"
            "Select a title below."
        ),
        color=0x8B5CF6,
    )

    if visible:

        lines = []

        for index, novel in enumerate(visible, start=start + 1):
            title = truncate(
                str(novel.get("title", "Unknown")), 80
            )

            lines.append(f"`{index:02}` {title}")

        embed.add_field(
            name="Titles",
            value="\n".join(lines),
            inline=False,
        )

    embed.set_footer(
        text=(
            f"Page {page + 1} • "
            f"{min(end, len(results))}/{len(results)}"
        )
    )

    return embed


def build_novel_info(
    novel: dict,
) -> discord.Embed:

    genres = parse_json_list(novel.get("genres"))
    themes = parse_json_list(novel.get("themes"))

    embed = discord.Embed(
        title=f"{EMOJI['noveltype']} {novel.get('title', 'Unknown')}",
        url=f"{LUNAR_BASE}/novel/{novel.get('slug', '')}",
        description=truncate(
            str(
                novel.get("description", "No description")
                or "No description"
            ),
            350,
        ),
        color=resolve_color(novel),
    )

    cover_url = novel.get("cover_url")
    banner_url = novel.get("banner_url")

    if cover_url:
        embed.set_thumbnail(url=cover_url)

    if banner_url:
        embed.set_image(url=banner_url)

    embed.add_field(
        name=f"{EMOJI['question']} Info",
        value=(
            f"Author: {novel.get('author', '?')}\n"
            f"Artist: {novel.get('artist', '?')}\n"
            f"Status: {novel.get('publication_status', '?')}\n"
            f"Year: {novel.get('publication_year', '?')}"
        ),
        inline=False,
    )

    embed.add_field(
        name="Stats",
        value=(
            f"Rating: {novel.get('rating', '?')}\n"
            f"Demographic: {novel.get('demographic', '?')}"
        ),
        inline=True,
    )

    embed.add_field(
        name="Publisher",
        value=(
            f"Publisher: {novel.get('publisher', '?')}\n"
            f"Serialization: {novel.get('serialization', '?')}"
        ),
        inline=True,
    )

    if genres:
        embed.add_field(
            name="Genres",
            value=truncate(", ".join(genres), 200),
            inline=False,
        )

    return embed


def build_novel_genres(
    novel: dict,
) -> discord.Embed:

    genres = parse_json_list(novel.get("genres"))
    themes = parse_json_list(novel.get("themes"))
    alt_titles = parse_json_list(novel.get("alternative_titles"))

    embed = discord.Embed(
        title=f"{EMOJI['noveltype']} Genres & Themes",
        color=resolve_color(novel),
    )

    embed.add_field(
        name="Genres",
        value=", ".join(genres) if genres else "None listed.",
        inline=False,
    )

    embed.add_field(
        name="Themes",
        value=", ".join(themes) if themes else "None listed.",
        inline=False,
    )

    if alt_titles:
        embed.add_field(
            name="Alternative Titles",
            value=", ".join(alt_titles),
            inline=False,
        )

    return embed


# ============================================================
# NAVIGATION VIEW
# ============================================================

class MangaNavigationView(
    discord.ui.View
):

    def __init__(
        self,
        cog: "Browse",
        session_id: str,
        user_id: int,
    ):

        super().__init__(
            timeout=SESSION_TIMEOUT
        )

        self.cog = cog
        self.session_id = session_id
        self.user_id = user_id

    async def interaction_check(
        self,
        interaction: discord.Interaction,
    ) -> bool:

        if interaction.user.id != self.user_id:

            await interaction.response.send_message(
                f"{EMOJI['denied']} "
                "This search menu belongs to another user.",
                ephemeral=True,
            )

            return False

        session = get_session(
            self.session_id
        )

        if session is None:

            await interaction.response.send_message(
                f"{EMOJI['denied']} "
                "This search session has expired.",
                ephemeral=True,
            )

            return False

        return True

    @discord.ui.button(
        label="Info",
        style=discord.ButtonStyle.primary,
    )
    async def info(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):

        await self.cog.show_info(
            interaction,
            self.session_id,
        )

    @discord.ui.button(
        label="Chapters",
        style=discord.ButtonStyle.secondary,
    )
    async def chapters(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):

        await self.cog.show_chapters(
            interaction,
            self.session_id,
        )

    @discord.ui.button(
        label="Languages",
        style=discord.ButtonStyle.secondary,
    )
    async def languages(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):

        await self.cog.show_languages(
            interaction,
            self.session_id,
        )

    @discord.ui.button(
        label="Stats",
        style=discord.ButtonStyle.secondary,
    )
    async def stats(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):

        await self.cog.show_stats(
            interaction,
            self.session_id,
        )

    @discord.ui.button(
        label="Close",
        style=discord.ButtonStyle.danger,
    )
    async def close(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):

        delete_session(
            self.session_id
        )

        await interaction.response.edit_message(
            content=(
                f"{EMOJI['approved']} "
                "Search closed."
            ),
            embed=None,
            view=None,
        )

        self.stop()


# ============================================================
# SEARCH SELECT
# ============================================================

class MangaSelect(
    discord.ui.Select
):

    def __init__(
        self,
        cog: "Browse",
        session_id: str,
        user_id: int,
        results: list[dict],
        page: int,
    ):

        self.cog = cog
        self.session_id = session_id
        self.user_id = user_id
        self.results = results

        start = page * PAGE_SIZE

        visible = results[
            start:
            start + PAGE_SIZE
        ]

        options = []

        for manga in visible:

            title = str(
                manga.get(
                    "title",
                    "Unknown",
                )
            )

            slug = str(
                manga.get(
                    "slug",
                    "",
                )
            )

            if not slug:
                continue

            options.append(
                discord.SelectOption(
                    label=truncate(
                        title,
                        100,
                    ),
                    value=slug,
                )
            )

        super().__init__(
            placeholder="Choose a manga...",
            options=options,
            custom_id=(
                f"manga_select:{session_id}"
            ),
        )

    async def callback(
        self,
        interaction: discord.Interaction,
    ):

        if (
            interaction.user.id
            != self.user_id
        ):

            await interaction.response.send_message(
                f"{EMOJI['denied']} "
                "This search menu belongs to another user.",
                ephemeral=True,
            )

            return

        session = get_session(
            self.session_id
        )

        if session is None:

            await interaction.response.send_message(
                f"{EMOJI['denied']} "
                "This search session has expired.",
                ephemeral=True,
            )

            return

        slug = self.values[0]

        await interaction.response.defer()

        manga = await fetch_manga(
            slug
        )

        if not manga:

            await interaction.followup.send(
                f"{EMOJI['error']} "
                "Failed to load that manga.",
                ephemeral=True,
            )

            return

        chapters = manga.get(
            "data",
            [],
        )

        if not isinstance(
            chapters,
            list,
        ):
            chapters = []

        set_session(
            self.session_id,
            {
                "user_id": self.user_id,
                "manga": manga,
                "chapters": chapters,
                "view": "info",
            },
        )

        await interaction.edit_original_response(
            content=(
                f"{EMOJI['approved']} "
                "Manga loaded."
            ),
            embed=build_info(
                manga,
                chapters,
            ),
            view=MangaNavigationView(
                self.cog,
                self.session_id,
                self.user_id,
            ),
        )


class MangaSearchView(
    discord.ui.View
):

    def __init__(
        self,
        cog: "Browse",
        session_id: str,
        user_id: int,
        results: list[dict],
    ):

        super().__init__(
            timeout=SESSION_TIMEOUT
        )

        self.add_item(
            MangaSelect(
                cog,
                session_id,
                user_id,
                results,
                0,
            )
        )


# ============================================================
# NOVEL NAVIGATION VIEW
# ============================================================

class NovelNavigationView(
    discord.ui.View
):

    def __init__(
        self,
        cog: "Browse",
        session_id: str,
        user_id: int,
    ):

        super().__init__(timeout=SESSION_TIMEOUT)

        self.cog = cog
        self.session_id = session_id
        self.user_id = user_id

    async def interaction_check(
        self,
        interaction: discord.Interaction,
    ) -> bool:

        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                f"{EMOJI['denied']} "
                "This search menu belongs to another user.",
                ephemeral=True,
            )
            return False

        session = get_session(self.session_id)

        if session is None:
            await interaction.response.send_message(
                f"{EMOJI['denied']} "
                "This search session has expired.",
                ephemeral=True,
            )
            return False

        return True

    @discord.ui.button(
        label="Info",
        style=discord.ButtonStyle.primary,
    )
    async def info(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        await self.cog.show_novel_info(
            interaction, self.session_id
        )

    @discord.ui.button(
        label="Genres & Themes",
        style=discord.ButtonStyle.secondary,
    )
    async def genres(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        await self.cog.show_novel_genres(
            interaction, self.session_id
        )

    @discord.ui.button(
        label="Close",
        style=discord.ButtonStyle.danger,
    )
    async def close(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        delete_session(self.session_id)

        await interaction.response.edit_message(
            content=f"{EMOJI['approved']} Search closed.",
            embed=None,
            view=None,
        )

        self.stop()


# ============================================================
# NOVEL SEARCH SELECT
# ============================================================

class NovelSelect(
    discord.ui.Select
):

    def __init__(
        self,
        cog: "Browse",
        session_id: str,
        user_id: int,
        results: list[dict],
        page: int,
    ):

        self.cog = cog
        self.session_id = session_id
        self.user_id = user_id
        self.results = results

        start = page * PAGE_SIZE

        visible = results[start:start + PAGE_SIZE]

        options = []

        for novel in visible:
            title = str(novel.get("title", "Unknown"))
            slug = str(novel.get("slug", ""))

            if not slug:
                continue

            options.append(
                discord.SelectOption(
                    label=truncate(title, 100),
                    value=slug,
                )
            )

        super().__init__(
            placeholder="Choose a novel...",
            options=options,
            custom_id=f"novel_select:{session_id}",
        )

    async def callback(
        self,
        interaction: discord.Interaction,
    ):

        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                f"{EMOJI['denied']} "
                "This search menu belongs to another user.",
                ephemeral=True,
            )
            return

        session = get_session(self.session_id)

        if session is None:
            await interaction.response.send_message(
                f"{EMOJI['denied']} "
                "This search session has expired.",
                ephemeral=True,
            )
            return

        slug = self.values[0]

        await interaction.response.defer()

        novel = await fetch_novel(slug)

        if not novel:
            await interaction.followup.send(
                f"{EMOJI['error']} Failed to load that novel.",
                ephemeral=True,
            )
            return

        set_session(
            self.session_id,
            {
                "user_id": self.user_id,
                "novel": novel,
                "view": "info",
            },
        )

        await interaction.edit_original_response(
            content=f"{EMOJI['approved']} Novel loaded.",
            embed=build_novel_info(novel),
            view=NovelNavigationView(
                self.cog,
                self.session_id,
                self.user_id,
            ),
        )


class NovelSearchView(
    discord.ui.View
):

    def __init__(
        self,
        cog: "Browse",
        session_id: str,
        user_id: int,
        results: list[dict],
    ):

        super().__init__(timeout=SESSION_TIMEOUT)

        self.add_item(
            NovelSelect(
                cog,
                session_id,
                user_id,
                results,
                0,
            )
        )


# ============================================================
# ANIME SEARCH SELECT (title-search disambiguation)
# ============================================================

class AnimeSelect(
    discord.ui.Select
):

    def __init__(
        self,
        cog: "Browse",
        user_id: int,
        results: list[dict],
    ):

        self.cog = cog
        self.user_id = user_id
        self.results = results

        options = []

        for anime in results[:25]:
            anime_id = anime.get("id")

            if anime_id is None:
                continue

            options.append(
                discord.SelectOption(
                    label=truncate(get_title(anime), 100),
                    value=str(anime_id),
                )
            )

        super().__init__(
            placeholder="Choose an anime...",
            options=options,
        )

    async def callback(
        self,
        interaction: discord.Interaction,
    ):

        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                f"{EMOJI['denied']} "
                "This search menu belongs to another user.",
                ephemeral=True,
            )
            return

        selected_id = self.values[0]

        anime = next(
            (
                item
                for item in self.results
                if str(item.get("id")) == selected_id
            ),
            None,
        )

        if anime is None:
            await interaction.response.send_message(
                f"{EMOJI['error']} That anime could no longer "
                "be found in the results.",
                ephemeral=True,
            )
            return

        embed = build_anime_embed(
            anime,
            heading=f"{EMOJI['lunar']} Result:",
        )

        await interaction.response.edit_message(
            content=f"{EMOJI['approved']} Search complete.",
            embed=embed,
            view=None,
        )


class AnimeSearchView(
    discord.ui.View
):

    def __init__(
        self,
        cog: "Browse",
        user_id: int,
        results: list[dict],
    ):

        super().__init__(timeout=SESSION_TIMEOUT)

        self.add_item(
            AnimeSelect(
                cog,
                user_id,
                results,
            )
        )


# ============================================================
# BROWSE COG — manga/novel navigation, plus /browse itself
# ============================================================

class Browse(
    commands.Cog
):

    def __init__(
        self,
        bot: commands.Bot,
    ):

        self.bot = bot

    # ========================================================
    # NAVIGATION
    # ========================================================

    async def show_info(
        self,
        interaction: discord.Interaction,
        session_id: str,
    ):

        session = get_session(
            session_id
        )

        if not session:
            return

        manga = session.get(
            "manga"
        )

        chapters = session.get(
            "chapters",
            [],
        )

        if not manga:
            return

        session["view"] = "info"

        await interaction.response.edit_message(
            embed=build_info(
                manga,
                chapters,
            ),
            view=MangaNavigationView(
                self,
                session_id,
                interaction.user.id,
            ),
        )

    async def show_chapters(
        self,
        interaction: discord.Interaction,
        session_id: str,
    ):

        session = get_session(
            session_id
        )

        if not session:
            return

        manga = session.get(
            "manga"
        )

        chapters = session.get(
            "chapters",
            [],
        )

        if not manga:
            return

        session["view"] = "chapters"

        await interaction.response.edit_message(
            embed=build_chapters(
                manga,
                chapters,
            ),
            view=MangaNavigationView(
                self,
                session_id,
                interaction.user.id,
            ),
        )

    async def show_languages(
        self,
        interaction: discord.Interaction,
        session_id: str,
    ):

        session = get_session(
            session_id
        )

        if not session:
            return

        manga = session.get(
            "manga"
        )

        chapters = session.get(
            "chapters",
            [],
        )

        if not manga:
            return

        session["view"] = "languages"

        await interaction.response.edit_message(
            embed=build_languages(
                manga,
                chapters,
            ),
            view=MangaNavigationView(
                self,
                session_id,
                interaction.user.id,
            ),
        )

    async def show_stats(
        self,
        interaction: discord.Interaction,
        session_id: str,
    ):

        session = get_session(
            session_id
        )

        if not session:
            return

        manga = session.get(
            "manga"
        )

        chapters = session.get(
            "chapters",
            [],
        )

        if not manga:
            return

        session["view"] = "stats"

        await interaction.response.edit_message(
            embed=build_stats(
                manga,
                chapters,
            ),
            view=MangaNavigationView(
                self,
                session_id,
                interaction.user.id,
            ),
        )

    # ========================================================
    # NOVEL NAVIGATION
    # ========================================================

    async def show_novel_info(
        self,
        interaction: discord.Interaction,
        session_id: str,
    ):

        session = get_session(session_id)

        if not session:
            return

        novel = session.get("novel")

        if not novel:
            return

        session["view"] = "info"

        await interaction.response.edit_message(
            embed=build_novel_info(novel),
            view=NovelNavigationView(
                self,
                session_id,
                interaction.user.id,
            ),
        )

    async def show_novel_genres(
        self,
        interaction: discord.Interaction,
        session_id: str,
    ):

        session = get_session(session_id)

        if not session:
            return

        novel = session.get("novel")

        if not novel:
            return

        session["view"] = "genres"

        await interaction.response.edit_message(
            embed=build_novel_genres(novel),
            view=NovelNavigationView(
                self,
                session_id,
                interaction.user.id,
            ),
        )

    # ========================================================
    # /BROWSE — unified anime / manga / novel search
    # ========================================================

    async def title_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:

        current = current.strip()

        if len(current) < 2:
            return []

        media_type = getattr(
            interaction.namespace,
            "media_type",
            None,
        )

        try:

            if media_type == "anime":
                results = await search_anime_anilist(current)

                return [
                    app_commands.Choice(
                        name=truncate(get_title(anime), 100),
                        value=truncate(get_title(anime), 100),
                    )
                    for anime in results[:25]
                ]

            if media_type == "novel":
                results = await search_novels(current)

                return [
                    app_commands.Choice(
                        name=truncate(
                            str(novel.get("title", "Unknown")),
                            100,
                        ),
                        value=str(novel.get("slug", ""))[:100],
                    )
                    for novel in results[:25]
                    if novel.get("slug")
                ]

            # Default / "manga"
            results = await search_manga(current)

            return [
                app_commands.Choice(
                    name=truncate(
                        str(manga.get("title", "Unknown")), 100
                    ),
                    value=str(manga.get("slug", ""))[:100],
                )
                for manga in results[:25]
                if manga.get("slug")
            ]

        except Exception:
            # Autocomplete errors should never surface to the user
            # as a broken interaction — just show no suggestions.
            return []

    @app_commands.command(
        name="browse",
        description="Search anime, manga, or novels.",
    )
    @app_commands.describe(
        media_type="What kind of media to search for.",
        title="Choose the title.",
        random="Anime only — skip search and get a random pick.",
        public="Post the result publicly instead of only to you.",
    )
    @app_commands.choices(
        media_type=[
            app_commands.Choice(name="Anime", value="anime"),
            app_commands.Choice(name="Manga", value="manga"),
            app_commands.Choice(name="Novel", value="novel"),
        ]
    )
    @app_commands.autocomplete(title=title_autocomplete)
    async def browse(
        self,
        interaction: discord.Interaction,
        media_type: app_commands.Choice[str],
        title: Optional[str] = None,
        random: bool = False,
        public: bool = True,
    ):

        kind = media_type.value
        query = (title or "").strip()

        # ----------------------------------------------------
        # ANIME
        # ----------------------------------------------------

        if kind == "anime":

            if random or not query:
                anime_helper = self.bot.get_cog("AnimeHelper")

                if anime_helper is None:
                    await interaction.response.send_message(
                        f"{EMOJI['error']} The anime helper "
                        "isn't loaded right now.",
                        ephemeral=True,
                    )
                    return

                if random:
                    await anime_helper.run_random(interaction)
                    return

                await anime_helper.show_anime_mode_chooser(
                    interaction
                )
                return

            if len(query) > 100:
                await interaction.response.send_message(
                    f"{EMOJI['denied']} "
                    "Search queries cannot exceed 100 characters.",
                    ephemeral=True,
                )
                return

            await interaction.response.defer(
                ephemeral=not public
            )

            results = await search_anime_anilist(query)

            if not results:
                await interaction.followup.send(
                    f"{EMOJI['denied']} "
                    f"No anime found for **{query}**."
                )
                return

            if len(results) == 1:
                embed = build_anime_embed(
                    results[0],
                    heading=f"{EMOJI['animetype']} Result:",
                )
                await interaction.followup.send(embed=embed)
                return

            await interaction.followup.send(
                content=(
                    f"{EMOJI['animetype']} "
                    f"Found **{len(results)}** matches for "
                    f"**{query}** — pick one:"
                ),
                view=AnimeSearchView(
                    self,
                    interaction.user.id,
                    results,
                ),
            )
            return

        # ----------------------------------------------------
        # MANGA / NOVEL — both require a title
        # ----------------------------------------------------

        if not query:
            await interaction.response.send_message(
                f"{EMOJI['question']} "
                f"Please provide a {kind} title to search for.",
                ephemeral=True,
            )
            return

        if len(query) > 100:
            await interaction.response.send_message(
                f"{EMOJI['denied']} "
                "Search queries cannot exceed 100 characters.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=not public)

        loading_label = "Manga" if kind == "manga" else "Novel"

        await interaction.edit_original_response(
            content=(
                f"{EMOJI['loading']} "
                f"Searching Lunar {loading_label} Catalog..."
            ),
        )

        if kind == "novel":

            # A direct slug match from autocomplete skips the
            # disambiguation step and shows the result immediately.
            novel = await fetch_novel(query)

            if novel is not None:
                session_id = str(interaction.id)

                set_session(
                    session_id,
                    {
                        "user_id": interaction.user.id,
                        "novel": novel,
                        "view": "info",
                    },
                )

                await interaction.edit_original_response(
                    content=(
                        f"{EMOJI['approved']} Search complete."
                    ),
                    embed=build_novel_info(novel),
                    view=NovelNavigationView(
                        self,
                        session_id,
                        interaction.user.id,
                    ),
                )
                return

            results = await search_novels(query)

            if not results:
                await interaction.edit_original_response(
                    content=(
                        f"{EMOJI['denied']} "
                        f"No novels found for **{query}**."
                    ),
                )
                return

            session_id = str(interaction.id)

            set_session(
                session_id,
                {
                    "user_id": interaction.user.id,
                    "query": query,
                    "results": results,
                    "page": 0,
                    "view": "home",
                },
            )

            await interaction.edit_original_response(
                content=f"{EMOJI['approved']} Search complete.",
                embed=build_novel_home(results, query),
                view=NovelSearchView(
                    self,
                    session_id,
                    interaction.user.id,
                    results,
                ),
            )
            return

        # kind == "manga"

        manga = await fetch_manga(query)

        if manga is not None:
            session_id = str(interaction.id)

            chapters = manga.get("data", [])

            if not isinstance(chapters, list):
                chapters = []

            set_session(
                session_id,
                {
                    "user_id": interaction.user.id,
                    "manga": manga,
                    "chapters": chapters,
                    "view": "info",
                },
            )

            await interaction.edit_original_response(
                content=f"{EMOJI['approved']} Search complete.",
                embed=build_info(manga, chapters),
                view=MangaNavigationView(
                    self,
                    session_id,
                    interaction.user.id,
                ),
            )
            return

        results = await search_manga(query)

        if not results:
            await interaction.edit_original_response(
                content=(
                    f"{EMOJI['denied']} "
                    f"No manga found for **{query}**."
                ),
            )
            return

        session_id = str(interaction.id)

        set_session(
            session_id,
            {
                "user_id": interaction.user.id,
                "query": query,
                "results": results,
                "page": 0,
                "view": "home",
            },
        )

        await interaction.edit_original_response(
            content=f"{EMOJI['approved']} Search complete.",
            embed=build_home(
                results,
                query,
            ),
            view=MangaSearchView(
                self,
                session_id,
                interaction.user.id,
                results,
            ),
        )


# ============================================================
# SETUP
# ============================================================

async def setup(
    bot: commands.Bot,
):

    await bot.add_cog(
        AnimeHelper(bot)
    )

    await bot.add_cog(
        Browse(bot)
    )

