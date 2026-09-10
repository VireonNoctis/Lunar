"""
Lunar Music
============

Multi-platform artist release tracker for Lunar.

Providers:
    - Spotify
    - YouTube Music
    - SoundCloud

Commands:
    /tmusic
    /tmusic_add
    /tmusic_list
    /tmusic_test
    /tmusic_pause
    /tmusic_resume
    /tmusic_remove

Environment variables:
    SPOTIFY_CLIENT_ID
    SPOTIFY_CLIENT_SECRET
    YOUTUBE_API_KEY
    SOUNDCLOUD_CLIENT_ID

Optional:
    TMUSIC_POLL_INTERVAL_MINUTES
"""

from __future__ import annotations

import asyncio
import base64
import html
import logging
import os
import re
import time
import xml.etree.ElementTree as ET

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

import aiohttp
import discord

from discord import app_commands
from discord.ext import commands, tasks

from cogs.utilities.database import db
from cogs.utilities.emoji import EMOJI


log = logging.getLogger("lunar.tmusic")


# ============================================================
# CONFIGURATION
# ============================================================

POLL_INTERVAL_MINUTES = max(
    1,
    int(
        os.getenv(
            "TMUSIC_POLL_INTERVAL_MINUTES",
            "10",
        )
    ),
)

MAX_SUBSCRIPTIONS_PER_GUILD = 25
MAX_SEEN_IDS = 75

SETTINGS_PREFIX = "tmusic:guild:"
SETTINGS_KEY = "subscriptions"

HTTP_TIMEOUT = aiohttp.ClientTimeout(
    total=15,
    connect=5,
    sock_read=10,
)

SPOTIFY_API = "https://api.spotify.com/v1"
SPOTIFY_TOKEN_URL = "https://accounts.spotify.com/api/token"

YOUTUBE_API = "https://www.googleapis.com/youtube/v3"

SOUNDCLOUD_API = "https://api-v2.soundcloud.com"


# ============================================================
# SENSITIVE CONFIGURATION
# ============================================================

SPOTIFY_CLIENT_ID = os.getenv(
    "SPOTIFY_CLIENT_ID"
)

SPOTIFY_CLIENT_SECRET = os.getenv(
    "SPOTIFY_CLIENT_SECRET"
)

YOUTUBE_API_KEY = os.getenv(
    "YOUTUBE_API_KEY"
)

SOUNDCLOUD_CLIENT_ID = os.getenv(
    "SOUNDCLOUD_CLIENT_ID"
)


# ============================================================
# PROVIDER HELPERS
# ============================================================

def provider_emoji(provider: str) -> str:
    provider = provider.lower().strip()

    if provider == "spotify":
        return EMOJI["spotify"]

    if provider == "youtube":
        return EMOJI["YtMusic"]

    if provider == "soundcloud":
        return EMOJI["Soundcloud"]

    return "🎵"


def provider_name(provider: str) -> str:
    return {
        "spotify": "Spotify",
        "youtube": "YouTube Music",
        "soundcloud": "SoundCloud",
    }.get(
        provider.lower(),
        provider.title(),
    )


# ============================================================
# GENERIC HELPERS
# ============================================================

def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso_now() -> str:
    return utcnow().isoformat()


def scope_for(guild_id: int) -> str:
    return f"{SETTINGS_PREFIX}{guild_id}"


def clean_text(
    value: Any,
    maximum: int = 1024,
) -> str:
    value = html.unescape(
        str(value or "")
    ).strip()

    value = discord.utils.escape_markdown(
        value
    )

    value = value.replace(
        "@everyone",
        "@\u200beveryone",
    )

    value = value.replace(
        "@here",
        "@\u200bhere",
    )

    if len(value) > maximum:
        return value[: maximum - 3] + "..."

    return value


def timestamp_relative(
    value: Optional[str],
) -> str:

    if not value:
        return "Never"

    try:
        dt = datetime.fromisoformat(
            value.replace(
                "Z",
                "+00:00",
            )
        )

        return f"<t:{int(dt.timestamp())}:R>"

    except (
        TypeError,
        ValueError,
    ):
        return "Unknown"


def extract_spotify_id(
    value: str,
) -> Optional[str]:

    value = value.strip()

    match = re.search(
        r"spotify\.com/artist/([A-Za-z0-9]+)",
        value,
        re.IGNORECASE,
    )

    if match:
        return match.group(1)

    if re.fullmatch(
        r"[A-Za-z0-9]{10,30}",
        value,
    ):
        return value

    return None


def extract_youtube_channel_id(
    value: str,
) -> Optional[str]:

    match = re.search(
        r"youtube\.com/channel/([A-Za-z0-9_-]+)",
        value.strip(),
        re.IGNORECASE,
    )

    if match:
        return match.group(1)

    return None


def extract_youtube_handle(
    value: str,
) -> Optional[str]:

    match = re.search(
        r"youtube\.com/@([A-Za-z0-9_.-]+)",
        value.strip(),
        re.IGNORECASE,
    )

    if match:
        return match.group(1)

    return None


def extract_soundcloud_user_id(
    value: str,
) -> Optional[str]:

    match = re.search(
        r"soundcloud:users:(\d+)",
        value,
        re.IGNORECASE,
    )

    if match:
        return match.group(1)

    return None


# ============================================================
# DATA MODELS
# ============================================================

@dataclass(slots=True)
class MusicRelease:
    provider: str
    release_id: str
    artist: str
    title: str
    url: str

    release_date: Optional[str] = None
    image_url: Optional[str] = None
    description: Optional[str] = None
    kind: str = "release"

    def cache_key(self) -> str:
        return (
            f"{self.provider}:"
            f"{self.release_id}"
        )


@dataclass(slots=True)
class MusicSubscription:
    id: str

    guild_id: int
    channel_id: int

    artist_name: str

    providers: list[str] = field(
        default_factory=list
    )

    spotify_target: Optional[str] = None
    youtube_target: Optional[str] = None
    soundcloud_target: Optional[str] = None

    mention_mode: str = "user"

    mention_user_id: Optional[int] = None
    mention_role_id: Optional[int] = None

    enabled: bool = True

    created_by: int = 0
    created_at: str = field(
        default_factory=iso_now
    )

    last_checked_at: Optional[str] = None

    seen_ids: list[str] = field(
        default_factory=list
    )

    def to_dict(self) -> dict[str, Any]:

        return {
            "id": self.id,
            "guild_id": self.guild_id,
            "channel_id": self.channel_id,
            "artist_name": self.artist_name,
            "providers": self.providers,
            "spotify_target": self.spotify_target,
            "youtube_target": self.youtube_target,
            "soundcloud_target": self.soundcloud_target,
            "mention_mode": self.mention_mode,
            "mention_user_id": self.mention_user_id,
            "mention_role_id": self.mention_role_id,
            "enabled": self.enabled,
            "created_by": self.created_by,
            "created_at": self.created_at,
            "last_checked_at": self.last_checked_at,
            "seen_ids": self.seen_ids[-MAX_SEEN_IDS:],
        }

    @classmethod
    def from_dict(
        cls,
        data: dict[str, Any],
    ) -> "MusicSubscription":

        return cls(
            id=str(
                data.get(
                    "id",
                    "",
                )
            ),
            guild_id=int(
                data.get(
                    "guild_id",
                    0,
                )
            ),
            channel_id=int(
                data.get(
                    "channel_id",
                    0,
                )
            ),
            artist_name=str(
                data.get(
                    "artist_name",
                    "",
                )
            ),
            providers=[
                str(provider).lower()
                for provider in data.get(
                    "providers",
                    [],
                )
            ],
            spotify_target=data.get(
                "spotify_target"
            ),
            youtube_target=data.get(
                "youtube_target"
            ),
            soundcloud_target=data.get(
                "soundcloud_target"
            ),
            mention_mode=str(
                data.get(
                    "mention_mode",
                    "user",
                )
            ),
            mention_user_id=(
                int(
                    data["mention_user_id"]
                )
                if data.get(
                    "mention_user_id"
                )
                else None
            ),
            mention_role_id=(
                int(
                    data["mention_role_id"]
                )
                if data.get(
                    "mention_role_id"
                )
                else None
            ),
            enabled=bool(
                data.get(
                    "enabled",
                    True,
                )
            ),
            created_by=int(
                data.get(
                    "created_by",
                    0,
                )
            ),
            created_at=str(
                data.get(
                    "created_at",
                    iso_now(),
                )
            ),
            last_checked_at=data.get(
                "last_checked_at"
            ),
            seen_ids=[
                str(item)
                for item in data.get(
                    "seen_ids",
                    [],
                )
            ][-MAX_SEEN_IDS:],
        )


# ============================================================
# DATABASE STORAGE
# ============================================================

class TMusicStorage:

    @staticmethod
    async def load(
        guild_id: int,
    ) -> list[MusicSubscription]:

        data = await db.settings.get(
            scope_for(guild_id),
            SETTINGS_KEY,
            default=[],
        )

        if not isinstance(
            data,
            list,
        ):
            return []

        subscriptions: list[
            MusicSubscription
        ] = []

        for item in data:

            if not isinstance(
                item,
                dict,
            ):
                continue

            try:

                subscription = (
                    MusicSubscription.from_dict(
                        item
                    )
                )

                if subscription.id:
                    subscriptions.append(
                        subscription
                    )

            except (
                TypeError,
                ValueError,
            ):
                log.exception(
                    "Invalid TMusic subscription"
                )

        return subscriptions

    @staticmethod
    async def save(
        guild_id: int,
        subscriptions: list[
            MusicSubscription
        ],
    ) -> None:

        await db.settings.set(
            scope_for(guild_id),
            SETTINGS_KEY,
            [
                subscription.to_dict()
                for subscription
                in subscriptions
            ],
        )

    @staticmethod
    async def find(
        guild_id: int,
        tracker_id: str,
    ) -> Optional[MusicSubscription]:

        subscriptions = await (
            TMusicStorage.load(
                guild_id
            )
        )

        for subscription in subscriptions:

            if subscription.id == tracker_id:
                return subscription

        return None

    @staticmethod
    async def add(
        subscription: MusicSubscription,
    ) -> None:

        subscriptions = await (
            TMusicStorage.load(
                subscription.guild_id
            )
        )

        subscriptions.append(
            subscription
        )

        await TMusicStorage.save(
            subscription.guild_id,
            subscriptions,
        )

    @staticmethod
    async def replace(
        subscription: MusicSubscription,
    ) -> None:

        subscriptions = await (
            TMusicStorage.load(
                subscription.guild_id
            )
        )

        replaced = False

        for index, current in enumerate(
            subscriptions
        ):

            if current.id == subscription.id:

                subscriptions[index] = (
                    subscription
                )

                replaced = True
                break

        if not replaced:

            subscriptions.append(
                subscription
            )

        await TMusicStorage.save(
            subscription.guild_id,
            subscriptions,
        )

    @staticmethod
    async def remove(
        guild_id: int,
        tracker_id: str,
    ) -> bool:

        subscriptions = await (
            TMusicStorage.load(
                guild_id
            )
        )

        original_length = len(
            subscriptions
        )

        subscriptions = [
            subscription
            for subscription in subscriptions
            if subscription.id != tracker_id
        ]

        if (
            len(subscriptions)
            == original_length
        ):
            return False

        await TMusicStorage.save(
            guild_id,
            subscriptions,
        )

        return True


# ============================================================
# EMBEDS
# ============================================================

class TMusicEmbeds:

    @staticmethod
    def base(
        title: str,
        description: str,
        colour: discord.Colour = discord.Colour.blurple(),
    ) -> discord.Embed:

        embed = discord.Embed(
            title=title,
            description=description,
            colour=colour,
            timestamp=utcnow(),
        )

        embed.set_footer(
            text="Lunar • TMusic"
        )

        return embed

    @staticmethod
    def success(
        title: str,
        description: str,
    ) -> discord.Embed:

        return TMusicEmbeds.base(
            f"{EMOJI['approved']} {title}",
            description,
            discord.Colour.green(),
        )

    @staticmethod
    def error(
        title: str,
        description: str,
    ) -> discord.Embed:

        return TMusicEmbeds.base(
            f"{EMOJI['error']} {title}",
            description,
            discord.Colour.red(),
        )

    @staticmethod
    def warning(
        title: str,
        description: str,
    ) -> discord.Embed:

        return TMusicEmbeds.base(
            f"{EMOJI['question']} {title}",
            description,
            discord.Colour.orange(),
        )


# ============================================================
# FAKE LOADING SYSTEM
# ============================================================

class SetupProgress:

    def __init__(
        self,
        interaction: discord.Interaction,
        artist: str,
        channel: discord.TextChannel,
    ):
        self.interaction = interaction
        self.artist = artist
        self.channel = channel

    async def update(
        self,
        stage: str,
        detail: str,
        current: int,
        total: int,
    ) -> None:

        percentage = round(
            (
                current
                / total
            )
            * 100
        )

        bar_size = 20

        filled = round(
            bar_size
            * percentage
            / 100
        )

        bar = (
            "━" * filled
            + "─" * (
                bar_size - filled
            )
        )

        embed = TMusicEmbeds.base(
            (
                f"{EMOJI['loading']} "
                "TMusic Initialization"
            ),
            (
                f"### {stage}\n"
                f"{detail}\n\n"
                f"`{bar}` **{percentage}%**\n\n"
                f"**Artist**\n"
                f"> {clean_text(self.artist)}\n\n"
                f"**Destination**\n"
                f"> {self.channel.mention}\n\n"
                f"System layer "
                f"`{current}/{total}`"
            ),
        )

        await self.interaction.edit_original_response(
            embed=embed
        )

    async def run(
        self,
    ) -> None:

        stages = [
            (
                "Resolving artist identity",
                "Searching the requested artist across the configured provider bridge.",
                1.0,
            ),
            (
                "Opening provider bridge",
                "Initializing the music source adapters and request sessions.",
                0.9,
            ),
            (
                "Checking Spotify",
                "Resolving artist metadata and preparing release discovery.",
                1.1,
            ),
            (
                "Checking YouTube Music",
                "Resolving the artist's channel and recent uploads.",
                1.1,
            ),
            (
                "Checking SoundCloud",
                "Inspecting the artist feed and recent tracks.",
                1.1,
            ),
            (
                "Verifying destination",
                "Checking channel access, message permissions, and embed support.",
                0.95,
            ),
            (
                "Preparing notifications",
                "Constructing mention routing and safe Discord mention handling.",
                0.9,
            ),
            (
                "Synchronizing release history",
                "Building the initial known-release baseline to prevent historical spam.",
                1.25,
            ),
            (
                "Persisting tracker",
                "Writing the tracker state into Lunar's persistent database layer.",
                1.1,
            ),
        ]

        total = len(stages)

        for index, (
            stage,
            detail,
            delay,
        ) in enumerate(
            stages,
            start=1,
        ):

            await self.update(
                stage,
                detail,
                index,
                total,
            )

            await asyncio.sleep(
                delay
            )


# ============================================================
# SPOTIFY PROVIDER
# ============================================================

class SpotifyProvider:

    def __init__(
        self,
        session: aiohttp.ClientSession,
    ):
        self.session = session

        self.access_token: Optional[str] = None
        self.expires_at: float = 0.0

    @property
    def configured(self) -> bool:

        return bool(
            SPOTIFY_CLIENT_ID
            and SPOTIFY_CLIENT_SECRET
        )

    async def get_token(
        self,
    ) -> Optional[str]:

        if not self.configured:
            return None

        if (
            self.access_token
            and time.monotonic()
            < self.expires_at - 60
        ):
            return self.access_token

        credentials = (
            f"{SPOTIFY_CLIENT_ID}:"
            f"{SPOTIFY_CLIENT_SECRET}"
        )

        encoded = base64.b64encode(
            credentials.encode(
                "utf-8"
            )
        ).decode(
            "ascii"
        )

        try:

            async with self.session.post(
                SPOTIFY_TOKEN_URL,
                headers={
                    "Authorization": (
                        f"Basic {encoded}"
                    ),
                    "Content-Type": (
                        "application/x-www-form-urlencoded"
                    ),
                },
                data={
                    "grant_type": (
                        "client_credentials"
                    )
                },
            ) as response:

                if response.status != 200:

                    log.warning(
                        "Spotify token failed: %s",
                        response.status,
                    )

                    return None

                payload = (
                    await response.json()
                )

        except (
            aiohttp.ClientError,
            asyncio.TimeoutError,
        ):

            log.exception(
                "Spotify token request failed"
            )

            return None

        self.access_token = payload.get(
            "access_token"
        )

        expires_in = int(
            payload.get(
                "expires_in",
                3600,
            )
        )

        self.expires_at = (
            time.monotonic()
            + expires_in
        )

        return self.access_token

    async def get(
        self,
        endpoint: str,
        params: Optional[
            dict[str, Any]
        ] = None,
    ) -> Optional[dict[str, Any]]:

        token = await self.get_token()

        if not token:
            return None

        try:

            async with self.session.get(
                f"{SPOTIFY_API}{endpoint}",
                headers={
                    "Authorization": (
                        f"Bearer {token}"
                    )
                },
                params=params,
            ) as response:

                if response.status == 401:

                    self.access_token = None
                    self.expires_at = 0

                    return None

                if response.status != 200:
                    return None

                return await response.json()

        except (
            aiohttp.ClientError,
            asyncio.TimeoutError,
        ):

            log.exception(
                "Spotify request failed: %s",
                endpoint,
            )

            return None

    async def resolve(
        self,
        target: str,
    ) -> Optional[dict[str, Any]]:

        artist_id = extract_spotify_id(
            target
        )

        if artist_id:

            return await self.get(
                f"/artists/{artist_id}"
            )

        result = await self.get(
            "/search",
            {
                "q": target,
                "type": "artist",
                "limit": 1,
            },
        )

        artists = (
            result or {}
        ).get(
            "artists",
            {}
        ).get(
            "items",
            []
        )

        if not artists:
            return None

        return artists[0]

    async def latest(
        self,
        target: str,
        fallback_artist: str,
    ) -> list[MusicRelease]:

        artist = await self.resolve(
            target
        )

        if not artist:
            return []

        artist_id = artist["id"]

        artist_name = artist.get(
            "name",
            fallback_artist,
        )

        result = await self.get(
            f"/artists/{artist_id}/albums",
            {
                "include_groups": (
                    "album,single"
                ),
                "limit": 10,
                "market": "US",
            },
        )

        if not result:
            return []

        releases = []

        for item in result.get(
            "items",
            []
        ):

            release_id = item.get(
                "id"
            )

            if not release_id:
                continue

            external_urls = (
                item.get(
                    "external_urls"
                )
                or {}
            )

            url = external_urls.get(
                "spotify"
            )

            if not url:
                continue

            images = (
                item.get(
                    "images"
                )
                or []
            )

            image_url = (
                images[0].get(
                    "url"
                )
                if images
                else None
            )

            releases.append(
                MusicRelease(
                    provider="spotify",
                    release_id=release_id,
                    artist=artist_name,
                    title=item.get(
                        "name",
                        "Unknown Release",
                    ),
                    url=url,
                    release_date=item.get(
                        "release_date"
                    ),
                    image_url=image_url,
                    kind=item.get(
                        "album_type",
                        "release",
                    ),
                )
            )

        releases.sort(
            key=lambda release: (
                release.release_date
                or ""
            ),
            reverse=True,
        )

        return releases[:5]


# ============================================================
# YOUTUBE PROVIDER
# ============================================================

class YouTubeProvider:

    def __init__(
        self,
        session: aiohttp.ClientSession,
    ):
        self.session = session

    @property
    def configured(self) -> bool:
        return bool(
            YOUTUBE_API_KEY
        )

    async def api_get(
        self,
        endpoint: str,
        params: dict[str, Any],
    ) -> Optional[dict[str, Any]]:

        query = dict(params)

        query["key"] = (
            YOUTUBE_API_KEY
        )

        try:

            async with self.session.get(
                f"{YOUTUBE_API}/{endpoint}",
                params=query,
            ) as response:

                if response.status != 200:

                    log.warning(
                        "YouTube API error %s -> %s",
                        endpoint,
                        response.status,
                    )

                    return None

                return await response.json()

        except (
            aiohttp.ClientError,
            asyncio.TimeoutError,
        ):

            log.exception(
                "YouTube API request failed"
            )

            return None

    async def resolve(
        self,
        target: str,
    ) -> Optional[
        dict[str, str]
    ]:

        channel_id = (
            extract_youtube_channel_id(
                target
            )
        )

        if channel_id:

            return {
                "id": channel_id,
                "name": target,
            }

        handle = (
            extract_youtube_handle(
                target
            )
        )

        query = (
            f"@{handle}"
            if handle
            else target
        )

        result = await self.api_get(
            "search",
            {
                "part": "snippet",
                "q": query,
                "type": "channel",
                "maxResults": 1,
            },
        )

        items = (
            result or {}
        ).get(
            "items",
            []
        )

        if not items:
            return None

        item = items[0]

        return {
            "id": item["id"]["channelId"],
            "name": item["snippet"].get(
                "channelTitle",
                target,
            ),
        }

    async def latest(
        self,
        target: str,
        fallback_artist: str,
    ) -> list[MusicRelease]:

        if not self.configured:
            return []

        channel = await self.resolve(
            target
        )

        if not channel:
            return []

        result = await self.api_get(
            "search",
            {
                "part": "snippet",
                "channelId": channel["id"],
                "type": "video",
                "order": "date",
                "maxResults": 5,
            },
        )

        if not result:
            return []

        releases = []

        for item in result.get(
            "items",
            []
        ):

            video_id = (
                item.get(
                    "id",
                    {}
                ).get(
                    "videoId"
                )
            )

            if not video_id:
                continue

            snippet = item.get(
                "snippet",
                {}
            )

            thumbnails = snippet.get(
                "thumbnails",
                {}
            )

            thumbnail = (
                thumbnails.get(
                    "high"
                )
                or thumbnails.get(
                    "medium"
                )
                or thumbnails.get(
                    "default"
                )
                or {}
            )

            releases.append(
                MusicRelease(
                    provider="youtube",
                    release_id=video_id,
                    artist=(
                        channel.get(
                            "name",
                            fallback_artist,
                        )
                    ),
                    title=snippet.get(
                        "title",
                        "New Upload",
                    ),
                    url=(
                        "https://www.youtube.com/"
                        f"watch?v={video_id}"
                    ),
                    release_date=snippet.get(
                        "publishedAt"
                    ),
                    image_url=thumbnail.get(
                        "url"
                    ),
                    description=snippet.get(
                        "description"
                    ),
                    kind="video",
                )
            )

        return releases[:5]


# ============================================================
# SOUNDCLOUD PROVIDER
# ============================================================

class SoundCloudProvider:

    def __init__(
        self,
        session: aiohttp.ClientSession,
    ):
        self.session = session

    async def resolve_user_id(
        self,
        target: str,
    ) -> Optional[str]:

        direct = (
            extract_soundcloud_user_id(
                target
            )
        )

        if direct:
            return direct

        is_url = (
            target.startswith(
                "http://"
            )
            or target.startswith(
                "https://"
            )
        )

        if not is_url:

            if not SOUNDCLOUD_CLIENT_ID:
                return None

            try:

                async with self.session.get(
                    f"{SOUNDCLOUD_API}/users",
                    params={
                        "q": target,
                        "client_id": (
                            SOUNDCLOUD_CLIENT_ID
                        ),
                        "limit": 1,
                    },
                ) as response:

                    if response.status != 200:
                        return None

                    payload = (
                        await response.json()
                    )

            except (
                aiohttp.ClientError,
                asyncio.TimeoutError,
            ):

                return None

            if (
                isinstance(
                    payload,
                    list,
                )
                and payload
            ):

                user_id = payload[0].get(
                    "id"
                )

                if user_id is not None:
                    return str(
                        user_id
                    )

            return None

        try:

            async with self.session.get(
                target
            ) as response:

                if response.status != 200:
                    return None

                source = await response.text()

        except (
            aiohttp.ClientError,
            asyncio.TimeoutError,
        ):

            return None

        return (
            extract_soundcloud_user_id(
                source
            )
        )

    async def latest(
        self,
        target: str,
        artist_name: str,
    ) -> list[MusicRelease]:

        user_id = (
            await self.resolve_user_id(
                target
            )
        )

        if not user_id:
            return []

        feed_url = (
            "https://feeds.soundcloud.com/"
            "users/"
            f"soundcloud:users:{user_id}/"
            "sounds.rss"
        )

        try:

            async with self.session.get(
                feed_url
            ) as response:

                if response.status != 200:
                    return []

                raw = await response.text()

        except (
            aiohttp.ClientError,
            asyncio.TimeoutError,
        ):

            return []

        try:

            root = ET.fromstring(
                raw
            )

        except ET.ParseError:

            return []

        releases = []

        for item in root.findall(
            ".//item"
        )[:5]:

            title = item.findtext(
                "title"
            )

            url = item.findtext(
                "link"
            )

            guid = item.findtext(
                "guid"
            )

            published = item.findtext(
                "pubDate"
            )

            if not url:
                continue

            releases.append(
                MusicRelease(
                    provider="soundcloud",
                    release_id=(
                        guid or url
                    ),
                    artist=artist_name,
                    title=(
                        title
                        or "New Track"
                    ),
                    url=url,
                    release_date=published,
                    kind="track",
                )
            )

        return releases


# ============================================================
# MAIN COG
# ============================================================

class TMusic(commands.Cog):

    def __init__(
        self,
        bot: commands.Bot,
    ):
        self.bot = bot

        self.session: Optional[
            aiohttp.ClientSession
        ] = None

        self.spotify: Optional[
            SpotifyProvider
        ] = None

        self.youtube: Optional[
            YouTubeProvider
        ] = None

        self.soundcloud: Optional[
            SoundCloudProvider
        ] = None

        self.guild_locks: dict[
            int,
            asyncio.Lock,
        ] = {}

    # ========================================================
    # LIFECYCLE
    # ========================================================

    async def cog_load(self) -> None:

        self.session = (
            aiohttp.ClientSession(
                timeout=HTTP_TIMEOUT,
                headers={
                    "User-Agent": (
                        "Lunar-TMusic/3.0"
                    ),
                    "Accept": (
                        "application/json,"
                        "application/xml,"
                        "text/xml,*/*"
                    ),
                },
            )
        )

        self.spotify = SpotifyProvider(
            self.session
        )

        self.youtube = YouTubeProvider(
            self.session
        )

        self.soundcloud = (
            SoundCloudProvider(
                self.session
            )
        )

        self.poll_releases.start()

        log.info(
            "TMusic subsystem loaded"
        )

    async def cog_unload(self) -> None:

        self.poll_releases.cancel()

        if (
            self.session
            and not self.session.closed
        ):
            await self.session.close()

    # ========================================================
    # LOCK
    # ========================================================

    def guild_lock(
        self,
        guild_id: int,
    ) -> asyncio.Lock:

        lock = self.guild_locks.get(
            guild_id
        )

        if lock is None:

            lock = asyncio.Lock()

            self.guild_locks[
                guild_id
            ] = lock

        return lock

    # ========================================================
    # FETCH PROVIDER
    # ========================================================

    async def fetch_provider(
        self,
        subscription: MusicSubscription,
        provider: str,
    ) -> list[MusicRelease]:

        target = {
            "spotify": (
                subscription.spotify_target
            ),
            "youtube": (
                subscription.youtube_target
            ),
            "soundcloud": (
                subscription.soundcloud_target
            ),
        }.get(
            provider
        )

        target = (
            target
            or subscription.artist_name
        )

        try:

            if provider == "spotify":

                if not self.spotify:
                    return []

                return await self.spotify.latest(
                    target,
                    subscription.artist_name,
                )

            if provider == "youtube":

                if not self.youtube:
                    return []

                return await self.youtube.latest(
                    target,
                    subscription.artist_name,
                )

            if provider == "soundcloud":

                if not self.soundcloud:
                    return []

                return await self.soundcloud.latest(
                    target,
                    subscription.artist_name,
                )

        except Exception:

            log.exception(
                "Provider fetch failure: %s",
                provider,
            )

        return []

    async def fetch_latest(
        self,
        subscription: MusicSubscription,
    ) -> list[MusicRelease]:

        providers = list(
            dict.fromkeys(
                subscription.providers
            )
        )

        if not providers:
            return []

        responses = await asyncio.gather(
            *[
                self.fetch_provider(
                    subscription,
                    provider,
                )
                for provider in providers
            ],
            return_exceptions=True,
        )

        releases: list[
            MusicRelease
        ] = []

        for response in responses:

            if isinstance(
                response,
                Exception,
            ):
                continue

            releases.extend(
                response
            )

        releases.sort(
            key=lambda release: (
                release.release_date
                or ""
            ),
            reverse=True,
        )

        # Deduplicate cross-provider
        # duplicates where possible.
        unique = []
        seen = set()

        for release in releases:

            key = (
                release.provider,
                release.release_id,
            )

            if key in seen:
                continue

            seen.add(key)
            unique.append(
                release
            )

        return unique[:15]

    # ========================================================
    # NOTIFICATION
    # ========================================================

    def notification_data(
        self,
        subscription: MusicSubscription,
    ) -> tuple[
        Optional[str],
        discord.AllowedMentions,
    ]:

        if (
            subscription.mention_mode
            == "user"
            and subscription.mention_user_id
        ):

            return (
                f"<@{subscription.mention_user_id}>",
                discord.AllowedMentions(
                    users=True,
                    roles=False,
                    everyone=False,
                ),
            )

        if (
            subscription.mention_mode
            == "role"
            and subscription.mention_role_id
        ):

            return (
                f"<@&{subscription.mention_role_id}>",
                discord.AllowedMentions(
                    users=False,
                    roles=True,
                    everyone=False,
                ),
            )

        return (
            None,
            discord.AllowedMentions.none(),
        )

    async def send_release(
        self,
        channel: discord.TextChannel,
        subscription: MusicSubscription,
        release: MusicRelease,
    ) -> bool:

        mention, allowed_mentions = (
            self.notification_data(
                subscription
            )
        )

        embed = TMusicEmbeds.base(
            (
                f"{provider_emoji(release.provider)} "
                f"New {provider_name(release.provider)} "
                "Release"
            ),
            (
                f"## {clean_text(release.title)}\n\n"
                f"**Artist:** "
                f"{clean_text(release.artist)}\n"
                f"**Platform:** "
                f"{provider_name(release.provider)}"
            ),
        )

        if release.release_date:

            embed.add_field(
                name="Released",
                value=clean_text(
                    release.release_date
                ),
                inline=True,
            )

        embed.add_field(
            name="Source",
            value=(
                f"[Open on "
                f"{provider_name(release.provider)}]"
                f"({release.url})"
            ),
            inline=True,
        )

        if release.description:

            description = clean_text(
                release.description,
                700,
            )

            embed.description += (
                f"\n\n{description}"
            )

        if release.image_url:

            embed.set_thumbnail(
                url=release.image_url
            )

        embed.set_author(
            name=clean_text(
                release.artist
            )
        )

        try:

            await channel.send(
                content=mention,
                embed=embed,
                allowed_mentions=allowed_mentions,
            )

            return True

        except (
            discord.Forbidden,
            discord.HTTPException,
        ):

            log.exception(
                "Failed to send TMusic release"
            )

            return False

    # ========================================================
    # PROVIDER RESOLUTION
    # ========================================================

    async def detect_providers(
        self,
        subscription: MusicSubscription,
    ) -> list[str]:

        detected = []

        # Spotify

        if self.spotify:

            result = await (
                self.spotify.resolve(
                    subscription.spotify_target
                    or subscription.artist_name
                )
            )

            if result:
                detected.append(
                    "spotify"
                )

        # YouTube

        if self.youtube:

            result = await (
                self.youtube.resolve(
                    subscription.youtube_target
                    or subscription.artist_name
                )
            )

            if result:
                detected.append(
                    "youtube"
                )

        # SoundCloud

        if self.soundcloud:

            result = await (
                self.soundcloud.resolve_user_id(
                    subscription.soundcloud_target
                    or subscription.artist_name
                )
            )

            if result:
                detected.append(
                    "soundcloud"
                )

        return detected

    # ========================================================
    # POLLER
    # ========================================================

    @tasks.loop(
        minutes=POLL_INTERVAL_MINUTES
    )
    async def poll_releases(self) -> None:

        for guild in list(
            getattr(
                self.bot,
                "guilds",
                [],
            )
        ):

            try:

                await self.process_guild(
                    guild
                )

            except Exception:

                log.exception(
                    "TMusic guild poll failed: %s",
                    guild.id,
                )

    @poll_releases.before_loop
    async def before_poll(
        self,
    ) -> None:

        await self.bot.wait_until_ready()

    async def process_guild(
        self,
        guild: discord.Guild,
    ) -> None:

        subscriptions = await (
            TMusicStorage.load(
                guild.id
            )
        )

        if not subscriptions:
            return

        lock = self.guild_lock(
            guild.id
        )

        async with lock:

            changed = False

            for subscription in subscriptions:

                if not subscription.enabled:
                    continue

                channel = guild.get_channel(
                    subscription.channel_id
                )

                if not isinstance(
                    channel,
                    discord.TextChannel,
                ):
                    continue

                releases = await (
                    self.fetch_latest(
                        subscription
                    )
                )

                subscription.last_checked_at = (
                    iso_now()
                )

                if not releases:

                    changed = True
                    continue

                known = set(
                    subscription.seen_ids
                )

                # First synchronization.
                if not known:

                    subscription.seen_ids = [
                        release.cache_key()
                        for release
                        in releases[:MAX_SEEN_IDS]
                    ]

                    changed = True
                    continue

                unseen = [
                    release
                    for release in releases
                    if release.cache_key()
                    not in known
                ]

                if not unseen:

                    changed = True
                    continue

                unseen.sort(
                    key=lambda release: (
                        release.release_date
                        or ""
                    )
                )

                for release in unseen:

                    success = await (
                        self.send_release(
                            channel,
                            subscription,
                            release,
                        )
                    )

                    if success:

                        subscription.seen_ids.append(
                            release.cache_key()
                        )

                        subscription.seen_ids = (
                            subscription.seen_ids[
                                -MAX_SEEN_IDS:
                            ]
                        )

                        changed = True

            if changed:

                await TMusicStorage.save(
                    guild.id,
                    subscriptions,
                )

    # ========================================================
    # /tmusic
    # ========================================================

    @app_commands.command(
        name="tmusic",
        description=(
            "Open the Lunar music tracking dashboard."
        ),
    )
    @app_commands.checks.has_permissions(
        manage_guild=True
    )
    async def tmusic(
        self,
        interaction: discord.Interaction,
    ) -> None:

        if not interaction.guild:

            await interaction.response.send_message(
                embed=TMusicEmbeds.error(
                    "Server Only",
                    "TMusic can only be used inside a server.",
                )
            )

            return

        subscriptions = await (
            TMusicStorage.load(
                interaction.guild.id
            )
        )

        active = sum(
            subscription.enabled
            for subscription
            in subscriptions
        )

        embed = TMusicEmbeds.base(
            (
                f"{EMOJI['lunar']} "
                "Lunar TMusic"
            ),
            (
                "### Music Release Intelligence\n"
                "Track artists across Spotify, YouTube Music, "
                "and SoundCloud and automatically publish "
                "new releases into your server.\n\n"
                "Tracker configuration is stored persistently "
                "in Lunar's database."
            ),
        )

        embed.add_field(
            name="Trackers",
            value=(
                f"**{len(subscriptions)}** configured\n"
                f"**{active}** active"
            ),
            inline=True,
        )

        embed.add_field(
            name="Platforms",
            value=(
                f"{EMOJI['spotify']} Spotify\n"
                f"{EMOJI['YtMusic']} YouTube Music\n"
                f"{EMOJI['Soundcloud']} SoundCloud"
            ),
            inline=True,
        )

        embed.add_field(
            name="Polling",
            value=(
                f"Every **{POLL_INTERVAL_MINUTES} minutes**"
            ),
            inline=True,
        )

        embed.add_field(
            name="Management",
            value=(
                "`/tmusic_add` — Create a tracker\n"
                "`/tmusic_list` — View trackers\n"
                "`/tmusic_test` — Test a tracker\n"
                "`/tmusic_pause` — Pause tracking\n"
                "`/tmusic_resume` — Resume tracking\n"
                "`/tmusic_remove` — Delete a tracker"
            ),
            inline=False,
        )

        await interaction.response.send_message(
            embed=embed
        )

    # ========================================================
    # /tmusic_add
    # ========================================================

    @app_commands.command(
        name="tmusic_add",
        description=(
            "Create a new artist music tracker."
        ),
    )
    @app_commands.describe(
        artist=(
            "Artist name or provider profile URL."
        ),
        channel=(
            "Channel where new releases should be announced."
        ),
    )
    @app_commands.checks.has_permissions(
        manage_guild=True
    )
    async def tmusic_add(
        self,
        interaction: discord.Interaction,
        artist: str,
        channel: discord.TextChannel,
    ) -> None:

        if not interaction.guild:

            await interaction.response.send_message(
                embed=TMusicEmbeds.error(
                    "Server Only",
                    "This command can only be used in a server.",
                )
            )

            return

        artist = artist.strip()

        if not artist:

            await interaction.response.send_message(
                embed=TMusicEmbeds.error(
                    "Invalid Artist",
                    "The artist name cannot be empty.",
                )
            )

            return

        subscriptions = await (
            TMusicStorage.load(
                interaction.guild.id
            )
        )

        if (
            len(subscriptions)
            >= MAX_SUBSCRIPTIONS_PER_GUILD
        ):

            await interaction.response.send_message(
                embed=TMusicEmbeds.error(
                    "Tracker Limit Reached",
                    (
                        f"This server has reached the maximum "
                        f"of **{MAX_SUBSCRIPTIONS_PER_GUILD}** trackers."
                    ),
                )
            )

            return

        bot_member = interaction.guild.me

        if bot_member:

            permissions = (
                channel.permissions_for(
                    bot_member
                )
            )

            missing = []

            if not permissions.view_channel:
                missing.append(
                    "View Channel"
                )

            if not permissions.send_messages:
                missing.append(
                    "Send Messages"
                )

            if not permissions.embed_links:
                missing.append(
                    "Embed Links"
                )

            if missing:

                await interaction.response.send_message(
                    embed=TMusicEmbeds.error(
                        "Channel Permissions",
                        (
                            f"I cannot publish releases in "
                            f"{channel.mention}.\n\n"
                            "Missing:\n"
                            + "\n".join(
                                f"• {permission}"
                                for permission in missing
                            )
                        ),
                    )
                )

                return

        subscription = MusicSubscription(
            id=(
                f"{interaction.guild.id}-"
                f"{int(time.time() * 1000)}-"
                f"{interaction.user.id}"
            ),
            guild_id=interaction.guild.id,
            channel_id=channel.id,
            artist_name=artist,
            providers=[],
            spotify_target=artist,
            youtube_target=artist,
            soundcloud_target=artist,
            mention_mode="user",
            mention_user_id=interaction.user.id,
            created_by=interaction.user.id,
        )

        await interaction.response.defer(
            ephemeral=True
        )

        progress = SetupProgress(
            interaction,
            artist,
            channel,
        )

        await progress.run()

        detected = await self.detect_providers(
            subscription
        )

        if not detected:

            await interaction.edit_original_response(
                embed=TMusicEmbeds.error(
                    "Artist Not Resolved",
                    (
                        f"I couldn't confidently resolve "
                        f"**{clean_text(artist)}** on the configured providers.\n\n"
                        "Try using a direct Spotify artist URL, "
                        "YouTube channel URL, or SoundCloud profile URL."
                    ),
                )
            )

            return

        subscription.providers = detected

        latest = await self.fetch_latest(
            subscription
        )

        subscription.seen_ids = [
            release.cache_key()
            for release in latest[:MAX_SEEN_IDS]
        ]

        await TMusicStorage.add(
            subscription
        )

        try:

            await db.audit.record(
                scope=(
                    f"guild:"
                    f"{interaction.guild.id}"
                ),
                action="tmusic.add",
                actor_id=str(
                    interaction.user.id
                ),
                target_id=subscription.id,
                details=(
                    f"artist={subscription.artist_name};"
                    f"providers={','.join(subscription.providers)};"
                    f"channel={subscription.channel_id}"
                ),
            )

        except Exception:

            log.exception(
                "Failed to audit TMusic add"
            )

        provider_text = "\n".join(
            (
                f"{provider_emoji(provider)} "
                f"**{provider_name(provider)}**"
            )
            for provider in detected
        )

        embed = TMusicEmbeds.success(
            "Tracker Activated",
            (
                f"### {clean_text(subscription.artist_name)}\n"
                "The artist is now being monitored.\n\n"
                f"**Platforms**\n"
                f"{provider_text}\n\n"
                f"**Destination**\n"
                f"{channel.mention}\n\n"
                f"**Notification Mode**\n"
                f"<@{interaction.user.id}>\n\n"
                "The currently known releases were synchronized "
                "as the baseline. Future releases will be announced "
                "automatically."
            ),
        )

        await interaction.edit_original_response(
            embed=embed
        )

    # ========================================================
    # /tmusic_list
    # ========================================================

    @app_commands.command(
        name="tmusic_list",
        description=(
            "Show all music trackers configured for this server."
        ),
    )
    @app_commands.checks.has_permissions(
        manage_guild=True
    )
    async def tmusic_list(
        self,
        interaction: discord.Interaction,
    ) -> None:

        subscriptions = await (
            TMusicStorage.load(
                interaction.guild.id
            )
        )

        if not subscriptions:

            await interaction.response.send_message(
                embed=TMusicEmbeds.base(
                    (
                        f"{EMOJI['lunar']} "
                        "TMusic Trackers"
                    ),
                    (
                        "No music trackers are configured.\n\n"
                        "Use `/tmusic_add` to create one."
                    ),
                )
            )

            return

        embed = TMusicEmbeds.base(
            (
                f"{EMOJI['lunar']} "
                "TMusic Trackers"
            ),
            (
                f"**{len(subscriptions)}** tracker(s) "
                "are configured for this server."
            ),
        )

        for index, subscription in enumerate(
            subscriptions,
            start=1,
        ):

            providers = " ".join(
                provider_emoji(provider)
                for provider
                in subscription.providers
            )

            status = (
                f"{EMOJI['approved']} Active"
                if subscription.enabled
                else "⏸️ Paused"
            )

            if (
                subscription.mention_mode
                == "user"
            ):

                mention = (
                    f"<@{subscription.mention_user_id}>"
                    if subscription.mention_user_id
                    else "User"
                )

            elif (
                subscription.mention_mode
                == "role"
            ):

                mention = (
                    f"<@&{subscription.mention_role_id}>"
                    if subscription.mention_role_id
                    else "Role"
                )

            else:

                mention = "None"

            embed.add_field(
                name=(
                    f"{index}. "
                    f"{clean_text(subscription.artist_name)}"
                ),
                value=(
                    f"{status}\n"
                    f"Platforms: {providers}\n"
                    f"Channel: <#{subscription.channel_id}>\n"
                    f"Mentions: {mention}\n"
                    f"Last check: "
                    f"{timestamp_relative(subscription.last_checked_at)}\n"
                    f"ID: `{subscription.id}`"
                ),
                inline=False,
            )

            if index >= 10:
                break

        await interaction.response.send_message(
            embed=embed
        )

    # ========================================================
    # /tmusic_test
    # ========================================================

    @app_commands.command(
        name="tmusic_test",
        description=(
            "Fetch and preview the newest release for a tracker."
        ),
    )
    @app_commands.describe(
        tracker=(
            "Tracker ID from /tmusic_list."
        ),
    )
    @app_commands.checks.has_permissions(
        manage_guild=True
    )
    async def tmusic_test(
        self,
        interaction: discord.Interaction,
        tracker: str,
    ) -> None:

        await interaction.response.defer(
            thinking=True
        )

        subscription = await (
            TMusicStorage.find(
                interaction.guild.id,
                tracker.strip(),
            )
        )

        if not subscription:

            await interaction.followup.send(
                embed=TMusicEmbeds.error(
                    "Tracker Not Found",
                    (
                        "I couldn't find that tracker.\n"
                        "Use `/tmusic_list` to get the correct ID."
                    ),
                )
            )

            return

        releases = await self.fetch_latest(
            subscription
        )

        if not releases:

            await interaction.followup.send(
                embed=TMusicEmbeds.error(
                    "No Release Found",
                    (
                        "None of the configured providers returned "
                        "a current release."
                    ),
                )
            )

            return

        release = releases[0]

        embed = TMusicEmbeds.base(
            (
                f"{provider_emoji(release.provider)} "
                f"TMusic Preview"
            ),
            (
                f"## {clean_text(release.title)}\n\n"
                f"**Artist:** "
                f"{clean_text(release.artist)}\n"
                f"**Platform:** "
                f"{provider_name(release.provider)}\n\n"
                f"[Open Release]({release.url})"
            ),
        )

        if release.image_url:

            embed.set_thumbnail(
                url=release.image_url
            )

        await interaction.followup.send(
            embed=embed
        )

    # ========================================================
    # /tmusic_pause
    # ========================================================

    @app_commands.command(
        name="tmusic_pause",
        description="Pause a music tracker.",
    )
    @app_commands.describe(
        tracker="Tracker ID.",
    )
    @app_commands.checks.has_permissions(
        manage_guild=True
    )
    async def tmusic_pause(
        self,
        interaction: discord.Interaction,
        tracker: str,
    ) -> None:

        subscription = await (
            TMusicStorage.find(
                interaction.guild.id,
                tracker.strip(),
            )
        )

        if not subscription:

            await interaction.response.send_message(
                embed=TMusicEmbeds.error(
                    "Tracker Not Found",
                    "That tracker does not exist.",
                )
            )

            return

        if not subscription.enabled:

            await interaction.response.send_message(
                embed=TMusicEmbeds.warning(
                    "Already Paused",
                    (
                        f"**{clean_text(subscription.artist_name)}** "
                        "is already paused."
                    ),
                )
            )

            return

        subscription.enabled = False

        await TMusicStorage.replace(
            subscription
        )

        try:

            await db.audit.record(
                scope=(
                    f"guild:"
                    f"{interaction.guild.id}"
                ),
                action="tmusic.pause",
                actor_id=str(
                    interaction.user.id
                ),
                target_id=subscription.id,
                details=(
                    f"artist={subscription.artist_name}"
                ),
            )

        except Exception:

            log.exception(
                "Failed to audit TMusic pause"
            )

        await interaction.response.send_message(
            embed=TMusicEmbeds.success(
                "Tracker Paused",
                (
                    f"**{clean_text(subscription.artist_name)}** "
                    "is no longer being checked for new releases."
                ),
            )
        )

    # ========================================================
    # /tmusic_resume
    # ========================================================

    @app_commands.command(
        name="tmusic_resume",
        description="Resume a paused music tracker.",
    )
    @app_commands.describe(
        tracker="Tracker ID.",
    )
    @app_commands.checks.has_permissions(
        manage_guild=True
    )
    async def tmusic_resume(
        self,
        interaction: discord.Interaction,
        tracker: str,
    ) -> None:

        subscription = await (
            TMusicStorage.find(
                interaction.guild.id,
                tracker.strip(),
            )
        )

        if not subscription:

            await interaction.response.send_message(
                embed=TMusicEmbeds.error(
                    "Tracker Not Found",
                    "That tracker does not exist.",
                )
            )

            return

        if subscription.enabled:

            await interaction.response.send_message(
                embed=TMusicEmbeds.warning(
                    "Already Active",
                    (
                        f"**{clean_text(subscription.artist_name)}** "
                        "is already active."
                    ),
                )
            )

            return

        subscription.enabled = True

        await TMusicStorage.replace(
            subscription
        )

        try:

            await db.audit.record(
                scope=(
                    f"guild:"
                    f"{interaction.guild.id}"
                ),
                action="tmusic.resume",
                actor_id=str(
                    interaction.user.id
                ),
                target_id=subscription.id,
                details=(
                    f"artist={subscription.artist_name}"
                ),
            )

        except Exception:

            log.exception(
                "Failed to audit TMusic resume"
            )

        await interaction.response.send_message(
            embed=TMusicEmbeds.success(
                "Tracker Resumed",
                (
                    f"**{clean_text(subscription.artist_name)}** "
                    "is being monitored again."
                ),
            )
        )

    # ========================================================
    # /tmusic_remove
    # ========================================================

    @app_commands.command(
        name="tmusic_remove",
        description="Remove a music tracker.",
    )
    @app_commands.describe(
        tracker="Tracker ID.",
    )
    @app_commands.checks.has_permissions(
        manage_guild=True
    )
    async def tmusic_remove(
        self,
        interaction: discord.Interaction,
        tracker: str,
    ) -> None:

        subscription = await (
            TMusicStorage.find(
                interaction.guild.id,
                tracker.strip(),
            )
        )

        if not subscription:

            await interaction.response.send_message(
                embed=TMusicEmbeds.error(
                    "Tracker Not Found",
                    "That tracker does not exist.",
                )
            )

            return

        view = RemoveTrackerView(
            cog=self,
            owner_id=interaction.user.id,
            subscription=subscription,
        )

        await interaction.response.send_message(
            embed=TMusicEmbeds.warning(
                "Remove Tracker?",
                (
                    f"You're about to remove the tracker "
                    f"for **{clean_text(subscription.artist_name)}**.\n\n"
                    "This deletes its configuration and "
                    "known-release history."
                ),
            ),
            view=view,
            ephemeral=True,
        )


# ============================================================
# REMOVE VIEW
# ============================================================

class RemoveTrackerView(
    discord.ui.View
):

    def __init__(
        self,
        cog: TMusic,
        owner_id: int,
        subscription: MusicSubscription,
    ):
        super().__init__(
            timeout=60
        )

        self.cog = cog
        self.owner_id = owner_id
        self.subscription = subscription

    async def interaction_check(
        self,
        interaction: discord.Interaction,
    ) -> bool:

        if interaction.user.id != self.owner_id:

            await interaction.response.send_message(
                f"{EMOJI['denied']} "
                "This confirmation belongs to another user.",
                ephemeral=True,
            )

            return False

        return True

    @discord.ui.button(
        label="Remove Tracker",
        style=discord.ButtonStyle.danger,
        emoji="🗑️",
    )
    async def remove(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:

        removed = await (
            TMusicStorage.remove(
                interaction.guild_id,
                self.subscription.id,
            )
        )

        if not removed:

            await interaction.response.edit_message(
                embed=TMusicEmbeds.error(
                    "Already Removed",
                    "That tracker no longer exists.",
                ),
                view=None,
            )

            return

        try:

            await db.audit.record(
                scope=(
                    f"guild:"
                    f"{interaction.guild.id}"
                ),
                action="tmusic.remove",
                actor_id=str(
                    interaction.user.id
                ),
                target_id=self.subscription.id,
                details=(
                    f"artist="
                    f"{self.subscription.artist_name}"
                ),
            )

        except Exception:

            log.exception(
                "Failed to audit TMusic removal"
            )

        await interaction.response.edit_message(
            embed=TMusicEmbeds.success(
                "Tracker Removed",
                (
                    f"**{clean_text(self.subscription.artist_name)}** "
                    "has been removed from TMusic."
                ),
            ),
            view=None,
        )

    @discord.ui.button(
        label="Cancel",
        style=discord.ButtonStyle.secondary,
    )
    async def cancel(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:

        await interaction.response.edit_message(
            embed=TMusicEmbeds.base(
                "Removal Cancelled",
                "The tracker was left untouched.",
            ),
            view=None,
        )


# ============================================================
# SETUP
# ============================================================

async def setup(
    bot: commands.Bot,
) -> None:

    await bot.add_cog(
        TMusic(bot)
    )
