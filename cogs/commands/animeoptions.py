from __future__ import annotations

import asyncio
import re

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
# TEXT
# ============================================================

def clean_text(
    value: str | None,
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

    return anime.get(
        "siteUrl"
    ) or (
        f"https://anilist.co/anime/{anime_id}"
    )


# ============================================================
# EMBED
# ============================================================

def build_anime_embed(
    anime: dict,
    *,
    title: str,
    color: discord.Color,
) -> discord.Embed:

    description = clean_text(
        anime.get("description")
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
            f"{title} "
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
        anime.get("episodes")
        or "?"
    )

    duration = (
        anime.get("duration")
        or "?"
    )

    status = (
        anime.get("status")
        or "UNKNOWN"
    )

    genres = anime.get(
        "genres"
    ) or []

    genre_text = (
        ", ".join(genres[:5])
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
# ANILIST API
# ============================================================

async def anilist_request(
    session: aiohttp.ClientSession,
    query: str,
    variables: dict | None = None,
) -> dict | None:

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

    except Exception:

        return None


# ============================================================
# LUNAR API
# ============================================================

async def fetch_lunar_profile(
    username: str,
) -> dict | None:

    async with aiohttp.ClientSession(
        timeout=REQUEST_TIMEOUT
    ) as session:

        try:

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

        except Exception:

            return None


# ============================================================
# DATABASE
# ============================================================

async def get_lunar_username(
    user_id: int,
) -> str | None:

    account = await db.account_links.get(
        str(user_id)
    )

    if not account:
        return None

    if not getattr(
        account,
        "verified",
        False,
    ):
        return None

    metadata = (
        getattr(
            account,
            "metadata",
            None,
        )
        or {}
    )

    username = metadata.get(
        "username"
    )

    if not username:
        username = metadata.get(
            "lunar_username"
        )

    if not isinstance(
        username,
        str,
    ):
        return None

    username = username.strip()

    return (
        username
        if username
        else None
    )


# ============================================================
# ANILIST WATCHLIST EXTRACTION
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

            # ------------------------------------------------
            # Explicit anime/media identifiers
            # ------------------------------------------------

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

            # ------------------------------------------------
            # AniList Media object
            # ------------------------------------------------

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

            # ------------------------------------------------
            # Continue recursively
            # ------------------------------------------------

            for child in current.values():
                walk(child)

        elif isinstance(
            current,
            list,
        ):

            for child in current:
                walk(child)

    walk(
        value
    )

    return found


def get_watchlist_ids(
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

        preferred_keys = (
            "watchlist",
            "watch_list",
            "anime_watchlist",
            "media",
            "lists",
            "entries",
        )

        for key in preferred_keys:

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

async def fetch_random_anime() -> dict | None:

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

        if not media:
            return None

        media = [
            anime
            for anime in media
            if anime.get("id") is not None
        ]

        if not media:
            return None

        # ----------------------------------------------------
        # Cryptographic selection
        # ----------------------------------------------------

        ids = [
            str(
                anime["id"]
            )
            for anime in media
        ]

        result = (
            CryptographicRandomizer.select(
                ids,
                1,
                context="animeoptions.random",
            )
        )

        selected_id = int(
            result.winners[0]
        )

        for anime in media:

            if anime["id"] == selected_id:
                return anime

    return None


# ============================================================
# PERSONALIZED RECOMMENDATION
# ============================================================

async def recommend(
    watchlist_ids: set[int],
) -> dict | None:

    if not watchlist_ids:
        return None

    seed_ids = list(
        watchlist_ids
    )

    seed_count = min(
        5,
        len(seed_ids),
    )

    # Select the seed anime cryptographically.
    seeds = (
        CryptographicRandomizer.select(
            [
                str(
                    anime_id
                )
                for anime_id in seed_ids
            ],
            seed_count,
            context="animeoptions.rec.seeds",
        )
    )

    selected_seed_ids = [
        int(value)
        for value in seeds.winners
    ]

    candidates: dict[int, dict] = {}

    async with aiohttp.ClientSession(
        timeout=REQUEST_TIMEOUT
    ) as session:

        for seed_id in selected_seed_ids:

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

                anime = node.get(
                    "mediaRecommendation"
                )

                if not anime:
                    continue

                anime_id = anime.get(
                    "id"
                )

                if not anime_id:
                    continue

                # Never recommend something already
                # present in the user's watchlist.
                if anime_id in watchlist_ids:
                    continue

                candidates[
                    anime_id
                ] = anime

    if not candidates:
        return None

    # --------------------------------------------------------
    # Rank candidates
    # --------------------------------------------------------

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

    # Don't let one recommendation completely dominate.
    top = ranked[
        :min(
            10,
            len(ranked),
        )
    ]

    if not top:
        return None

    # --------------------------------------------------------
    # Cryptographically choose final result
    # --------------------------------------------------------

    result = (
        CryptographicRandomizer.select(
            [
                str(
                    anime["id"]
                )
                for anime in top
            ],
            1,
            context="animeoptions.rec.result",
        )
    )

    selected_id = int(
        result.winners[0]
    )

    for anime in top:

        if anime.get(
            "id"
        ) == selected_id:

            return anime

    return None


# ============================================================
# COG
# ============================================================

class AnimeOptions(
    commands.Cog
):

    def __init__(
        self,
        bot: commands.Bot,
    ):
        self.bot = bot

    # ========================================================
    # GROUP
    # ========================================================

    animeoptions = app_commands.Group(
        name="animeoptions",
        description="Anime discovery and recommendation tools.",
    )

    # ========================================================
    # RANDOM
    # ========================================================

    @animeoptions.command(
        name="random",
        description="Discover a random anime.",
    )
    async def random(
        self,
        interaction: discord.Interaction,
    ):

        await interaction.response.send_message(
            f"{EMOJI['loading']} "
            "Searching the anime archives...",
            ephemeral=True,
        )

        await asyncio.sleep(
            1
        )

        anime = await fetch_random_anime()

        if not anime:

            embed = discord.Embed(
                title=(
                    f"{EMOJI['error']} "
                    "Random Search Failed"
                ),
                description=(
                    f"{EMOJI['denied']} "
                    "AniList didn't return a valid "
                    "anime right now. Try again."
                ),
                color=discord.Color.red(),
            )

            await interaction.edit_original_response(
                content=None,
                embed=embed,
            )

            return

        embed = build_anime_embed(
            anime,
            title=(
                f"{EMOJI['lunar']} Random Pick:"
            ),
            color=discord.Color.blurple(),
        )

        embed.description = (
            f"{EMOJI['approved']} "
            "The archive has selected an anime for you.\n\n"
            + (
                embed.description
                or ""
            )
        )

        await interaction.edit_original_response(
            content=None,
            embed=embed,
        )

    # ========================================================
    # RECOMMENDATION
    # ========================================================

    @animeoptions.command(
        name="rec",
        description="Get an anime recommendation from your Lunar watchlist.",
    )
    async def rec(
        self,
        interaction: discord.Interaction,
    ):

        # ----------------------------------------------------
        # STEP 1 — ACCOUNT
        # ----------------------------------------------------

        await interaction.response.send_message(
            f"{EMOJI['loading']} "
            "Checking your Lunar account...",
            ephemeral=True,
        )

        await asyncio.sleep(
            1
        )

        try:

            username = await get_lunar_username(
                interaction.user.id
            )

        except Exception:

            username = None

        if not username:

            embed = discord.Embed(
                title=(
                    f"{EMOJI['question']} "
                    "Lunar Account Required"
                ),
                description=(
                    f"{EMOJI['denied']} "
                    "You need a verified Lunar account "
                    "before I can create a personalized "
                    "recommendation.\n\n"
                    "Use `/link` to connect your Lunar account."
                ),
                color=discord.Color.orange(),
            )

            await interaction.edit_original_response(
                content=None,
                embed=embed,
            )

            return

        # ----------------------------------------------------
        # STEP 2 — LUNAR PROFILE
        # ----------------------------------------------------

        await interaction.edit_original_response(
            content=(
                f"{EMOJI['loading']} "
                f"Reading Lunar profile for `{username}`..."
            )
        )

        await asyncio.sleep(
            1
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
            )

            return

        # ----------------------------------------------------
        # STEP 3 — WATCHLIST
        # ----------------------------------------------------

        watchlist_ids = get_watchlist_ids(
            profile
        )

        if not watchlist_ids:

            embed = discord.Embed(
                title=(
                    f"{EMOJI['question']} "
                    "AniList Watchlist Unavailable"
                ),
                description=(
                    f"{EMOJI['denied']} "
                    "Lunar returned your profile, but it "
                    "isn't currently providing AniList "
                    "watchlist data.\n\n"
                    "Make sure your AniList account is "
                    "connected to Lunar."
                ),
                color=discord.Color.orange(),
            )

            embed.set_footer(
                text=(
                    f"Lunar Account • {username}"
                )
            )

            await interaction.edit_original_response(
                content=None,
                embed=embed,
            )

            return

        # ----------------------------------------------------
        # STEP 4 — RECOMMENDATION
        # ----------------------------------------------------

        await interaction.edit_original_response(
            content=(
                f"{EMOJI['loading']} "
                f"Analyzed `{len(watchlist_ids):,}` anime. "
                "Finding something new..."
            )
        )

        await asyncio.sleep(
            1
        )

        recommendation = await recommend(
            watchlist_ids
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
                    "outside your current watchlist."
                ),
                color=discord.Color.orange(),
            )

            await interaction.edit_original_response(
                content=None,
                embed=embed,
            )

            return

        # ----------------------------------------------------
        # RESULT
        # ----------------------------------------------------

        embed = build_anime_embed(
            recommendation,
            title=(
                f"{EMOJI['aniheart']} "
                "Recommended:"
            ),
            color=discord.Color.gold(),
        )

        embed.description = (
            f"{EMOJI['approved']} "
            f"Recommendation generated from "
            f"`{len(watchlist_ids):,}` anime on your Lunar "
            "watchlist.\n\n"
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
        )


# ============================================================
# SETUP
# ============================================================

async def setup(
    bot: commands.Bot,
):

    await bot.add_cog(
        AnimeOptions(bot)
    )
