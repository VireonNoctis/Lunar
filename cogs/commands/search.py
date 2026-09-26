from __future__ import annotations

import json
import re
import time

import aiohttp
import discord

from discord import app_commands
from discord.ext import commands

from cogs.utilities.database import db
from cogs.utilities.emoji import EMOJI


# ============================================================
# CONSTANTS
# ============================================================

API_BASE = "https://api.lunarx.to/api"
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
    manga: dict,
) -> int:
    theme = (
        manga.get("theme_color")
        or manga.get("themecolor")
    )

    parsed = parse_color(
        theme
    )

    if parsed is not None:
        return parsed

    return gradient_fallback(
        manga.get(
            "title",
            "lunar",
        )
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


def slugify(
    value: str,
) -> str:
    value = value.strip().lower()

    value = re.sub(
        r"[^a-z0-9]+",
        "-",
        value,
    )

    return value.strip("-")


def parse_json_field(
    value,
    default,
):
    if value is None:
        return default

    if isinstance(
        value,
        (list, dict),
    ):
        return value

    try:
        parsed = json.loads(
            value
        )

    except (TypeError, ValueError):
        return default

    return parsed


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
    url = (
        f"{API_BASE}"
        f"{endpoint}"
    )

    timeout = aiohttp.ClientTimeout(
        total=10
    )

    try:

        async with aiohttp.ClientSession(
            timeout=timeout
        ) as session:

            async with session.get(
                url,
                headers={
                    "Accept": "application/json",
                    "User-Agent": "Lunar-Bot/1.0",
                },
            ) as response:

                if response.status != 200:
                    return None

                return await response.json()

    except (
        aiohttp.ClientError,
        aiohttp.ContentTypeError,
        TimeoutError,
    ):
        return None


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
        f"/manga/search?q={aiohttp.helpers.quote(query)}"
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
        f"/manga/{aiohttp.helpers.quote(slug)}"
    )

    if not data:
        return None

    await set_cached(
        key,
        data,
        MANGA_CACHE_TTL,
    )

    return data


async def fetch_novel(
    slug: str,
) -> dict | None:
    """
    GET /novels/title/{slug}

    Unlike manga, there is no keyword-search endpoint for novels,
    so the search command resolves whatever the user typed into a
    slug and fetches it directly.
    """

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

    data = await lunar_get(
        f"/novels/title/"
        f"{aiohttp.helpers.quote(slug)}"
    )

    if not data:
        return None

    novel = data.get(
        "novel"
    )

    if not isinstance(
        novel,
        dict,
    ):
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
            f"{EMOJI['moon']} Lunar Catalog"
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


def build_novel_info(
    novel: dict,
) -> discord.Embed:

    alt_titles = parse_json_field(
        novel.get(
            "alternative_titles"
        ),
        [],
    )

    embed = discord.Embed(
        title=(
            f"{EMOJI['moon']} "
            f"{novel.get('title', 'Unknown')}"
        ),
        url=(
            f"{LUNAR_BASE}/novel/"
            f"{novel.get('slug', '')}"
        ),
        description=truncate(
            str(
                novel.get(
                    "description",
                    "No description",
                )
                or "No description"
            ),
            350,
        ),
        color=resolve_color(
            novel
        ),
    )

    cover_url = novel.get(
        "cover_url"
    )

    banner_url = novel.get(
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
            f"{novel.get('author', '?')}\n"
            f"Artist: "
            f"{novel.get('artist', '?')}\n"
            f"Status: "
            f"{novel.get('publication_status', '?')}\n"
            f"Year: "
            f"{novel.get('publication_year', '?')}"
        ),
        inline=False,
    )

    embed.add_field(
        name="Rating",
        value=(
            f"Rating: "
            f"{novel.get('rating', '?')}\n"
            f"Demographic: "
            f"{novel.get('demographic', '?')}"
        ),
        inline=True,
    )

    embed.add_field(
        name="Badges",
        value=(
            f"{'Official' if novel.get('is_official') else 'Unofficial'}\n"
            f"{'Premium' if novel.get('is_premium') else 'Free'}"
        ),
        inline=True,
    )

    if alt_titles:

        embed.add_field(
            name="Alternative Titles",
            value=truncate(
                ", ".join(
                    str(title)
                    for title in alt_titles
                ),
                200,
            ),
            inline=False,
        )

    embed.set_footer(
        text="Lunar Library • Novel"
    )

    return embed


def build_novel_genres(
    novel: dict,
) -> discord.Embed:

    genres = parse_json_field(
        novel.get("genres"),
        [],
    )

    themes = parse_json_field(
        novel.get("themes"),
        [],
    )

    return discord.Embed(
        title=(
            f"{EMOJI['moon']} "
            "Genres & Themes"
        ),
        description=(
            "**Genres**\n"
            + (
                ", ".join(
                    str(genre)
                    for genre in genres
                )
                if genres
                else "None listed."
            )
            + "\n\n**Themes**\n"
            + (
                ", ".join(
                    str(theme)
                    for theme in themes
                )
                if themes
                else "None listed."
            )
        ),
        color=resolve_color(
            novel
        ),
    )


def build_novel_details(
    novel: dict,
) -> discord.Embed:

    translated_languages = parse_json_field(
        novel.get(
            "translated_languages"
        ),
        [],
    )

    return discord.Embed(
        title=(
            f"{EMOJI['moon']} "
            "Publication Details"
        ),
        description=(
            f"Publisher: "
            f"{novel.get('publisher') or '?'}\n"
            f"Serialization: "
            f"{novel.get('serialization') or '?'}\n"
            f"Original Language: "
            f"{novel.get('original_language', '?')}\n"
            f"Translated Languages: "
            f"{', '.join(translated_languages) if translated_languages else '?'}\n"
            f"Translator: "
            f"{novel.get('tl_username') or '?'}"
        ),
        color=resolve_color(
            novel
        ),
    )


# ============================================================
# NAVIGATION VIEW
# ============================================================

class MangaNavigationView(
    discord.ui.View
):

    def __init__(
        self,
        cog: "Search",
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
        cog: "Search",
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
        cog: "Search",
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
        cog: "Search",
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

        await self.cog.show_novel_info(
            interaction,
            self.session_id,
        )

    @discord.ui.button(
        label="Genres",
        style=discord.ButtonStyle.secondary,
    )
    async def genres(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):

        await self.cog.show_novel_genres(
            interaction,
            self.session_id,
        )

    @discord.ui.button(
        label="Details",
        style=discord.ButtonStyle.secondary,
    )
    async def details(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):

        await self.cog.show_novel_details(
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
# SEARCH COG
# ============================================================

class Search(
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

        session = get_session(
            session_id
        )

        if not session:
            return

        novel = session.get(
            "novel"
        )

        if not novel:
            return

        session["view"] = "novel_info"

        await interaction.response.edit_message(
            embed=build_novel_info(
                novel
            ),
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

        session = get_session(
            session_id
        )

        if not session:
            return

        novel = session.get(
            "novel"
        )

        if not novel:
            return

        session["view"] = "novel_genres"

        await interaction.response.edit_message(
            embed=build_novel_genres(
                novel
            ),
            view=NovelNavigationView(
                self,
                session_id,
                interaction.user.id,
            ),
        )

    async def show_novel_details(
        self,
        interaction: discord.Interaction,
        session_id: str,
    ):

        session = get_session(
            session_id
        )

        if not session:
            return

        novel = session.get(
            "novel"
        )

        if not novel:
            return

        session["view"] = "novel_details"

        await interaction.response.edit_message(
            embed=build_novel_details(
                novel
            ),
            view=NovelNavigationView(
                self,
                session_id,
                interaction.user.id,
            ),
        )

    # ========================================================
    # /SEARCH
    # ========================================================

    @app_commands.command(
        name="search",
        description="Search the Lunar library.",
    )
    @app_commands.describe(
        query=(
            "The title (or novel slug) you want to search for."
        ),
        category="Manga or Novel. Defaults to Manga.",
    )
    @app_commands.choices(
        category=[
            app_commands.Choice(
                name="Manga",
                value="manga",
            ),
            app_commands.Choice(
                name="Novel",
                value="novel",
            ),
        ]
    )
    async def search(
        self,
        interaction: discord.Interaction,
        query: str,
        category: app_commands.Choice[str] | None = None,
    ):

        category_value = (
            category.value
            if category
            else "manga"
        )

        if category_value == "novel":

            await self.search_novel(
                interaction,
                query,
            )

            return

        query = query.strip()

        if not query:

            await interaction.response.send_message(
                f"{EMOJI['question']} "
                "Please provide a manga title to search for.",
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

        await interaction.response.defer()

        await interaction.edit_original_response(
            content=(
                f"{EMOJI['loading']} "
                "Searching Lunar Catalog..."
            ),
        )

        results = await search_manga(
            query
        )

        if not results:

            await interaction.edit_original_response(
                content=(
                    f"{EMOJI['denied']} "
                    f"No manga found for **{query}**."
                ),
            )

            return

        session_id = str(
            interaction.id
        )

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
            content=(
                f"{EMOJI['approved']} "
                "Search complete."
            ),
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

    # ========================================================
    # NOVEL LOOKUP
    #
    # There is no keyword-search endpoint for novels, only
    # GET /novels/title/{slug}, so the query is normalized into
    # a slug and fetched directly instead of returning a list.
    # ========================================================

    async def search_novel(
        self,
        interaction: discord.Interaction,
        query: str,
    ):

        query = query.strip()

        if not query:

            await interaction.response.send_message(
                f"{EMOJI['question']} "
                "Please provide a novel title or slug "
                "to search for.",
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

        await interaction.response.defer()

        await interaction.edit_original_response(
            content=(
                f"{EMOJI['loading']} "
                "Looking up novel..."
            ),
        )

        slug = slugify(
            query
        )

        if not slug:

            await interaction.edit_original_response(
                content=(
                    f"{EMOJI['denied']} "
                    f"No novel found for **{query}**."
                ),
            )

            return

        novel = await fetch_novel(
            slug
        )

        if not novel:

            await interaction.edit_original_response(
                content=(
                    f"{EMOJI['denied']} "
                    f"No novel found for **{query}**."
                ),
            )

            return

        session_id = str(
            interaction.id
        )

        set_session(
            session_id,
            {
                "user_id": interaction.user.id,
                "query": query,
                "novel": novel,
                "view": "novel_info",
            },
        )

        await interaction.edit_original_response(
            content=(
                f"{EMOJI['approved']} "
                "Novel loaded."
            ),
            embed=build_novel_info(
                novel
            ),
            view=NovelNavigationView(
                self,
                session_id,
                interaction.user.id,
            ),
        )


# ============================================================
# SETUP
# ============================================================

async def setup(
    bot: commands.Bot,
):

    await bot.add_cog(
        Search(bot)
    )
