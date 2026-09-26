import asyncio
import logging
import os
from typing import Any, Optional
import aiohttp
import discord
from discord.ext import commands
from cogs.utilities.database import db
from cogs.utilities.emoji import EMOJI

log = logging.getLogger("lunar.emoji_import")


# ============================================================
# CONFIG
# ============================================================

LUNAR_EMOJI_IMPORT_API = (
    "https://api.lunarx.to/api/admin/emojis/import"
)

# Where every import attempt gets logged.
LOG_CHANNEL_ID = 1499281835757404250

# Restrict which guilds emojis are pulled from.
# Leave empty to allow every guild the bot is in.
ALLOWED_GUILD_IDS: tuple[int, ...] = ()

ALLOWED_HOSTS = (
    "cdn.discordapp.com",
    "media.discordapp.net",
)

# How many emojis go into a single request to the Lunar API.
IMPORT_BATCH_SIZE = 50


VARIABLE_PREFIX = "emoji_import"

LUNAR_TOKEN = os.getenv("lunar_token")
LUNAR_BYPASS_TOKEN = os.getenv("bypass_token")


# ============================================================
# COG
# ============================================================

class EmojiImport(commands.Cog):
    """
    Automatically imports server emojis into the Lunar emoji vault.

    - Watches `on_guild_emojis_update` and imports anything new
      the moment it's uploaded to a guild.
    - Reconciles once on startup, so anything added while the bot
      was offline still gets picked up.
    - Every emoji is only ever submitted once. A row is reserved
      in the `variables` table (via the ``emoji_import:<id>`` key)
      before the API call goes out, and an asyncio.Lock keeps the
      startup sync and the live listener from racing each other.
    - Every attempt (success or rejection) is reported to the log
      channel.
    """

    def __init__(self, bot: commands.Bot):
        self.bot = bot

        self.http: Optional[aiohttp.ClientSession] = None

        # Serializes "check if already imported" + "reserve" so two
        # overlapping triggers (e.g. startup sync running right as
        # an emoji-update event fires) can never claim the same
        # emoji twice.
        self._lock = asyncio.Lock()

        self._synced_once = False

    # ========================================================
    # LIFECYCLE
    # ========================================================

    async def cog_load(self) -> None:
        timeout = aiohttp.ClientTimeout(
            total=15,
            connect=5,
            sock_read=10,
        )

        self.http = aiohttp.ClientSession(
            timeout=timeout,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "User-Agent": "LunarDiscordBot/1.0",
            },
        )

        log.info("Emoji import integration loaded")

    async def cog_unload(self) -> None:
        if self.http and not self.http.closed:
            await self.http.close()

        log.info("Emoji import integration unloaded")

    # ========================================================
    # HELPERS
    # ========================================================

    @staticmethod
    def _guild_allowed(guild_id: Optional[int]) -> bool:
        if not ALLOWED_GUILD_IDS:
            return True

        return guild_id in ALLOWED_GUILD_IDS

    @staticmethod
    def _variable_key(emoji_id: int) -> str:
        return f"{VARIABLE_PREFIX}:{emoji_id}"

    @staticmethod
    def _format_name(name: str) -> str:
        # The API expects names wrapped in colons, e.g. ":tes:".
        return f":{name.strip(':')}:"

    @staticmethod
    def _emoji_url(emoji: discord.Emoji) -> Optional[str]:
        url = str(emoji.url)

        try:
            host = url.split("/", 3)[2]
        except IndexError:
            host = ""

        if not url.startswith("https://") or host not in ALLOWED_HOSTS:
            return None

        return url

    async def _already_imported(self, emoji_id: int) -> bool:
        row = await db.variables.get(self._variable_key(emoji_id))
        return row is not None

    # ========================================================
    # RESERVATION
    # ========================================================

    async def _collect_pending(
        self,
        emojis: list[discord.Emoji],
    ) -> list[discord.Emoji]:
        """
        Filters `emojis` down to ones that have never been imported
        (or attempted) before, reserving each one under the lock so
        nothing can be picked up by a second overlapping call.
        """

        pending: list[discord.Emoji] = []

        async with self._lock:
            for emoji in emojis:

                if emoji.id is None:
                    continue

                if not self._guild_allowed(emoji.guild_id):
                    continue

                if await self._already_imported(emoji.id):
                    continue

                url = self._emoji_url(emoji)

                if url is None:
                    continue

                # Reserve immediately so nothing else can queue this
                # same emoji while we're still talking to the API.
                await db.variables.ensure(
                    self._variable_key(emoji.id),
                    string_value="pending",
                    metadata={
                        "name": emoji.name,
                        "guild_id": str(emoji.guild_id or ""),
                    },
                )

                pending.append(emoji)

        return pending

    async def _finalize(
        self,
        emoji: discord.Emoji,
        *,
        status: str,
        reason: str = "",
    ) -> None:
        await db.variables.update(
            self._variable_key(emoji.id),
            string_value=status,
            metadata={
                "name": emoji.name,
                "guild_id": str(emoji.guild_id or ""),
                "reason": reason,
            },
        )

    # ========================================================
    # LUNAR API
    # ========================================================

    async def _submit(
        self,
        emojis: list[discord.Emoji],
    ) -> Optional[dict[str, Any]]:

        if not self.http:
            log.error("Emoji import HTTP session is not initialized")
            return None

        if not LUNAR_TOKEN:
            log.error("Missing lunar_token environment variable")
            return None

        payload = {
            "emojis": [
                {
                    "name": self._format_name(emoji.name),
                    "url": self._emoji_url(emoji),
                }
                for emoji in emojis
            ]
        }

        headers = {
            "Authorization": LUNAR_TOKEN,
            "Content-Type": "application/json",
        }

        if LUNAR_BYPASS_TOKEN:
            headers["X-Scraper-Guard-Bypass"] = LUNAR_BYPASS_TOKEN

        try:
            async with self.http.post(
                LUNAR_EMOJI_IMPORT_API,
                json=payload,
                headers=headers,
            ) as response:

                if response.status != 200:
                    body = await response.text()

                    log.error(
                        "Emoji import API failed: %s | %s",
                        response.status,
                        body[:1000],
                    )

                    return None

                data = await response.json()

                if not isinstance(data, dict):
                    log.error(
                        "Emoji import API returned an invalid response"
                    )
                    return None

                return data

        except (aiohttp.ClientError, TimeoutError):
            log.exception("Emoji import API request failed")
            return None

        except Exception:
            log.exception("Unexpected emoji import API error")
            return None

    # ========================================================
    # LOGGING
    # ========================================================

    async def _get_log_channel(self):
        channel = self.bot.get_channel(LOG_CHANNEL_ID)

        if channel is not None:
            return channel

        try:
            return await self.bot.fetch_channel(LOG_CHANNEL_ID)
        except discord.HTTPException:
            log.exception("Could not access emoji import log channel")
            return None

    async def _log_result(
        self,
        emojis: list[discord.Emoji],
        result: Optional[dict[str, Any]],
    ) -> None:

        channel = await self._get_log_channel()

        if not isinstance(
            channel,
            (discord.TextChannel, discord.Thread),
        ):
            return

        if result is None:
            names = ", ".join(e.name for e in emojis[:10])

            try:
                await channel.send(
                    f"{EMOJI['error']} Failed to import "
                    f"**{len(emojis)}** emoji(s) (`{names}`) "
                    f"— the Lunar API request failed. Check logs."
                )
            except discord.HTTPException:
                log.exception("Failed to send emoji import failure log")

            return

        added = int(result.get("added", 0) or 0)
        rejected = result.get("rejected", []) or []
        success = bool(result.get("success", False))

        status_icon = EMOJI["approved"] if success else EMOJI["error"]

        lines = [
            f"{status_icon} Emoji import: **{added}** added, "
            f"**{len(rejected)}** rejected "
            f"out of **{len(emojis)}** submitted."
        ]

        for entry in rejected[:10]:
            name = entry.get("name", "?")
            why = entry.get("why", "unknown reason")

            lines.append(f"• `{name}` — {why}")

        remaining = len(rejected) - 10

        if remaining > 0:
            lines.append(f"...and {remaining} more.")

        try:
            await channel.send("\n".join(lines))
        except discord.HTTPException:
            log.exception("Failed to send emoji import log")

    # ========================================================
    # CORE IMPORT FLOW
    # ========================================================

    async def _import_emojis(
        self,
        emojis: list[discord.Emoji],
    ) -> None:

        if not emojis:
            return

        pending = await self._collect_pending(emojis)

        if not pending:
            return

        for start in range(0, len(pending), IMPORT_BATCH_SIZE):
            batch = pending[start : start + IMPORT_BATCH_SIZE]

            result = await self._submit(batch)

            rejected_names = {
                entry.get("name")
                for entry in (result or {}).get("rejected", []) or []
            }

            for emoji in batch:

                if result is None:
                    # The request itself failed (not a rejection by
                    # the API) -- unreserve so it can be retried on
                    # the next startup sync / emoji update instead
                    # of being stuck as "pending" forever.
                    await self._finalize(
                        emoji,
                        status="failed",
                        reason="request_failed",
                    )
                    continue

                if self._format_name(emoji.name) in rejected_names:
                    await self._finalize(
                        emoji,
                        status="rejected",
                    )
                else:
                    await self._finalize(
                        emoji,
                        status="imported",
                    )

            await self._log_result(batch, result)

            if result:
                await db.stats.increment(
                    "emojis_imported",
                    int(result.get("added", 0) or 0),
                )

    # ========================================================
    # LISTENERS
    # ========================================================

    @commands.Cog.listener()
    async def on_guild_emojis_update(
        self,
        guild: discord.Guild,
        before,
        after,
    ) -> None:

        before_ids = {emoji.id for emoji in before}

        added = [
            emoji for emoji in after if emoji.id not in before_ids
        ]

        if not added:
            return

        try:
            await self._import_emojis(added)
        except Exception:
            log.exception(
                "Unhandled error while importing new emojis "
                "for guild %s",
                guild.id,
            )

    @commands.Cog.listener()
    async def on_ready(self) -> None:

        if self._synced_once:
            return

        self._synced_once = True

        if not getattr(db, "_initialized", False):
            await db.initialize()

        all_emojis: list[discord.Emoji] = []

        for guild in self.bot.guilds:
            if not self._guild_allowed(guild.id):
                continue

            all_emojis.extend(guild.emojis)

        if not all_emojis:
            return

        try:
            await self._import_emojis(all_emojis)
        except Exception:
            log.exception("Unhandled error during startup emoji sync")


# ============================================================
# SETUP
# ============================================================

async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(EmojiImport(bot))
