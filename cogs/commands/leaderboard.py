from __future__ import annotations

import asyncio
import math
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

from cogs.utilities.database import db
from cogs.utilities.emoji import EMOJI


OWNERS = {
    1419744000977403994,
    960946185768685618,
}

LUNAR_LEADERBOARD_URL = "https://api.lunarx.to/api/animes/leaderboard"

PAGE_SIZE = 10
VIEW_TIMEOUT = 600
LUNAR_CACHE_SECONDS = 60


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def hour_bucket(dt: datetime) -> str:
    dt = dt.astimezone(timezone.utc).replace(
        minute=0,
        second=0,
        microsecond=0,
    )
    return dt.isoformat()


def format_number(value: int) -> str:
    return f"{value:,}"


def format_duration(seconds: int) -> str:
    seconds = max(0, int(seconds))

    days, remainder = divmod(seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, seconds = divmod(remainder, 60)

    parts: list[str] = []

    if days:
        parts.append(f"{days}d")

    if hours:
        parts.append(f"{hours}h")

    if minutes:
        parts.append(f"{minutes}m")

    if seconds or not parts:
        parts.append(f"{seconds}s")

    return " ".join(parts)


def medal(position: int) -> str:
    medals = {
        1: "🥇",
        2: "🥈",
        3: "🥉",
    }
    return medals.get(position, f"`#{position}`")


def lunar_profile_url(username: str) -> str:
    return f"https://lunarx.to/@{quote(username, safe='')}"


async def fake_loading(
    interaction: discord.Interaction,
    text: str,
    delay: float = 1.15,
) -> None:
    await interaction.edit_original_response(
        content=f"{EMOJI['loading']} {text}",
        embed=None,
        view=None,
    )
    await asyncio.sleep(delay)


class LeaderboardSelect(discord.ui.Select):
    def __init__(self, view: "LeaderboardView") -> None:
        self.dashboard_view = view

        options = [
            discord.SelectOption(
                label="24H Messages",
                description="Most messages sent in the last 24 hours.",
                emoji=EMOJI["new1"],
                value="24h",
                default=view.category == "24h",
            ),
            discord.SelectOption(
                label="Total Messages",
                description="Total messages recorded in this server.",
                emoji=EMOJI["right"],
                value="total",
                default=view.category == "total",
            ),
            discord.SelectOption(
                label="VC Time",
                description="Users with the most time spent in voice.",
                emoji=EMOJI["moon"],
                value="vc",
                default=view.category == "vc",
            ),
            discord.SelectOption(
                label="Lunar Top 25",
                description="Top 25 users on Lunar.",
                emoji=EMOJI["lunar"],
                value="lunar",
                default=view.category == "lunar",
            ),
        ]

        super().__init__(
            placeholder="Choose a leaderboard...",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        self.dashboard_view.category = self.values[0]
        self.dashboard_view.page = 0

        await self.dashboard_view.refresh(interaction)


class LeaderboardView(discord.ui.View):
    def __init__(
        self,
        cog: "Leaderboard",
        interaction: discord.Interaction,
        category: str = "24h",
    ) -> None:
        super().__init__(timeout=VIEW_TIMEOUT)

        self.cog = cog
        self.owner_id = interaction.user.id
        self.category = category
        self.page = 0

        self.select_menu = LeaderboardSelect(self)
        self.add_item(self.select_menu)

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

        self.previous_button.callback = self.previous_page
        self.next_button.callback = self.next_page

        self.add_item(self.previous_button)
        self.add_item(self.next_button)

        self.update_buttons()

    def update_buttons(self) -> None:
        self.previous_button.disabled = self.page <= 0

    async def interaction_check(
        self,
        interaction: discord.Interaction,
    ) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                f"{EMOJI['error']} This leaderboard session belongs to another user.",
                ephemeral=True,
            )
            return False

        return True

    async def previous_page(
        self,
        interaction: discord.Interaction,
    ) -> None:
        if self.page > 0:
            self.page -= 1

        await self.refresh(interaction)

    async def next_page(
        self,
        interaction: discord.Interaction,
    ) -> None:
        self.page += 1
        await self.refresh(interaction)

    async def refresh(
        self,
        interaction: discord.Interaction,
    ) -> None:
        self.update_buttons()

        if interaction.response.is_done():
            await interaction.edit_original_response(
                embed=await self.cog.build_embed(
                    interaction.guild,
                    self.category,
                    self.page,
                ),
                view=self,
                content=None,
            )
        else:
            await interaction.response.edit_message(
                embed=await self.cog.build_embed(
                    interaction.guild,
                    self.category,
                    self.page,
                ),
                view=self,
                content=None,
            )

    async def on_timeout(self) -> None:
        for child in self.children:
            child.disabled = True


class Leaderboard(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

        self._lunar_cache: list[dict[str, Any]] = []
        self._lunar_cache_time = 0.0
        self._lunar_lock = asyncio.Lock()

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot:
            return

        if message.guild is None:
            return

        try:
            bucket = hour_bucket(message.created_at)

            await db.stats.increment_message(
                guild_id=str(message.guild.id),
                user_id=str(message.author.id),
                hour_bucket=bucket,
            )
        except Exception:
            return

    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ) -> None:
        if member.bot:
            return

        guild_id = str(member.guild.id)
        user_id = str(member.id)

        try:
            if before.channel is None and after.channel is not None:
                await db.stats.set_vc_active(
                    guild_id=guild_id,
                    user_id=user_id,
                    joined_at=utc_now(),
                )
                return

            if before.channel is not None and after.channel is None:
                active = await db.stats.get_vc_active(
                    guild_id=guild_id,
                    user_id=user_id,
                )

                if active:
                    joined_at = active["joined_at"]

                    if joined_at.tzinfo is None:
                        joined_at = joined_at.replace(tzinfo=timezone.utc)

                    elapsed = max(
                        0,
                        int((utc_now() - joined_at).total_seconds()),
                    )

                    if elapsed > 0:
                        await db.stats.add_vc_seconds(
                            guild_id=guild_id,
                            user_id=user_id,
                            seconds=elapsed,
                        )

                await db.stats.clear_vc_active(
                    guild_id=guild_id,
                    user_id=user_id,
                )

        except Exception:
            return

    async def get_24h_messages(
        self,
        guild_id: int,
    ) -> list[tuple[str, int]]:
        now = utc_now()
        current_hour = now.replace(
            minute=0,
            second=0,
            microsecond=0,
        )

        buckets = [
            hour_bucket(current_hour - timedelta(hours=i))
            for i in range(25)
        ]

        rows = await db.stats.get_message_totals(
            guild_id=str(guild_id),
            hour_buckets=buckets,
        )

        totals: Counter[str] = Counter()

        for row in rows:
            user_id = str(row["user_id"])
            count = int(row.get("message_count", 0))
            totals[user_id] += count

        return totals.most_common()

    async def get_total_messages(
        self,
        guild_id: int,
    ) -> list[tuple[str, int]]:
        rows = await db.stats.get_message_totals(
            guild_id=str(guild_id),
            hour_buckets=None,
        )

        totals = [
            (
                str(row["user_id"]),
                int(row.get("message_count", 0)),
            )
            for row in rows
        ]

        totals.sort(
            key=lambda item: item[1],
            reverse=True,
        )

        return totals

    async def get_vc_leaderboard(
        self,
        guild_id: int,
    ) -> list[tuple[str, int]]:
        rows = await db.stats.get_vc_totals(
            guild_id=str(guild_id),
        )

        totals: dict[str, int] = {}

        for row in rows:
            user_id = str(row["user_id"])
            seconds = int(row.get("seconds", 0))
            totals[user_id] = seconds

        active_users = await db.stats.get_active_vc_users(
            guild_id=str(guild_id),
        )

        now = utc_now()

        for row in active_users:
            user_id = str(row["user_id"])
            joined_at = row["joined_at"]

            if joined_at.tzinfo is None:
                joined_at = joined_at.replace(
                    tzinfo=timezone.utc,
                )

            active_seconds = max(
                0,
                int((now - joined_at).total_seconds()),
            )

            totals[user_id] = totals.get(user_id, 0) + active_seconds

        result = list(totals.items())
        result.sort(
            key=lambda item: item[1],
            reverse=True,
        )

        return result

    async def fetch_lunar_leaderboard(self) -> list[dict[str, Any]]:
        now = time.monotonic()

        if (
            self._lunar_cache
            and now - self._lunar_cache_time < LUNAR_CACHE_SECONDS
        ):
            return self._lunar_cache

        async with self._lunar_lock:
            now = time.monotonic()

            if (
                self._lunar_cache
                and now - self._lunar_cache_time < LUNAR_CACHE_SECONDS
            ):
                return self._lunar_cache

            timeout = aiohttp.ClientTimeout(total=15)

            try:
                async with aiohttp.ClientSession(
                    timeout=timeout,
                ) as session:
                    async with session.get(
                        LUNAR_LEADERBOARD_URL,
                    ) as response:
                        if response.status != 200:
                            return self._lunar_cache

                        data = await response.json()

                leaderboard = data.get("leaderboard", [])

                if not isinstance(leaderboard, list):
                    return self._lunar_cache

                self._lunar_cache = leaderboard[:25]
                self._lunar_cache_time = time.monotonic()

                return self._lunar_cache

            except Exception:
                return self._lunar_cache

    async def build_discord_embed(
        self,
        guild: discord.Guild,
        category: str,
        page: int,
    ) -> discord.Embed:
        if category == "24h":
            title = f"{EMOJI['new1']} 24-Hour Message Leaderboard"
            entries = await self.get_24h_messages(guild.id)

            formatter = lambda value: (
                f"{EMOJI['new1']} **{format_number(value)} messages**"
            )

        elif category == "total":
            title = f"{EMOJI['right']} Total Message Leaderboard"
            entries = await self.get_total_messages(guild.id)

            formatter = lambda value: (
                f"{EMOJI['right']} **{format_number(value)} messages**"
            )

        else:
            title = f"{EMOJI['moon']} Voice Channel Leaderboard"
            entries = await self.get_vc_leaderboard(guild.id)

            formatter = lambda value: (
                f"{EMOJI['moon']} **{format_duration(value)}**"
            )

        total_pages = max(
            1,
            math.ceil(len(entries) / PAGE_SIZE),
        )

        page = max(
            0,
            min(page, total_pages - 1),
        )

        start = page * PAGE_SIZE
        current_entries = entries[start:start + PAGE_SIZE]

        embed = discord.Embed(
            title=title,
            description=(
                f"{EMOJI['lunar']} **{guild.name}**\n"
                f"Page **{page + 1}/{total_pages}**"
            ),
            colour=discord.Colour.blurple(),
            timestamp=utc_now(),
        )

        if not current_entries:
            embed.description = (
                f"{EMOJI['question']} No leaderboard data is available yet."
            )
            return embed

        lines: list[str] = []

        for index, (user_id, value) in enumerate(
            current_entries,
            start=start + 1,
        ):
            member = guild.get_member(int(user_id))

            if member is not None:
                username = member.display_name
                mention = member.mention
            else:
                username = f"User {user_id}"
                mention = f"<@{user_id}>"

            lines.append(
                f"{medal(index)} {mention} — "
                f"**{username}**\n"
                f"{' ' * 4}{formatter(value)}"
            )

        embed.add_field(
            name="Rankings",
            value="\n".join(lines),
            inline=False,
        )

        embed.set_footer(
            text="Lunar Leaderboards • Interactive Dashboard",
        )

        return embed

    async def build_lunar_embed(
        self,
        page: int,
    ) -> discord.Embed:
        leaderboard = await self.fetch_lunar_leaderboard()

        total_pages = max(
            1,
            math.ceil(len(leaderboard) / PAGE_SIZE),
        )

        page = max(
            0,
            min(page, total_pages - 1),
        )

        start = page * PAGE_SIZE
        entries = leaderboard[start:start + PAGE_SIZE]

        embed = discord.Embed(
            title=f"{EMOJI['lunar']} Lunar Top 25",
            description=(
                "Top users across Lunar\n"
                f"Page **{page + 1}/{total_pages}**"
            ),
            colour=discord.Colour.blurple(),
            timestamp=utc_now(),
        )

        if not entries:
            embed.description = (
                f"{EMOJI['question']} Lunar leaderboard data is unavailable."
            )
            return embed

        lines: list[str] = []

        for index, entry in enumerate(
            entries,
            start=start + 1,
        ):
            username = str(
                entry.get("username")
                or entry.get("name")
                or "Unknown User"
            )

            level = int(entry.get("level", 0))
            xp = int(entry.get("xp", 0))
            profile = lunar_profile_url(username)

            line = (
                f"{medal(index)} "
                f"**[{username}]({profile})**\n"
                f"{' ' * 4}Level **{format_number(level)}** • "
                f"XP **{format_number(xp)}**"
            )

            lines.append(line)

        embed.add_field(
            name="Lunar Rankings",
            value="\n".join(lines),
            inline=False,
        )

        if entries:
            first_avatar = entries[0].get("avatar")

            if first_avatar:
                embed.set_thumbnail(
                    url=str(first_avatar),
                )

        embed.set_footer(
            text="Lunar Top 25 • lunarx.to",
        )

        return embed

    async def build_embed(
        self,
        guild: discord.Guild | None,
        category: str,
        page: int,
    ) -> discord.Embed:
        if category == "lunar":
            return await self.build_lunar_embed(page)

        if guild is None:
            return discord.Embed(
                title=f"{EMOJI['error']} Error",
                description="This command can only be used inside a server.",
                colour=discord.Colour.red(),
            )

        return await self.build_discord_embed(
            guild=guild,
            category=category,
            page=page,
        )

    @app_commands.command(
        name="leaderboard",
        description="Open the interactive Lunar leaderboard dashboard.",
    )
    async def leaderboard(
        self,
        interaction: discord.Interaction,
    ) -> None:
        await interaction.response.send_message(
            f"{EMOJI['loading']} Loading leaderboard...",
        )

        await asyncio.sleep(1.25)

        view = LeaderboardView(
            cog=self,
            interaction=interaction,
            category="24h",
        )

        embed = await self.build_embed(
            guild=interaction.guild,
            category="24h",
            page=0,
        )

        await interaction.edit_original_response(
            content=None,
            embed=embed,
            view=view,
        )

    @app_commands.command(
        name="leaderboard_sync",
        description="Synchronize historical server leaderboard data.",
    )
    async def leaderboard_sync(
        self,
        interaction: discord.Interaction,
    ) -> None:
        if interaction.user.id not in OWNERS:
            await interaction.response.send_message(
                f"{EMOJI['error']} You are not authorized to use this command.",
                ephemeral=True,
            )
            return

        if interaction.guild is None:
            await interaction.response.send_message(
                f"{EMOJI['error']} This command can only be used inside a server.",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            f"{EMOJI['loading']} Preparing leaderboard synchronization...",
        )

        guild = interaction.guild

        text_channels = [
            channel
            for channel in guild.text_channels
            if channel.permissions_for(guild.me).view_channel
            and channel.permissions_for(guild.me).read_message_history
        ]

        if not text_channels:
            await interaction.edit_original_response(
                content=(
                    f"{EMOJI['error']} I cannot read message history in "
                    f"any text channel."
                ),
            )
            return

        total_channels = len(text_channels)
        processed_channels = 0
        scanned_messages = 0

        total_counts: Counter[str] = Counter()
        hourly_counts: Counter[tuple[str, str]] = Counter()

        sync_started = time.monotonic()

        last_24h = utc_now() - timedelta(hours=24)

        for channel in text_channels:
            try:
                async for message in channel.history(
                    limit=None,
                    oldest_first=True,
                ):
                    scanned_messages += 1

                    if message.author.bot:
                        continue

                    user_id = str(message.author.id)

                    total_counts[user_id] += 1

                    created_at = message.created_at

                    if created_at.tzinfo is None:
                        created_at = created_at.replace(
                            tzinfo=timezone.utc,
                        )

                    if created_at >= last_24h:
                        bucket = hour_bucket(created_at)

                        hourly_counts[
                            (user_id, bucket)
                        ] += 1

                    if scanned_messages % 500 == 0:
                        elapsed = max(
                            0.001,
                            time.monotonic() - sync_started,
                        )

                        rate = scanned_messages / elapsed
                        remaining_channels = max(
                            0,
                            total_channels - processed_channels,
                        )

                        eta_seconds = (
                            remaining_channels / max(rate / 250, 0.001)
                        )

                        await interaction.edit_original_response(
                            content=(
                                f"{EMOJI['loading']} "
                                f"**Syncing leaderboard data...**\n"
                                f"Channels: **{processed_channels}/{total_channels}**\n"
                                f"Messages scanned: **{format_number(scanned_messages)}**\n"
                                f"Users discovered: **{format_number(len(total_counts))}**\n"
                                f"ETA: **{format_duration(int(eta_seconds))}**"
                            ),
                        )

            except discord.Forbidden:
                pass

            except discord.HTTPException:
                pass

            processed_channels += 1

            elapsed = max(
                0.001,
                time.monotonic() - sync_started,
            )

            average_per_channel = elapsed / processed_channels
            remaining = total_channels - processed_channels
            eta_seconds = average_per_channel * remaining

            await interaction.edit_original_response(
                content=(
                    f"{EMOJI['loading']} "
                    f"**Syncing leaderboard data...**\n"
                    f"Channels: **{processed_channels}/{total_channels}**\n"
                    f"Messages scanned: **{format_number(scanned_messages)}**\n"
                    f"Users discovered: **{format_number(len(total_counts))}**\n"
                    f"ETA: **{format_duration(int(eta_seconds))}**"
                ),
            )

        try:
            await db.stats.rebuild_message_totals(
                guild_id=str(guild.id),
                totals=dict(total_counts),
            )

            await db.stats.rebuild_message_hours(
                guild_id=str(guild.id),
                hourly=dict(hourly_counts),
            )

            await db.stats.set_leaderboard_sync_state(
                guild_id=str(guild.id),
                last_sync_at=utc_now(),
                messages_scanned=scanned_messages,
                channels_scanned=processed_channels,
                users_discovered=len(total_counts),
            )

        except Exception:
            await interaction.edit_original_response(
                content=(
                    f"{EMOJI['error']} "
                    "The historical data was scanned, but the database "
                    "synchronization failed."
                ),
            )
            return

        total_time = time.monotonic() - sync_started

        await interaction.edit_original_response(
            content=(
                f"{EMOJI['approved']} "
                "**Leaderboard synchronization complete.**\n"
                f"Channels scanned: **{processed_channels}/{total_channels}**\n"
                f"Messages scanned: **{format_number(scanned_messages)}**\n"
                f"Users discovered: **{format_number(len(total_counts))}**\n"
                f"Duration: **{format_duration(int(total_time))}**"
            ),
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Leaderboard(bot))
