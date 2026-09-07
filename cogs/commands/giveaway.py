from __future__ import annotations

import asyncio
import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import discord
from discord import app_commands
from discord.ext import commands, tasks

from cogs.utilities.database import db
from cogs.utilities.emoji import EMOJI
from cogs.utilities.randomizer import (
    CryptographicRandomizer,
    RandomSelection,
)

log = logging.getLogger("lunar.giveaway")

MAX_WINNERS = 100
MAX_PRIZE_LENGTH = 200
MAX_DESCRIPTION_LENGTH = 1500
MAX_DURATION_SECONDS = 365 * 86400
FAKE_LOADING_SECONDS = 1.25


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def parse_duration(value: str) -> Optional[int]:
    value = value.strip().lower()

    if not value:
        return None

    units = {
        "s": 1,
        "m": 60,
        "h": 3600,
        "d": 86400,
        "w": 604800,
    }

    number = ""

    for char in value:
        if not char.isdigit():
            break
        number += char

    if not number:
        return None

    unit = value[len(number):]
    multiplier = units.get(unit)

    if multiplier is None:
        return None

    seconds = int(number) * multiplier

    if seconds <= 0 or seconds > MAX_DURATION_SECONDS:
        return None

    return seconds


def format_duration(seconds: int) -> str:
    if seconds % 604800 == 0:
        return f"{seconds // 604800} week(s)"

    if seconds % 86400 == 0:
        return f"{seconds // 86400} day(s)"

    if seconds % 3600 == 0:
        return f"{seconds // 3600} hour(s)"

    if seconds % 60 == 0:
        return f"{seconds // 60} minute(s)"

    return f"{seconds} second(s)"


def mention_users(user_ids: list[str] | tuple[str, ...]) -> str:
    if not user_ids:
        return "No winners."

    return ", ".join(
        f"<@{user_id}>"
        for user_id in user_ids
    )


def parse_metadata(value: Any) -> dict[str, Any]:
    if not value:
        return {}

    if isinstance(value, dict):
        return dict(value)

    try:
        parsed = json.loads(str(value))
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}

    return parsed if isinstance(parsed, dict) else {}


def normalize_ids(values: Any) -> list[str]:
    if values is None:
        return []

    if isinstance(values, (str, bytes)):
        values = [values]

    return sorted(
        {
            str(value).strip()
            for value in values
            if str(value).strip()
        }
    )


@dataclass(slots=True)
class GiveawayState:
    giveaway_id: str
    guild_id: str
    channel_id: str
    message_id: Optional[str]
    host_id: str
    prize: str
    description: str
    winner_count: int
    duration_seconds: int
    ends_at: str
    participants: list[str] = field(default_factory=list)
    seed_hex: Optional[str] = None
    commitment: Optional[str] = None
    randomizer_version: str = CryptographicRandomizer.algorithm
    ended: bool = False
    deleted: bool = False
    round_number: int = 1
    last_result: Optional[dict[str, Any]] = None
    draw_history: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def from_row(cls, row: Any) -> "GiveawayState":
        metadata = parse_metadata(
            getattr(row, "metadata", None)
        )

        ended = (
            str(
                getattr(
                    row,
                    "state",
                    "active",
                )
            )
            == "ended"
        )

        ended_at = getattr(
            row,
            "ended_at",
            None,
        )

        ends_at = getattr(
            row,
            "ends_at",
            None,
        )

        participants = normalize_ids(
            getattr(
                row,
                "participant_ids",
                None,
            )
        )

        return cls(
            giveaway_id=str(
                getattr(
                    row,
                    "giveaway_id",
                )
            ),
            guild_id=str(
                getattr(
                    row,
                    "guild_id",
                )
            ),
            channel_id=str(
                getattr(
                    row,
                    "channel_id",
                )
            ),
            message_id=(
                str(
                    getattr(
                        row,
                        "message_id",
                    )
                )
                if getattr(
                    row,
                    "message_id",
                    None,
                )
                else None
            ),
            host_id=str(
                getattr(
                    row,
                    "host_id",
                )
            ),
            prize=str(
                getattr(
                    row,
                    "prize",
                    "",
                )
            ),
            description=str(
                getattr(
                    row,
                    "description",
                    "",
                )
            ),
            winner_count=max(
                1,
                int(
                    getattr(
                        row,
                        "winners_count",
                        1,
                    )
                    or 1
                ),
            ),
            duration_seconds=max(
                1,
                int(
                    getattr(
                        row,
                        "duration_seconds",
                        1,
                    )
                    or 1
                ),
            ),
            ends_at=(
                ends_at.isoformat()
                if isinstance(
                    ends_at,
                    datetime,
                )
                else str(
                    ends_at
                )
            ),
            participants=participants,
            seed_hex=(
                str(
                    metadata["seed_hex"]
                )
                if metadata.get(
                    "seed_hex"
                )
                else None
            ),
            commitment=(
                str(
                    metadata["commitment"]
                )
                if metadata.get(
                    "commitment"
                )
                else None
            ),
            randomizer_version=str(
                metadata.get(
                    "randomizer_version",
                    CryptographicRandomizer.algorithm,
                )
            ),
            ended=ended,
            deleted=False,
            round_number=max(
                1,
                int(
                    metadata.get(
                        "round_number",
                        1,
                    )
                    or 1
                ),
            ),
            last_result=(
                metadata.get(
                    "last_result"
                )
                if isinstance(
                    metadata.get(
                        "last_result"
                    ),
                    dict,
                )
                else None
            ),
            draw_history=(
                metadata.get(
                    "draw_history"
                )
                if isinstance(
                    metadata.get(
                        "draw_history"
                    ),
                    list,
                )
                else []
            ),
        )

    def metadata(self) -> dict[str, str]:
        return {
            "seed_hex": self.seed_hex or "",
            "commitment": self.commitment or "",
            "randomizer_version": self.randomizer_version,
            "round_number": str(
                self.round_number
            ),
            "last_result": (
                json.dumps(
                    self.last_result,
                    separators=(
                        ",",
                        ":",
                    ),
                )
                if self.last_result is not None
                else ""
            ),
            "draw_history": json.dumps(
                self.draw_history,
                separators=(
                    ",",
                    ":",
                ),
            ),
        }


class GiveawayEntryView(discord.ui.View):
    def __init__(
        self,
        cog: "Giveaway",
        giveaway_id: str,
    ):
        super().__init__(
            timeout=None
        )

        self.cog = cog
        self.giveaway_id = giveaway_id

        button = discord.ui.Button(
            label="Enter Giveaway",
            emoji=EMOJI["gift"],
            style=discord.ButtonStyle.blurple,
            custom_id=(
                f"giveaway:enter:"
                f"{giveaway_id}"
            ),
        )

        button.callback = self.enter

        self.add_item(button)

    async def enter(
        self,
        interaction: discord.Interaction,
    ) -> None:
        await self.cog.handle_entry(
            interaction,
            self.giveaway_id,
        )


class GiveawayEndedView(discord.ui.View):
    def __init__(self):
        super().__init__(
            timeout=None
        )

        self.add_item(
            discord.ui.Button(
                label="Giveaway Ended",
                emoji=EMOJI["gift"],
                style=discord.ButtonStyle.secondary,
                disabled=True,
                custom_id="giveaway:ended",
            )
        )


class GiveawayCreateModal(discord.ui.Modal):
    def __init__(
        self,
        cog: "Giveaway",
        author_id: int,
    ):
        super().__init__(
            title="Create Giveaway"
        )

        self.cog = cog
        self.author_id = author_id

        self.duration_input = discord.ui.TextInput(
            label="Duration",
            placeholder="Examples: 30m, 2h, 3d, 1w",
            min_length=2,
            max_length=12,
            required=True,
        )

        self.winners_input = discord.ui.TextInput(
            label="Number of Winners",
            placeholder="Example: 3",
            min_length=1,
            max_length=3,
            required=True,
        )

        self.prize_input = discord.ui.TextInput(
            label="Prize",
            placeholder="Example: 1,000,000 Coins",
            min_length=1,
            max_length=MAX_PRIZE_LENGTH,
            required=True,
        )

        self.description_input = discord.ui.TextInput(
            label="Description",
            placeholder=(
                "Explain the giveaway and any "
                "important details."
            ),
            style=discord.TextStyle.paragraph,
            min_length=1,
            max_length=MAX_DESCRIPTION_LENGTH,
            required=True,
        )

        self.add_item(
            self.duration_input
        )

        self.add_item(
            self.winners_input
        )

        self.add_item(
            self.prize_input
        )

        self.add_item(
            self.description_input
        )

    async def on_submit(
        self,
        interaction: discord.Interaction,
    ) -> None:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "This giveaway form belongs to another user.",
                ephemeral=True,
            )
            return

        duration_seconds = parse_duration(
            self.duration_input.value
        )

        if duration_seconds is None:
            await interaction.response.send_message(
                (
                    "Invalid duration. Use "
                    "`30s`, `15m`, `2h`, `3d`, or `1w`. "
                    f"Maximum duration is "
                    f"{format_duration(MAX_DURATION_SECONDS)}."
                ),
                ephemeral=True,
            )
            return

        try:
            winner_count = int(
                self.winners_input.value.strip()
            )
        except ValueError:
            await interaction.response.send_message(
                "Winner count must be a whole number.",
                ephemeral=True,
            )
            return

        if not 1 <= winner_count <= MAX_WINNERS:
            await interaction.response.send_message(
                (
                    f"Winner count must be between "
                    f"1 and {MAX_WINNERS}."
                ),
                ephemeral=True,
            )
            return

        prize = self.prize_input.value.strip()
        description = (
            self.description_input.value.strip()
        )

        if not prize:
            await interaction.response.send_message(
                "Prize cannot be empty.",
                ephemeral=True,
            )
            return

        if not description:
            await interaction.response.send_message(
                "Description cannot be empty.",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            embed=self.cog.build_preview_embed(
                interaction,
                duration_seconds=duration_seconds,
                winner_count=winner_count,
                prize=prize,
                description=description,
            ),
            view=GiveawayConfirmView(
                cog=self.cog,
                author_id=self.author_id,
                duration_seconds=duration_seconds,
                winner_count=winner_count,
                prize=prize,
                description=description,
            ),
            ephemeral=True,
        )


class GiveawayConfirmView(discord.ui.View):
    def __init__(
        self,
        *,
        cog: "Giveaway",
        author_id: int,
        duration_seconds: int,
        winner_count: int,
        prize: str,
        description: str,
    ):
        super().__init__(
            timeout=120
        )

        self.cog = cog
        self.author_id = author_id
        self.duration_seconds = duration_seconds
        self.winner_count = winner_count
        self.prize = prize
        self.description = description

    async def interaction_check(
        self,
        interaction: discord.Interaction,
    ) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "Only the giveaway creator can use these buttons.",
                ephemeral=True,
            )
            return False

        return True

    @discord.ui.button(
        label="Publish Giveaway",
        emoji=EMOJI["approved"],
        style=discord.ButtonStyle.success,
    )
    async def publish(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        button.disabled = True

        await interaction.response.edit_message(
            embed=discord.Embed(
                title=(
                    f"{EMOJI['loading']} "
                    "Publishing Giveaway"
                ),
                description=(
                    "Generating cryptographic entropy...\n"
                    "Creating the SHA-256 commitment...\n"
                    "Publishing giveaway state..."
                ),
                color=discord.Color.blurple(),
            ),
            view=self,
        )

        await asyncio.sleep(
            FAKE_LOADING_SECONDS
        )

        try:
            state = await self.cog.create_giveaway(
                interaction=interaction,
                duration_seconds=self.duration_seconds,
                winner_count=self.winner_count,
                prize=self.prize,
                description=self.description,
            )

        except Exception:
            log.exception(
                "Failed to create giveaway"
            )

            await interaction.edit_original_response(
                embed=discord.Embed(
                    title=(
                        f"{EMOJI['error']} "
                        "Giveaway Creation Failed"
                    ),
                    description=(
                        "The giveaway could not be "
                        "published. Nothing was left active."
                    ),
                    color=discord.Color.red(),
                ),
                view=None,
            )

            return

        await interaction.edit_original_response(
            embed=discord.Embed(
                title=(
                    f"{EMOJI['approved']} "
                    "Giveaway Published"
                ),
                description=(
                    f"Your giveaway is now live in "
                    f"<#{state.channel_id}>.\n\n"
                    f"**Giveaway ID:** "
                    f"`{state.giveaway_id}`\n"
                    f"**Randomizer:** "
                    f"`{state.randomizer_version}`\n"
                    f"**Commitment:** "
                    f"`{state.commitment}`"
                ),
                color=discord.Color.green(),
            ),
            view=None,
        )

        self.stop()

    @discord.ui.button(
        label="Cancel",
        emoji=EMOJI["denied"],
        style=discord.ButtonStyle.danger,
    )
    async def cancel(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        await interaction.response.edit_message(
            embed=discord.Embed(
                title=(
                    f"{EMOJI['denied']} "
                    "Giveaway Cancelled"
                ),
                description="No giveaway was created.",
                color=discord.Color.red(),
            ),
            view=None,
        )

        self.stop()

    async def on_timeout(self) -> None:
        for child in self.children:
            if isinstance(
                child,
                discord.ui.Button,
            ):
                child.disabled = True


class Giveaway(commands.Cog):
    def __init__(
        self,
        bot: commands.Bot,
    ):
        self.bot = bot

        self._active: dict[
            str,
            GiveawayState,
        ] = {}

        self._locks: dict[
            str,
            asyncio.Lock,
        ] = {}

        self._restored = False

        self.expiry_loop.start()

    def cog_unload(self) -> None:
        self.expiry_loop.cancel()

    @property
    def repository(self):
        repository = db.giveaways

        if repository is None:
            raise RuntimeError(
                "Giveaway repository is not initialized."
            )

        return repository

    def get_lock(
        self,
        giveaway_id: str,
    ) -> asyncio.Lock:
        lock = self._locks.get(
            giveaway_id
        )

        if lock is None:
            lock = asyncio.Lock()
            self._locks[giveaway_id] = lock

        return lock

    async def cog_load(self) -> None:
        await self.restore_active_giveaways()

    async def restore_active_giveaways(
        self,
    ) -> None:
        if db.giveaways is None:
            log.error(
                "Giveaway repository is not initialized during restore."
            )
            return

        restored = 0

        try:
            result = await db.query(
                """
                SELECT *
                FROM giveaways
                WHERE state = 'active'
                ALLOW FILTERING
                """
            )

            now = utcnow()

            for row in result.all():
                state = GiveawayState.from_row(
                    row
                )

                try:
                    ends_at = datetime.fromisoformat(
                        state.ends_at
                    )
                except ValueError:
                    log.error(
                        "Invalid expiration for restored giveaway %s",
                        state.giveaway_id,
                    )
                    continue

                if ends_at <= now:
                    continue

                self._active[
                    state.giveaway_id
                ] = state

                if state.message_id:
                    self.bot.add_view(
                        GiveawayEntryView(
                            self,
                            state.giveaway_id,
                        ),
                        message_id=int(
                            state.message_id
                        ),
                    )

                restored += 1

        except Exception:
            log.exception(
                "Failed to restore active giveaways from Scylla."
            )
            return

        self._restored = True

        log.info(
            "Restored %d active giveaway(s).",
            restored,
        )

    async def load(
        self,
        giveaway_id: str,
        *,
        refresh: bool = False,
    ) -> Optional[GiveawayState]:
        giveaway_id = str(
            giveaway_id
        ).strip()

        if not giveaway_id:
            return None

        if (
            not refresh
            and giveaway_id in self._active
        ):
            cached = self._active[
                giveaway_id
            ]

            if (
                not cached.ended
                and not cached.deleted
            ):
                return cached

        row = await self.repository.get(
            giveaway_id
        )

        if row is None:
            self._active.pop(
                giveaway_id,
                None,
            )
            return None

        state = GiveawayState.from_row(
            row
        )

        self._active[
            giveaway_id
        ] = state

        return state

    async def resolve_identifier(
        self,
        identifier: str,
    ) -> Optional[GiveawayState]:
        identifier = identifier.strip()

        if not identifier:
            return None

        state = await self.load(
            identifier,
            refresh=True,
        )

        if state is not None:
            return state

        if not identifier.isdigit():
            return None

        row = await self.repository.get_by_message(
            identifier
        )

        if row is None:
            return None

        state = GiveawayState.from_row(
            row
        )

        self._active[
            state.giveaway_id
        ] = state

        return state

    async def save_metadata(
        self,
        state: GiveawayState,
    ) -> None:
        await self.repository.update_metadata(
            state.giveaway_id,
            state.metadata(),
        )

        self._active[
            state.giveaway_id
        ] = state

    async def create_giveaway(
        self,
        *,
        interaction: discord.Interaction,
        duration_seconds: int,
        winner_count: int,
        prize: str,
        description: str,
    ) -> GiveawayState:
        if (
            interaction.guild is None
            or interaction.channel_id is None
        ):
            raise ValueError(
                "Giveaways can only be created in a server channel."
            )

        if not 1 <= winner_count <= MAX_WINNERS:
            raise ValueError(
                "Invalid winner count."
            )

        if not 1 <= duration_seconds <= MAX_DURATION_SECONDS:
            raise ValueError(
                "Invalid giveaway duration."
            )

        giveaway_id = str(
            uuid.uuid4()
        )

        ends_at = (
            utcnow()
            + timedelta(
                seconds=duration_seconds
            )
        )

        seed = (
            CryptographicRandomizer.generate_seed()
        )

        commitment = (
            CryptographicRandomizer.commitment(
                seed
            )
        )

        state = GiveawayState(
            giveaway_id=giveaway_id,
            guild_id=str(
                interaction.guild.id
            ),
            channel_id=str(
                interaction.channel_id
            ),
            message_id=None,
            host_id=str(
                interaction.user.id
            ),
            prize=prize[:MAX_PRIZE_LENGTH],
            description=description[
                :MAX_DESCRIPTION_LENGTH
            ],
            winner_count=winner_count,
            duration_seconds=duration_seconds,
            ends_at=ends_at.isoformat(),
            seed_hex=seed.hex(),
            commitment=commitment,
            randomizer_version=(
                CryptographicRandomizer.algorithm
            ),
        )

        channel = interaction.channel

        if not isinstance(
            channel,
            discord.abc.Messageable,
        ):
            raise ValueError(
                "This channel cannot receive giveaway messages."
            )

        message = await channel.send(
            embed=self.build_public_embed(
                state,
                participant_count=0,
            ),
            view=GiveawayEntryView(
                self,
                giveaway_id,
            ),
            allowed_mentions=discord.AllowedMentions.none(),
        )

        state.message_id = str(
            message.id
        )

        state.channel_id = str(
            channel.id
        )

        try:
            await self.repository.create(
                giveaway_id=state.giveaway_id,
                message_id=message.id,
                channel_id=channel.id,
                guild_id=interaction.guild.id,
                host_id=interaction.user.id,
                duration_seconds=state.duration_seconds,
                prize=state.prize,
                description=state.description,
                winners_count=state.winner_count,
                created_at=utcnow(),
                ends_at=ends_at,
                metadata=state.metadata(),
            )

        except Exception:
            try:
                await message.delete()
            except discord.HTTPException:
                log.exception(
                    "Could not remove orphaned giveaway message %s",
                    message.id,
                )

            raise

        self._active[
            state.giveaway_id
        ] = state

        return state

    def draw(
        self,
        state: GiveawayState,
        *,
        participants: list[str],
        winner_count: int,
        round_number: int,
    ) -> RandomSelection:
        if not state.seed_hex:
            raise RuntimeError(
                "Giveaway is missing its cryptographic seed."
            )

        if not participants:
            raise ValueError(
                "No eligible participants."
            )

        if winner_count <= 0:
            raise ValueError(
                "Winner count must be greater than zero."
            )

        if winner_count > len(participants):
            raise ValueError(
                "Not enough eligible participants."
            )

        return CryptographicRandomizer.select(
            seed=bytes.fromhex(
                state.seed_hex
            ),
            giveaway_id=state.giveaway_id,
            guild_id=state.guild_id,
            message_id=state.message_id or "",
            participants=participants,
            winner_count=winner_count,
            round_number=round_number,
        )

    def record_result(
        self,
        state: GiveawayState,
        result: RandomSelection,
        *,
        eligible_participants: list[str],
        round_number: int,
    ) -> dict[str, Any]:
        payload = {
            "round_number": round_number,
            "winners": list(
                result.winners
            ),
            "eligible_participants": list(
                eligible_participants
            ),
            "participant_count": len(
                eligible_participants
            ),
            "winner_count": len(
                result.winners
            ),
            "commitment": result.commitment,
            "proof": result.proof,
            "algorithm": result.algorithm,
            "generated_at": utcnow().isoformat(),
        }

        state.last_result = payload

        state.draw_history.append(
            payload
        )

        return payload

    async def handle_entry(
        self,
        interaction: discord.Interaction,
        giveaway_id: str,
    ) -> None:
        if interaction.guild_id is None:
            await interaction.response.send_message(
                (
                    f"{EMOJI['error']} "
                    "Giveaways can only be entered in a server."
                ),
                ephemeral=True,
            )
            return

        lock = self.get_lock(
            giveaway_id
        )

        async with lock:
            state = await self.load(
                giveaway_id,
                refresh=True,
            )

            if state is None or state.deleted:
                await interaction.response.send_message(
                    (
                        f"{EMOJI['error']} "
                        "This giveaway no longer exists."
                    ),
                    ephemeral=True,
                )
                return

            if state.guild_id != str(
                interaction.guild_id
            ):
                await interaction.response.send_message(
                    (
                        f"{EMOJI['error']} "
                        "This giveaway belongs to another server."
                    ),
                    ephemeral=True,
                )
                return

            if state.ended:
                await interaction.response.send_message(
                    (
                        f"{EMOJI['denied']} "
                        "This giveaway has already ended."
                    ),
                    ephemeral=True,
                )
                return

            try:
                ends_at = datetime.fromisoformat(
                    state.ends_at
                )
            except ValueError:
                await interaction.response.send_message(
                    (
                        f"{EMOJI['error']} "
                        "This giveaway has an invalid expiration time."
                    ),
                    ephemeral=True,
                )
                return

            if ends_at <= utcnow():
                await interaction.response.send_message(
                    (
                        f"{EMOJI['denied']} "
                        "This giveaway has expired."
                    ),
                    ephemeral=True,
                )
                return

            user_id = str(
                interaction.user.id
            )

            participants = set(
                state.participants
            )

            try:
                if user_id in participants:
                    await self.repository.remove_entry(
                        state.giveaway_id,
                        user_id,
                    )

                    participants.remove(
                        user_id
                    )

                    message_text = (
                        f"{EMOJI['denied']} "
                        "You left the giveaway."
                    )

                else:
                    await self.repository.add_entry(
                        state.giveaway_id,
                        user_id,
                    )

                    participants.add(
                        user_id
                    )

                    message_text = (
                        f"{EMOJI['approved']} "
                        "You entered the giveaway. Good luck!"
                    )

            except Exception:
                log.exception(
                    "Failed to update giveaway entry: %s",
                    state.giveaway_id,
                )

                await interaction.response.send_message(
                    (
                        f"{EMOJI['error']} "
                        "Your giveaway entry could not be updated."
                    ),
                    ephemeral=True,
                )

                return

            state.participants = sorted(
                participants
            )

            self._active[
                state.giveaway_id
            ] = state

            await interaction.response.send_message(
                message_text,
                ephemeral=True,
            )

            try:
                await self.update_public_message(
                    state
                )

            except discord.NotFound:
                log.warning(
                    "Giveaway message %s no longer exists",
                    state.message_id,
                )

            except discord.HTTPException:
                log.exception(
                    "Failed to update giveaway message %s",
                    state.message_id,
                )

    async def update_public_message(
        self,
        state: GiveawayState,
    ) -> None:
        if not state.message_id:
            return

        channel = self.bot.get_channel(
            int(state.channel_id)
        )

        if channel is None:
            channel = await self.bot.fetch_channel(
                int(state.channel_id)
            )

        if not isinstance(
            channel,
            discord.abc.Messageable,
        ):
            return

        message = await channel.fetch_message(
            int(state.message_id)
        )

        await message.edit(
            embed=self.build_public_embed(
                state,
                participant_count=len(
                    state.participants
                ),
            ),
            view=GiveawayEntryView(
                self,
                state.giveaway_id,
            ),
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @tasks.loop(seconds=15)
    async def expiry_loop(self) -> None:
        if db.giveaways is None:
            return

        now = utcnow()

        for giveaway_id, state in list(
            self._active.items()
        ):
            if state.deleted or state.ended:
                continue

            try:
                ends_at = datetime.fromisoformat(
                    state.ends_at
                )
            except ValueError:
                log.error(
                    "Invalid expiration for giveaway %s",
                    giveaway_id,
                )
                continue

            if ends_at <= now:
                try:
                    await self.finish_giveaway(
                        giveaway_id
                    )

                except Exception:
                    log.exception(
                        "Failed to auto-finish giveaway %s",
                        giveaway_id,
                    )

    @expiry_loop.before_loop
    async def before_expiry_loop(
        self,
    ) -> None:
        await self.bot.wait_until_ready()

        while db.giveaways is None:
            await asyncio.sleep(1)

    async def finish_giveaway(
        self,
        giveaway_id: str,
    ) -> Optional[RandomSelection]:
        lock = self.get_lock(
            giveaway_id
        )

        async with lock:
            state = await self.load(
                giveaway_id,
                refresh=True,
            )

            if (
                state is None
                or state.deleted
                or state.ended
            ):
                return None

            participants = sorted(
                set(state.participants)
            )

            state.participants = participants

            if not participants:
                state.ended = True

                await self.repository.end(
                    state.giveaway_id,
                    winners=set(),
                    ended_at=utcnow(),
                )

                self._active[
                    state.giveaway_id
                ] = state

                await self.announce_end(
                    state,
                    result=None,
                )

                return None

            winner_count = min(
                state.winner_count,
                len(participants),
            )

            result = self.draw(
                state,
                participants=participants,
                winner_count=winner_count,
                round_number=1,
            )

            self.record_result(
                state,
                result,
                eligible_participants=participants,
                round_number=1,
            )

            state.round_number = 1
            state.ended = True

            await self.repository.end(
                state.giveaway_id,
                winners=set(
                    result.winners
                ),
                ended_at=utcnow(),
            )

            await self.save_metadata(
                state
            )

            self._active[
                state.giveaway_id
            ] = state

            await self.announce_end(
                state,
                result=result,
            )

            return result

    async def delete_giveaway(
        self,
        state: GiveawayState,
    ) -> None:
        lock = self.get_lock(
            state.giveaway_id
        )

        async with lock:
            current = await self.load(
                state.giveaway_id,
                refresh=True,
            )

            if current is None:
                return

            state = current

            channel = self.bot.get_channel(
                int(state.channel_id)
            )

            if (
                channel is not None
                and state.message_id
            ):
                try:
                    message = await channel.fetch_message(
                        int(state.message_id)
                    )

                    await message.delete()

                except discord.NotFound:
                    pass

                except discord.HTTPException:
                    log.exception(
                        "Failed to delete giveaway message %s",
                        state.message_id,
                    )

            await self.repository.delete(
                state.giveaway_id
            )

            self._active.pop(
                state.giveaway_id,
                None,
            )

            self._locks.pop(
                state.giveaway_id,
                None,
            )

    async def reroll_giveaway(
        self,
        state: GiveawayState,
        amount: int,
    ) -> RandomSelection:
        if not state.ended:
            raise ValueError(
                "Giveaway has not ended."
            )

        if state.deleted:
            raise ValueError(
                "Giveaway was deleted."
            )

        if not state.participants:
            raise ValueError(
                "There are no participants."
            )

        if amount <= 0 or amount > MAX_WINNERS:
            raise ValueError(
                f"Amount must be between 1 and {MAX_WINNERS}."
            )

        previous_winners: set[str] = set()

        for history in state.draw_history:
            previous_winners.update(
                normalize_ids(
                    history.get(
                        "winners",
                        [],
                    )
                )
            )

        eligible = sorted(
            set(
                state.participants
            )
            - previous_winners
        )

        if not eligible:
            raise ValueError(
                "No eligible participants remain."
            )

        if amount > len(eligible):
            raise ValueError(
                (
                    f"Only {len(eligible)} "
                    "eligible participant(s) remain."
                )
            )

        next_round = (
            max(
                (
                    int(
                        entry.get(
                            "round_number",
                            1,
                        )
                        or 1
                    )
                    for entry in state.draw_history
                ),
                default=1,
            )
            + 1
        )

        result = self.draw(
            state,
            participants=eligible,
            winner_count=amount,
            round_number=next_round,
        )

        self.record_result(
            state,
            result,
            eligible_participants=eligible,
            round_number=next_round,
        )

        state.round_number = next_round

        await self.save_metadata(
            state
        )

        return result

    def build_preview_embed(
        self,
        interaction: discord.Interaction,
        *,
        duration_seconds: int,
        winner_count: int,
        prize: str,
        description: str,
    ) -> discord.Embed:
        embed = discord.Embed(
            title=(
                f"{EMOJI['gift']} "
                "Giveaway Preview"
            ),
            description=description,
            color=discord.Color.blurple(),
        )

        embed.add_field(
            name="Prize",
            value=prize,
            inline=False,
        )

        embed.add_field(
            name="Duration",
            value=format_duration(
                duration_seconds
            ),
            inline=True,
        )

        embed.add_field(
            name="Winners",
            value=str(
                winner_count
            ),
            inline=True,
        )

        embed.add_field(
            name="Hosted By",
            value=interaction.user.mention,
            inline=True,
        )

        embed.set_footer(
            text="Review the details before publishing."
        )

        return embed

    def build_public_embed(
        self,
        state: GiveawayState,
        *,
        participant_count: Optional[int] = None,
    ) -> discord.Embed:
        ends_at = datetime.fromisoformat(
            state.ends_at
        )

        count = (
            len(state.participants)
            if participant_count is None
            else participant_count
        )

        embed = discord.Embed(
            title=(
                f"{EMOJI['gift']} "
                f"{state.prize}"
            ),
            description=(
                f"{state.description}\n\n"
                f"{EMOJI['staff']} "
                f"**Host:** <@{state.host_id}>\n"
                f"{EMOJI['yellowstar']} "
                f"**Winners:** `{state.winner_count}`\n"
                f"{EMOJI['loading']} "
                f"**Ends:** "
                f"<t:{int(ends_at.timestamp())}:R>\n"
                f"👥 **Entries:** `{count:,}`\n\n"
                "Press **Enter Giveaway** below to join."
            ),
            color=discord.Color.blurple(),
        )

        embed.add_field(
            name="Fairness Commitment",
            value=(
                f"`{state.commitment or 'Unavailable'}`"
            ),
            inline=False,
        )

        embed.add_field(
            name="Randomizer",
            value=(
                f"`{state.randomizer_version}`"
            ),
            inline=True,
        )

        embed.add_field(
            name="Duration",
            value=(
                f"`{format_duration(state.duration_seconds)}`"
            ),
            inline=True,
        )

        embed.set_footer(
            text=(
                f"Giveaway ID: "
                f"{state.giveaway_id}"
            )
        )

        return embed

    def build_result_embed(
        self,
        state: GiveawayState,
        result: RandomSelection,
    ) -> discord.Embed:
        embed = discord.Embed(
            title=(
                f"{EMOJI['gift']} "
                "Giveaway Results"
            ),
            description=(
                f"Congratulations "
                f"{mention_users(list(result.winners))}!\n\n"
                f"**Prize:** {state.prize}"
            ),
            color=discord.Color.gold(),
        )

        embed.add_field(
            name="Winners",
            value=str(
                len(result.winners)
            ),
            inline=True,
        )

        embed.add_field(
            name="Round",
            value=str(
                state.round_number
            ),
            inline=True,
        )

        embed.add_field(
            name="Algorithm",
            value=f"`{result.algorithm}`",
            inline=True,
        )

        embed.add_field(
            name="Commitment",
            value=f"`{result.commitment}`",
            inline=False,
        )

        embed.add_field(
            name="Selection Proof",
            value=f"`{result.proof}`",
            inline=False,
        )

        if state.seed_hex:
            embed.add_field(
                name="Revealed Seed",
                value=f"`{state.seed_hex}`",
                inline=False,
            )

        embed.set_footer(
            text=(
                f"Giveaway ID: "
                f"{state.giveaway_id} "
                "• Use /gverify to verify"
            )
        )

        return embed

    def build_reroll_embed(
        self,
        state: GiveawayState,
        result: RandomSelection,
    ) -> discord.Embed:
        embed = discord.Embed(
            title=(
                f"{EMOJI['gift']} "
                "Giveaway Reroll"
            ),
            description=(
                f"New winner(s): "
                f"{mention_users(list(result.winners))}\n\n"
                f"**Prize:** {state.prize}"
            ),
            color=discord.Color.orange(),
        )

        embed.add_field(
            name="Round",
            value=str(
                state.round_number
            ),
            inline=True,
        )

        embed.add_field(
            name="Winners",
            value=str(
                len(result.winners)
            ),
            inline=True,
        )

        embed.add_field(
            name="Proof",
            value=f"`{result.proof}`",
            inline=False,
        )

        embed.set_footer(
            text=(
                f"Giveaway ID: "
                f"{state.giveaway_id}"
            )
        )

        return embed

    async def announce_end(
        self,
        state: GiveawayState,
        *,
        result: Optional[RandomSelection],
    ) -> None:
        channel = self.bot.get_channel(
            int(state.channel_id)
        )

        if channel is None:
            try:
                channel = await self.bot.fetch_channel(
                    int(state.channel_id)
                )

            except discord.HTTPException:
                log.exception(
                    "Could not resolve giveaway channel %s",
                    state.channel_id,
                )
                return

        result_embed = (
            self.build_result_embed(
                state,
                result,
            )
            if result is not None
            else discord.Embed(
                title=(
                    f"{EMOJI['denied']} "
                    "Giveaway Ended"
                ),
                description=(
                    f"**Prize:** {state.prize}\n\n"
                    "No one entered the giveaway, "
                    "so no winners were drawn."
                ),
                color=discord.Color.red(),
            )
        )

        if state.message_id:
            try:
                message = await channel.fetch_message(
                    int(state.message_id)
                )

                await message.edit(
                    embed=result_embed,
                    view=GiveawayEndedView(),
                    allowed_mentions=(
                        discord.AllowedMentions.none()
                    ),
                )

            except discord.NotFound:
                log.warning(
                    "Giveaway message %s was not found",
                    state.message_id,
                )

            except discord.HTTPException:
                log.exception(
                    "Failed to update ended giveaway %s",
                    state.giveaway_id,
                )

        await channel.send(
            embed=result_embed,
            allowed_mentions=(
                discord.AllowedMentions(
                    users=True
                )
            ),
        )

    @app_commands.command(
        name="gcreate",
        description=(
            "Create a new cryptographically fair giveaway."
        ),
    )
    @app_commands.default_permissions(
        manage_guild=True
    )
    @app_commands.checks.has_permissions(
        manage_guild=True
    )
    async def gcreate(
        self,
        interaction: discord.Interaction,
    ) -> None:
        if interaction.guild is None:
            await interaction.response.send_message(
                "Giveaways can only be created inside a server.",
                ephemeral=True,
            )
            return

        await interaction.response.send_modal(
            GiveawayCreateModal(
                self,
                interaction.user.id,
            )
        )

    @app_commands.command(
        name="gdelete",
        description=(
            "Delete a giveaway using its ID or message ID."
        ),
    )
    @app_commands.describe(
        giveaway="Giveaway ID or Discord message ID."
    )
    @app_commands.default_permissions(
        manage_guild=True
    )
    @app_commands.checks.has_permissions(
        manage_guild=True
    )
    async def gdelete(
        self,
        interaction: discord.Interaction,
        giveaway: str,
    ) -> None:
        await interaction.response.defer(
            ephemeral=True
        )

        state = await self.resolve_identifier(
            giveaway
        )

        if state is None:
            await interaction.followup.send(
                (
                    f"{EMOJI['error']} "
                    "No giveaway found."
                ),
                ephemeral=True,
            )
            return

        await self.delete_giveaway(
            state
        )

        await interaction.followup.send(
            embed=discord.Embed(
                title=(
                    f"{EMOJI['approved']} "
                    "Giveaway Deleted"
                ),
                description=(
                    f"**Prize:** {state.prize}\n"
                    f"**Giveaway ID:** "
                    f"`{state.giveaway_id}`"
                ),
                color=discord.Color.green(),
            ),
            ephemeral=True,
        )

    @app_commands.command(
        name="gend",
        description=(
            "End a giveaway immediately and draw its winners."
        ),
    )
    @app_commands.describe(
        giveaway="Giveaway ID or Discord message ID."
    )
    @app_commands.default_permissions(
        manage_guild=True
    )
    @app_commands.checks.has_permissions(
        manage_guild=True
    )
    async def gend(
        self,
        interaction: discord.Interaction,
        giveaway: str,
    ) -> None:
        await interaction.response.defer(
            ephemeral=True
        )

        state = await self.resolve_identifier(
            giveaway
        )

        if state is None:
            await interaction.followup.send(
                (
                    f"{EMOJI['error']} "
                    "No giveaway found."
                ),
                ephemeral=True,
            )
            return

        if state.ended:
            await interaction.followup.send(
                (
                    f"{EMOJI['denied']} "
                    "That giveaway has already ended."
                ),
                ephemeral=True,
            )
            return

        await interaction.edit_original_response(
            embed=discord.Embed(
                title=(
                    f"{EMOJI['loading']} "
                    "Finalizing Giveaway"
                ),
                description=(
                    "Locking entries...\n"
                    "Freezing participants...\n"
                    "Preparing cryptographic draw..."
                ),
                color=discord.Color.blurple(),
            )
        )

        await asyncio.sleep(
            FAKE_LOADING_SECONDS
        )

        try:
            result = await self.finish_giveaway(
                state.giveaway_id
            )

        except Exception:
            log.exception(
                "Failed to manually end giveaway %s",
                state.giveaway_id,
            )

            await interaction.edit_original_response(
                embed=discord.Embed(
                    title=(
                        f"{EMOJI['error']} "
                        "Giveaway Finalization Failed"
                    ),
                    description=(
                        "The giveaway could not be finalized."
                    ),
                    color=discord.Color.red(),
                )
            )

            return

        await interaction.edit_original_response(
            embed=discord.Embed(
                title=(
                    f"{EMOJI['approved']} "
                    "Giveaway Ended"
                ),
                description=(
                    f"**Prize:** {state.prize}\n"
                    f"**Giveaway ID:** "
                    f"`{state.giveaway_id}`\n\n"
                    + (
                        (
                            f"Winners: "
                            f"{mention_users(list(result.winners))}"
                        )
                        if result is not None
                        else "No participants entered."
                    )
                ),
                color=discord.Color.green(),
            )
        )

    @app_commands.command(
        name="greroll",
        description=(
            "Cryptographically reroll winners."
        ),
    )
    @app_commands.describe(
        message_id=(
            "The giveaway Discord message ID."
        ),
        amount=(
            "Number of new winners. "
            "Defaults to the original winner count."
        ),
    )
    @app_commands.default_permissions(
        manage_guild=True
    )
    @app_commands.checks.has_permissions(
        manage_guild=True
    )
    async def greroll(
        self,
        interaction: discord.Interaction,
        message_id: str,
        amount: Optional[
            app_commands.Range[
                int,
                1,
                MAX_WINNERS
            ]
        ] = None,
    ) -> None:
        await interaction.response.defer(
            ephemeral=True
        )

        state = await self.resolve_identifier(
            message_id
        )

        if state is None:
            await interaction.followup.send(
                (
                    f"{EMOJI['error']} "
                    "No giveaway found for that message ID."
                ),
                ephemeral=True,
            )
            return

        if not state.ended:
            await interaction.followup.send(
                (
                    f"{EMOJI['denied']} "
                    "That giveaway has not ended yet."
                ),
                ephemeral=True,
            )
            return

        requested_amount = int(
            amount
            or state.winner_count
        )

        lock = self.get_lock(
            state.giveaway_id
        )

        try:
            async with lock:
                state = await self.load(
                    state.giveaway_id,
                    refresh=True,
                )

                if state is None:
                    raise ValueError(
                        "Giveaway no longer exists."
                    )

                result = await self.reroll_giveaway(
                    state,
                    requested_amount,
                )

        except ValueError as exc:
            await interaction.followup.send(
                (
                    f"{EMOJI['error']} "
                    f"{exc}"
                ),
                ephemeral=True,
            )
            return

        except Exception:
            log.exception(
                "Reroll failed for giveaway %s",
                state.giveaway_id,
            )

            await interaction.followup.send(
                (
                    f"{EMOJI['error']} "
                    "The reroll failed."
                ),
                ephemeral=True,
            )
            return

        channel = self.bot.get_channel(
            int(state.channel_id)
        )

        if channel is not None:
            await channel.send(
                embed=self.build_reroll_embed(
                    state,
                    result,
                ),
                allowed_mentions=(
                    discord.AllowedMentions(
                        users=True
                    )
                ),
            )

        await interaction.followup.send(
            embed=discord.Embed(
                title=(
                    f"{EMOJI['approved']} "
                    "Reroll Complete"
                ),
                description=(
                    f"New winner(s): "
                    f"{mention_users(list(result.winners))}\n\n"
                    f"**Round:** "
                    f"{state.round_number}\n"
                    f"**Proof:** "
                    f"`{result.proof}`"
                ),
                color=discord.Color.green(),
            ),
            ephemeral=True,
        )

    @app_commands.command(
        name="gverify",
        description=(
            "Verify a completed giveaway's cryptographic result."
        ),
    )
    @app_commands.describe(
        giveaway="Giveaway ID or Discord message ID."
    )
    async def gverify(
        self,
        interaction: discord.Interaction,
        giveaway: str,
    ) -> None:
        await interaction.response.defer(
            ephemeral=True
        )

        state = await self.resolve_identifier(
            giveaway
        )

        if (
            state is None
            or not state.ended
            or not state.last_result
            or not state.seed_hex
            or not state.message_id
        ):
            await interaction.followup.send(
                (
                    f"{EMOJI['error']} "
                    "No completed verifiable giveaway was found."
                ),
                ephemeral=True,
            )
            return

        result = state.last_result

        participants = normalize_ids(
            result.get(
                "eligible_participants",
                [],
            )
        )

        winners = normalize_ids(
            result.get(
                "winners",
                [],
            )
        )

        winner_count = int(
            result.get(
                "winner_count",
                len(winners),
            )
            or len(winners)
        )

        round_number = int(
            result.get(
                "round_number",
                1,
            )
            or 1
        )

        try:
            valid = CryptographicRandomizer.verify(
                seed=bytes.fromhex(
                    state.seed_hex
                ),
                giveaway_id=state.giveaway_id,
                guild_id=state.guild_id,
                message_id=state.message_id,
                participants=participants,
                winner_count=winner_count,
                expected_winners=winners,
                expected_commitment=str(
                    result.get(
                        "commitment",
                        "",
                    )
                ),
                expected_proof=str(
                    result.get(
                        "proof",
                        "",
                    )
                ),
                round_number=round_number,
            )

        except (
            ValueError,
            TypeError,
        ) as exc:
            await interaction.followup.send(
                embed=discord.Embed(
                    title=(
                        f"{EMOJI['error']} "
                        "Verification Failed"
                    ),
                    description=(
                        "The stored draw could not be verified.\n\n"
                        f"`{exc}`"
                    ),
                    color=discord.Color.red(),
                ),
                ephemeral=True,
            )
            return

        if valid:
            embed = discord.Embed(
                title=(
                    f"{EMOJI['approved']} "
                    "Giveaway Verified"
                ),
                description=(
                    "The stored seed, participant set, "
                    "winner set, commitment, and proof are "
                    "consistent with the recorded draw."
                ),
                color=discord.Color.green(),
            )

        else:
            embed = discord.Embed(
                title=(
                    f"{EMOJI['error']} "
                    "Giveaway Verification Failed"
                ),
                description=(
                    "The stored result does not match "
                    "the recorded cryptographic inputs."
                ),
                color=discord.Color.red(),
            )

        embed.add_field(
            name="Giveaway",
            value=(
                f"`{state.giveaway_id}`"
            ),
            inline=False,
        )

        embed.add_field(
            name="Round",
            value=str(
                round_number
            ),
            inline=True,
        )

        embed.add_field(
            name="Winners",
            value=str(
                winner_count
            ),
            inline=True,
        )

        embed.add_field(
            name="Algorithm",
            value=(
                f"`{result.get(
                    'algorithm',
                    state.randomizer_version
                )}`"
            ),
            inline=True,
        )

        await interaction.followup.send(
            embed=embed,
            ephemeral=True,
        )


async def setup(
    bot: commands.Bot,
) -> None:
    await bot.add_cog(
        Giveaway(bot)
    )