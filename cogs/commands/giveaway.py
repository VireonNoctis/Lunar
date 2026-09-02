from __future__ import annotations

import asyncio
import json
import logging
import uuid

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

import discord

from discord import app_commands
from discord.ext import commands, tasks

from cogs.utilities.database import db
from cogs.utilities.emoji import EMOJI
from cogs.utilities.randomizer import (
    CryptographicRandomizer,
    RandomSelection,
)


# ============================================================
# LOGGING
# ============================================================

log = logging.getLogger(
    "lunar.giveaway"
)


# ============================================================
# CONSTANTS
# ============================================================

EXTENSION_NAMESPACE = "giveaways"

MAX_WINNERS = 100
MAX_PRIZE_LENGTH = 200
MAX_DESCRIPTION_LENGTH = 1500

FAKE_LOADING_SECONDS = 2.0


# ============================================================
# HELPERS
# ============================================================

def utcnow() -> datetime:
    return datetime.now(
        timezone.utc
    )


def parse_duration(
    value: str,
) -> Optional[int]:

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
        if char.isdigit():
            number += char
        else:
            break

    if not number:
        return None

    unit = value[len(number):]

    if unit not in units:
        return None

    seconds = (
        int(number)
        * units[unit]
    )

    if seconds <= 0:
        return None

    return seconds


def format_duration(
    seconds: int,
) -> str:

    if seconds % 604800 == 0:
        return (
            f"{seconds // 604800} week(s)"
        )

    if seconds % 86400 == 0:
        return (
            f"{seconds // 86400} day(s)"
        )

    if seconds % 3600 == 0:
        return (
            f"{seconds // 3600} hour(s)"
        )

    if seconds % 60 == 0:
        return (
            f"{seconds // 60} minute(s)"
        )

    return (
        f"{seconds} second(s)"
    )


def mention_users(
    user_ids: list[str] | tuple[str, ...],
) -> str:

    if not user_ids:
        return "No winners."

    return ", ".join(
        f"<@{user_id}>"
        for user_id in user_ids
    )


# ============================================================
# GIVEAWAY STATE
# ============================================================

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

    participants: list[str] = field(
        default_factory=list
    )

    seed_hex: Optional[str] = None
    commitment: Optional[str] = None

    randomizer_version: str = (
        CryptographicRandomizer.algorithm
    )

    ended: bool = False
    deleted: bool = False

    round_number: int = 1

    last_result: Optional[dict] = None

    draw_history: list[dict] = field(
        default_factory=list
    )

    def to_dict(self) -> dict:

        return {
            "giveaway_id": self.giveaway_id,
            "guild_id": self.guild_id,
            "channel_id": self.channel_id,
            "message_id": self.message_id,
            "host_id": self.host_id,
            "prize": self.prize,
            "description": self.description,
            "winner_count": self.winner_count,
            "duration_seconds": self.duration_seconds,
            "ends_at": self.ends_at,
            "participants": self.participants,
            "seed_hex": self.seed_hex,
            "commitment": self.commitment,
            "randomizer_version": self.randomizer_version,
            "ended": self.ended,
            "deleted": self.deleted,
            "round_number": self.round_number,
            "last_result": self.last_result,
            "draw_history": self.draw_history,
        }

    @classmethod
    def from_dict(
        cls,
        payload: dict,
    ) -> "GiveawayState":

        return cls(
            giveaway_id=str(
                payload["giveaway_id"]
            ),
            guild_id=str(
                payload["guild_id"]
            ),
            channel_id=str(
                payload["channel_id"]
            ),
            message_id=(
                str(
                    payload["message_id"]
                )
                if payload.get(
                    "message_id"
                )
                else None
            ),
            host_id=str(
                payload["host_id"]
            ),
            prize=str(
                payload["prize"]
            ),
            description=str(
                payload.get(
                    "description",
                    "",
                )
            ),
            winner_count=int(
                payload["winner_count"]
            ),
            duration_seconds=int(
                payload.get(
                    "duration_seconds",
                    0,
                )
            ),
            ends_at=str(
                payload["ends_at"]
            ),
            participants=[
                str(user_id)
                for user_id in payload.get(
                    "participants",
                    [],
                )
            ],
            seed_hex=payload.get(
                "seed_hex"
            ),
            commitment=payload.get(
                "commitment"
            ),
            randomizer_version=str(
                payload.get(
                    "randomizer_version",
                    CryptographicRandomizer.algorithm,
                )
            ),
            ended=bool(
                payload.get(
                    "ended",
                    False,
                )
            ),
            deleted=bool(
                payload.get(
                    "deleted",
                    False,
                )
            ),
            round_number=int(
                payload.get(
                    "round_number",
                    1,
                )
            ),
            last_result=payload.get(
                "last_result"
            ),
            draw_history=list(
                payload.get(
                    "draw_history",
                    [],
                )
            ),
        )


# ============================================================
# GIVEAWAY ENTRY VIEW
# ============================================================

class GiveawayEntryView(
    discord.ui.View
):

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

        self.add_item(
            discord.ui.Button(
                label="Enter Giveaway",
                emoji=EMOJI["gift"],
                style=discord.ButtonStyle.blurple,
                custom_id=(
                    f"giveaway:enter:{giveaway_id}"
                ),
            )
        )

        self.children[0].callback = (
            self.enter
        )

    async def enter(
        self,
        interaction: discord.Interaction,
    ):

        await self.cog.handle_entry(
            interaction,
            self.giveaway_id,
        )


# ============================================================
# ENDED VIEW
# ============================================================

class GiveawayEndedView(
    discord.ui.View
):

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


# ============================================================
# CREATE MODAL
# ============================================================

class GiveawayCreateModal(
    discord.ui.Modal
):

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
            max_length=2,
            required=True,
        )

        self.prize_input = discord.ui.TextInput(
            label="Prize",
            placeholder="Example: 1,000,000 Coins",
            max_length=MAX_PRIZE_LENGTH,
            required=True,
        )

        self.description_input = discord.ui.TextInput(
            label="Description",
            placeholder="Explain the giveaway and any important details.",
            style=discord.TextStyle.paragraph,
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
    ):

        if (
            interaction.user.id
            != self.author_id
        ):

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
                "Invalid duration. Use formats such as `30s`, `15m`, `2h`, `3d`, or `1w`.",
                ephemeral=True,
            )

            return

        try:
            winner_count = int(
                self.winners_input.value.strip()
            )

        except ValueError:

            await interaction.response.send_message(
                "Winner count must be a number.",
                ephemeral=True,
            )

            return

        if not 1 <= winner_count <= MAX_WINNERS:

            await interaction.response.send_message(
                f"Winner count must be between 1 and {MAX_WINNERS}.",
                ephemeral=True,
            )

            return

        prize = (
            self.prize_input.value.strip()
        )

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


# ============================================================
# CONFIRMATION VIEW
# ============================================================

class GiveawayConfirmView(
    discord.ui.View
):

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

        if (
            interaction.user.id
            != self.author_id
        ):

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
    ):

        await interaction.response.edit_message(
            embed=discord.Embed(
                title=(
                    f"{EMOJI['loading']} Publishing Giveaway"
                ),
                description=(
                    "Generating cryptographic entropy...\n"
                    "Creating the SHA-256 commitment...\n"
                    "Building giveaway state..."
                ),
                color=discord.Color.blurple(),
            ),
            view=None,
        )

        await asyncio.sleep(
            FAKE_LOADING_SECONDS
        )

        try:

            state = (
                await self.cog.create_giveaway(
                    interaction=interaction,
                    duration_seconds=self.duration_seconds,
                    winner_count=self.winner_count,
                    prize=self.prize,
                    description=self.description,
                )
            )

        except Exception:

            log.exception(
                "Failed to create giveaway"
            )

            await interaction.edit_original_response(
                embed=discord.Embed(
                    title=(
                        f"{EMOJI['error']} Giveaway Creation Failed"
                    ),
                    description=(
                        "Something went wrong while creating the giveaway."
                    ),
                    color=discord.Color.red(),
                ),
                view=None,
            )

            return

        await interaction.edit_original_response(
            embed=discord.Embed(
                title=(
                    f"{EMOJI['approved']} Giveaway Published"
                ),
                description=(
                    f"Your giveaway is now live.\n\n"
                    f"**Giveaway ID:** `{state.giveaway_id}`\n"
                    f"**Randomizer:** `{state.randomizer_version}`\n"
                    f"**Commitment:** `{state.commitment}`"
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
    ):

        await interaction.response.edit_message(
            embed=discord.Embed(
                title=(
                    f"{EMOJI['denied']} Giveaway Cancelled"
                ),
                description=(
                    "No giveaway was created."
                ),
                color=discord.Color.red(),
            ),
            view=None,
        )

        self.stop()


# ============================================================
# COG
# ============================================================

class Giveaway(
    commands.Cog
):

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

        self.expiry_loop.start()

    def cog_unload(self):
        self.expiry_loop.cancel()

    # ========================================================
    # LOCK MANAGEMENT
    # ========================================================

    def get_lock(
        self,
        giveaway_id: str,
    ) -> asyncio.Lock:

        lock = self._locks.get(
            giveaway_id
        )

        if lock is None:

            lock = asyncio.Lock()

            self._locks[
                giveaway_id
            ] = lock

        return lock

    # ========================================================
    # RESTORE
    # ========================================================

    async def cog_load(self):

        await self.restore_active_giveaways()

    async def restore_active_giveaways(
        self,
    ):

        if self.bot.db is None:

            log.error(
                "bot.db is not initialized."
            )

            return

        try:

            result = (
                await self.bot.db.extensions.query(
                    """
                    SELECT entity_id, key, value
                    FROM extension_data
                    WHERE namespace = ?
                    """,
                    (
                        EXTENSION_NAMESPACE,
                    ),
                )
            )

        except Exception:

            log.exception(
                "Failed to restore giveaways."
            )

            return

        for row in result.all():

            if row.key != "state":
                continue

            try:

                payload = (
                    json.loads(row.value)
                    if isinstance(
                        row.value,
                        str,
                    )
                    else row.value
                )

                if not isinstance(
                    payload,
                    dict,
                ):
                    continue

                state = (
                    GiveawayState.from_dict(
                        payload
                    )
                )

            except Exception:

                log.exception(
                    "Failed to restore giveaway."
                )

                continue

            if state.deleted:
                continue

            self._active[
                state.giveaway_id
            ] = state

            if state.ended:
                continue

            self.bot.add_view(
                GiveawayEntryView(
                    self,
                    state.giveaway_id,
                ),
                message_id=(
                    int(state.message_id)
                    if state.message_id
                    else None
                ),
            )

            log.info(
                "Restored giveaway %s",
                state.giveaway_id,
            )

    # ========================================================
    # STORAGE
    # ========================================================

    async def save(
        self,
        state: GiveawayState,
    ):

        self._active[
            state.giveaway_id
        ] = state

        await self.bot.db.extensions.set(
            EXTENSION_NAMESPACE,
            state.giveaway_id,
            "state",
            state.to_dict(),
        )

    async def load(
        self,
        giveaway_id: str,
    ) -> Optional[GiveawayState]:

        cached = self._active.get(
            giveaway_id
        )

        if cached is not None:
            return cached

        payload = (
            await self.bot.db.extensions.get(
                EXTENSION_NAMESPACE,
                giveaway_id,
                "state",
            )
        )

        if not payload:
            return None

        if isinstance(
            payload,
            str,
        ):
            payload = json.loads(
                payload
            )

        if not isinstance(
            payload,
            dict,
        ):
            return None

        state = (
            GiveawayState.from_dict(
                payload
            )
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

        state = await self.load(
            identifier
        )

        if state is not None:
            return state

        if not identifier.isdigit():
            return None

        for cached_state in (
            self._active.values()
        ):

            if (
                cached_state.message_id
                == identifier
            ):
                return cached_state

        try:

            result = (
                await self.bot.db.extensions.query(
                    """
                    SELECT entity_id, key, value
                    FROM extension_data
                    WHERE namespace = ?
                    """,
                    (
                        EXTENSION_NAMESPACE,
                    ),
                )
            )

        except Exception:

            log.exception(
                "Failed to resolve giveaway."
            )

            return None

        for row in result.all():

            if row.key != "state":
                continue

            try:

                payload = (
                    json.loads(row.value)
                    if isinstance(
                        row.value,
                        str,
                    )
                    else row.value
                )

                if not isinstance(
                    payload,
                    dict,
                ):
                    continue

                if (
                    str(
                        payload.get(
                            "message_id"
                        )
                    )
                    != identifier
                ):
                    continue

                state = (
                    GiveawayState.from_dict(
                        payload
                    )
                )

                self._active[
                    state.giveaway_id
                ] = state

                return state

            except Exception:
                continue

        return None

    # ========================================================
    # CREATE
    # ========================================================

    async def create_giveaway(
        self,
        *,
        interaction: discord.Interaction,
        duration_seconds: int,
        winner_count: int,
        prize: str,
        description: str,
    ) -> GiveawayState:

        giveaway_id = str(
            uuid.uuid4()
        )

        ends_at = (
            utcnow()
            + timedelta(
                seconds=duration_seconds
            )
        )

        # Generate the seed before the giveaway is published.
        seed = (
            CryptographicRandomizer
            .generate_seed()
        )

        commitment = (
            CryptographicRandomizer
            .commitment(seed)
        )

        state = GiveawayState(
            giveaway_id=giveaway_id,
            guild_id=str(
                interaction.guild_id
            ),
            channel_id=str(
                interaction.channel_id
            ),
            message_id=None,
            host_id=str(
                interaction.user.id
            ),
            prize=prize,
            description=description,
            winner_count=winner_count,
            duration_seconds=duration_seconds,
            ends_at=ends_at.isoformat(),
            seed_hex=seed.hex(),
            commitment=commitment,
            randomizer_version=(
                CryptographicRandomizer.algorithm
            ),
        )

        # Persist the commitment before publishing.
        await self.save(
            state
        )

        channel = interaction.channel

        if channel is None:
            raise RuntimeError(
                "Unable to resolve giveaway channel."
            )

        message = await channel.send(
            embed=self.build_public_embed(
                state
            ),
            view=GiveawayEntryView(
                self,
                giveaway_id,
            ),
        )

        state.message_id = str(
            message.id
        )

        await self.save(
            state
        )

        return state

    # ========================================================
    # ENTRY
    # ========================================================

    async def handle_entry(
        self,
        interaction: discord.Interaction,
        giveaway_id: str,
    ):

        lock = self.get_lock(
            giveaway_id
        )

        async with lock:

            state = await self.load(
                giveaway_id
            )

            if (
                state is None
                or state.deleted
            ):

                await interaction.response.send_message(
                    f"{EMOJI['error']} This giveaway no longer exists.",
                    ephemeral=True,
                )

                return

            if state.ended:

                await interaction.response.send_message(
                    f"{EMOJI['denied']} This giveaway has already ended.",
                    ephemeral=True,
                )

                return

            if (
                datetime.fromisoformat(
                    state.ends_at
                )
                <= utcnow()
            ):

                await interaction.response.send_message(
                    f"{EMOJI['denied']} This giveaway has expired.",
                    ephemeral=True,
                )

                return

            user_id = str(
                interaction.user.id
            )

            state.participants = list(
                dict.fromkeys(
                    state.participants
                )
            )

            if user_id in state.participants:

                state.participants.remove(
                    user_id
                )

                await self.save(
                    state
                )

                await interaction.response.send_message(
                    f"{EMOJI['denied']} You have left the giveaway.",
                    ephemeral=True,
                )

                return

            state.participants.append(
                user_id
            )

            await self.save(
                state
            )

            await interaction.response.send_message(
                f"{EMOJI['approved']} You're entered!\n\n"
                f"**Prize:** {state.prize}\n"
                f"**Winners:** {state.winner_count}",
                ephemeral=True,
            )

    # ========================================================
    # EXPIRATION
    # ========================================================

    @tasks.loop(seconds=15)
    async def expiry_loop(
        self,
    ):

        now = utcnow()

        for giveaway_id, state in list(
            self._active.items()
        ):

            if (
                state.deleted
                or state.ended
            ):
                continue

            try:

                ends_at = (
                    datetime.fromisoformat(
                        state.ends_at
                    )
                )

            except ValueError:

                log.error(
                    "Invalid expiration for %s",
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
    ):

        await self.bot.wait_until_ready()

        while self.bot.db is None:
            await asyncio.sleep(1)

    # ========================================================
    # DRAW
    # ========================================================

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

        if winner_count > len(
            participants
        ):

            raise ValueError(
                "Not enough eligible participants."
            )

        return (
            CryptographicRandomizer.select(
                seed=bytes.fromhex(
                    state.seed_hex
                ),
                giveaway_id=state.giveaway_id,
                guild_id=state.guild_id,
                message_id=(
                    state.message_id or ""
                ),
                participants=participants,
                winner_count=winner_count,
                round_number=round_number,
            )
        )

    def record_result(
        self,
        state: GiveawayState,
        result: RandomSelection,
        *,
        eligible_participants: list[str],
        round_number: int,
    ):

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

    # ========================================================
    # END GIVEAWAY
    # ========================================================

    async def finish_giveaway(
        self,
        giveaway_id: str,
    ):

        lock = self.get_lock(
            giveaway_id
        )

        async with lock:

            state = await self.load(
                giveaway_id
            )

            if (
                state is None
                or state.deleted
                or state.ended
            ):
                return

            participants = sorted(
                {
                    str(user_id)
                    for user_id in state.participants
                    if str(user_id)
                }
            )

            state.ended = True

            if not participants:

                await self.save(
                    state
                )

                await self.announce_end(
                    state,
                    result=None,
                )

                return

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

            await self.save(
                state
            )

            await self.announce_end(
                state,
                result=result,
            )

    # ========================================================
    # DELETE
    # ========================================================

    async def delete_giveaway(
        self,
        state: GiveawayState,
    ):

        state.deleted = True
        state.ended = True

        await self.save(
            state
        )

        channel = self.bot.get_channel(
            int(state.channel_id)
        )

        if channel is None:
            return

        if not state.message_id:
            return

        try:

            message = (
                await channel.fetch_message(
                    int(state.message_id)
                )
            )

            await message.delete()

        except discord.NotFound:
            pass

        except discord.HTTPException:

            log.exception(
                "Failed to delete giveaway message."
            )

    # ========================================================
    # REROLL
    # ========================================================

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

        previous_winners: set[str] = set()

        for history in (
            state.draw_history
        ):

            previous_winners.update(
                str(user_id)
                for user_id in history.get(
                    "winners",
                    [],
                )
            )

        eligible = sorted(
            set(
                str(user_id)
                for user_id in state.participants
            )
            - previous_winners
        )

        if not eligible:

            raise ValueError(
                "No eligible participants remain."
            )

        if amount > len(
            eligible
        ):

            raise ValueError(
                f"Only {len(eligible)} eligible participant(s) remain."
            )

        next_round = (
            max(
                (
                    int(
                        entry.get(
                            "round_number",
                            1,
                        )
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

        await self.save(
            state
        )

        return result

    # ========================================================
    # EMBEDS
    # ========================================================

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
                f"{EMOJI['gift']} Giveaway Preview"
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

        return embed

    def build_public_embed(
        self,
        state: GiveawayState,
    ) -> discord.Embed:

        ends_at = datetime.fromisoformat(
            state.ends_at
        )

        embed = discord.Embed(
            title=(
                f"{EMOJI['gift']} {state.prize}"
            ),
            description=(
                f"{state.description}\n\n"
                f"{EMOJI['gift']} **Prize:** {state.prize}\n"
                f"{EMOJI['staff']} **Host:** <@{state.host_id}>\n"
                f"{EMOJI['yellowstar']} **Winners:** {state.winner_count}\n"
                f"{EMOJI['loading']} **Ends:** "
                f"<t:{int(ends_at.timestamp())}:R>\n\n"
                "**Enter below for your chance to win.**"
            ),
            color=discord.Color.blurple(),
        )

        embed.add_field(
            name="Randomness Commitment",
            value=(
                f"`{state.commitment}`"
            ),
            inline=False,
        )

        embed.add_field(
            name="Randomizer",
            value=(
                f"`{state.randomizer_version}`"
            ),
            inline=False,
        )

        embed.set_footer(
            text=(
                f"Giveaway ID: {state.giveaway_id}"
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
                f"{EMOJI['gift']} Giveaway Results"
            ),
            description=(
                f"Congratulations "
                f"{mention_users(list(result.winners))}!\n\n"
                f"**Prize:** {state.prize}"
            ),
            color=discord.Color.gold(),
        )

        embed.add_field(
            name="Winner Count",
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

        # The seed is intentionally revealed after the draw.
        if state.seed_hex:

            embed.add_field(
                name="Revealed Seed",
                value=f"`{state.seed_hex}`",
                inline=False,
            )

        embed.set_footer(
            text=(
                f"Giveaway ID: {state.giveaway_id} • "
                "Use /gverify to verify"
            )
        )

        return embed

    def build_reroll_embed(
        self,
        state: GiveawayState,
        result: RandomSelection,
    ) -> discord.Embed:

        return discord.Embed(
            title=(
                f"{EMOJI['gift']} Giveaway Reroll"
            ),
            description=(
                f"New winner(s): "
                f"{mention_users(list(result.winners))}\n\n"
                f"**Prize:** {state.prize}\n"
                f"**Round:** {state.round_number}\n\n"
                f"**Proof:** `{result.proof}`"
            ),
            color=discord.Color.orange(),
        )

    # ========================================================
    # ANNOUNCEMENT
    # ========================================================

    async def announce_end(
        self,
        state: GiveawayState,
        *,
        result: Optional[RandomSelection],
    ):

        channel = self.bot.get_channel(
            int(state.channel_id)
        )

        if channel is None:

            log.warning(
                "Could not resolve giveaway channel."
            )

            return

        if state.message_id:

            try:

                message = (
                    await channel.fetch_message(
                        int(state.message_id)
                    )
                )

                if result is not None:

                    embed = (
                        self.build_result_embed(
                            state,
                            result,
                        )
                    )

                    await message.edit(
                        embed=embed,
                        view=GiveawayEndedView(),
                    )

                else:

                    embed = discord.Embed(
                        title=(
                            f"{EMOJI['denied']} Giveaway Ended"
                        ),
                        description=(
                            f"**Prize:** {state.prize}\n\n"
                            "No one entered the giveaway."
                        ),
                        color=discord.Color.red(),
                    )

                    await message.edit(
                        embed=embed,
                        view=GiveawayEndedView(),
                    )

            except discord.NotFound:
                pass

            except discord.HTTPException:

                log.exception(
                    "Failed to update giveaway message."
                )

        if result is not None:

            await channel.send(
                embed=self.build_result_embed(
                    state,
                    result,
                )
            )

        else:

            await channel.send(
                embed=discord.Embed(
                    title=(
                        f"{EMOJI['denied']} Giveaway Ended"
                    ),
                    description=(
                        f"**Prize:** {state.prize}\n\n"
                        "No one entered this giveaway, "
                        "so no winners were drawn."
                    ),
                    color=discord.Color.red(),
                )
            )

    # ========================================================
    # GCREATE
    # ========================================================

    @app_commands.command(
        name="gcreate",
        description="Create a new cryptographically fair giveaway.",
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
    ):

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

    # ========================================================
    # GDELETE
    # ========================================================

    @app_commands.command(
        name="gdelete",
        description="Delete a giveaway using its ID or message ID.",
    )
    @app_commands.describe(
        giveaway="Giveaway ID or Discord message ID.",
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
    ):

        await interaction.response.defer(
            ephemeral=True
        )

        await asyncio.sleep(
            FAKE_LOADING_SECONDS
        )

        state = (
            await self.resolve_identifier(
                giveaway
            )
        )

        if (
            state is None
            or state.deleted
        ):

            await interaction.followup.send(
                f"{EMOJI['error']} No giveaway found.",
                ephemeral=True,
            )

            return

        await self.delete_giveaway(
            state
        )

        await interaction.followup.send(
            embed=discord.Embed(
                title=(
                    f"{EMOJI['approved']} Giveaway Deleted"
                ),
                description=(
                    f"**Prize:** {state.prize}\n"
                    f"**Giveaway ID:** `{state.giveaway_id}`"
                ),
                color=discord.Color.green(),
            ),
            ephemeral=True,
        )

    # ========================================================
    # GEND
    # ========================================================

    @app_commands.command(
        name="gend",
        description="End a giveaway immediately and draw its winners.",
    )
    @app_commands.describe(
        giveaway="Giveaway ID or Discord message ID.",
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
    ):

        await interaction.response.defer(
            ephemeral=True
        )

        await interaction.edit_original_response(
            embed=discord.Embed(
                title=(
                    f"{EMOJI['loading']} Finalizing Giveaway"
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

        state = (
            await self.resolve_identifier(
                giveaway
            )
        )

        if state is None:

            await interaction.followup.send(
                f"{EMOJI['error']} No giveaway found.",
                ephemeral=True,
            )

            return

        if state.ended:

            await interaction.followup.send(
                f"{EMOJI['denied']} That giveaway has already ended.",
                ephemeral=True,
            )

            return

        try:

            await self.finish_giveaway(
                state.giveaway_id
            )

        except Exception:

            log.exception(
                "Failed to end giveaway."
            )

            await interaction.followup.send(
                f"{EMOJI['error']} The giveaway could not be finalized.",
                ephemeral=True,
            )

            return

        await interaction.followup.send(
            embed=discord.Embed(
                title=(
                    f"{EMOJI['approved']} Giveaway Ended"
                ),
                description=(
                    f"**Prize:** {state.prize}\n"
                    f"**Giveaway ID:** `{state.giveaway_id}`\n\n"
                    "The winner selection has been published."
                ),
                color=discord.Color.green(),
            ),
            ephemeral=True,
        )

    # ========================================================
    # GREROLL
    # ========================================================

    @app_commands.command(
        name="greroll",
        description="Cryptographically reroll winners.",
    )
    @app_commands.describe(
        message_id="The giveaway Discord message ID.",
        amount="Number of new winners.",
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
                MAX_WINNERS,
            ]
        ] = None,
    ):

        await interaction.response.defer(
            ephemeral=True
        )

        state = (
            await self.resolve_identifier(
                message_id
            )
        )

        if state is None:

            await interaction.followup.send(
                f"{EMOJI['error']} No giveaway found for that message ID.",
                ephemeral=True,
            )

            return

        if not state.ended:

            await interaction.followup.send(
                f"{EMOJI['denied']} That giveaway has not ended yet.",
                ephemeral=True,
            )

            return

        requested_amount = (
            amount
            or state.winner_count
        )

        try:

            lock = self.get_lock(
                state.giveaway_id
            )

            async with lock:

                state = await self.load(
                    state.giveaway_id
                )

                if state is None:

                    raise ValueError(
                        "Giveaway no longer exists."
                    )

                result = (
                    await self.reroll_giveaway(
                        state,
                        requested_amount,
                    )
                )

        except ValueError as exc:

            await interaction.followup.send(
                f"{EMOJI['error']} {exc}",
                ephemeral=True,
            )

            return

        except Exception:

            log.exception(
                "Reroll failed."
            )

            await interaction.followup.send(
                f"{EMOJI['error']} The reroll failed.",
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
                )
            )

        await interaction.followup.send(
            embed=discord.Embed(
                title=(
                    f"{EMOJI['approved']} Reroll Complete"
                ),
                description=(
                    f"New winner(s): "
                    f"{mention_users(list(result.winners))}\n\n"
                    f"**Round:** {state.round_number}\n"
                    f"**Proof:** `{result.proof}`"
                ),
                color=discord.Color.green(),
            ),
            ephemeral=True,
        )

    # ========================================================
    # GVERIFY
    # ========================================================

    @app_commands.command(
        name="gverify",
        description="Verify a completed giveaway's cryptographic result.",
    )
    @app_commands.describe(
        giveaway="Giveaway ID or Discord message ID.",
    )
    async def gverify(
        self,
        interaction: discord.Interaction,
        giveaway: str,
    ):

        await interaction.response.defer(
            ephemeral=True
        )

        state = (
            await self.resolve_identifier(
                giveaway
            )
        )

        if (
            state is None
            or not state.ended
            or not state.last_result
            or not state.seed_hex
        ):

            await interaction.followup.send(
                f"{EMOJI['error']} No completed verifiable giveaway was found.",
                ephemeral=True,
            )

            return

        result = state.last_result

        try:

            valid = (
                CryptographicRandomizer.verify(
                    seed=bytes.fromhex(
                        state.seed_hex
                    ),
                    giveaway_id=state.giveaway_id,
                    guild_id=state.guild_id,
                    message_id=(
                        state.message_id
                        or ""
                    ),
                    participants=[
                        str(user_id)
                        for user_id in result.get(
                            "eligible_participants",
                            [],
                        )
                    ],
                    winner_count=int(
                        result[
                            "winner_count"
                        ]
                    ),
                    expected_winners=[
                        str(user_id)
                        for user_id in result.get(
                            "winners",
                            [],
                        )
                    ],
                    expected_commitment=str(
                        result[
                            "commitment"
                        ]
                    ),
                    expected_proof=str(
                        result[
                            "proof"
                        ]
                    ),
                    round_number=int(
                        result.get(
                            "round_number",
                            1,
                        )
                    ),
                )
            )

        except Exception:

            log.exception(
                "Verification failed."
            )

            await interaction.followup.send(
                f"{EMOJI['error']} Verification could not be completed.",
                ephemeral=True,
            )

            return

        if valid:

            embed = discord.Embed(
                title=(
                    f"{EMOJI['approved']} Draw Verified"
                ),
                description=(
                    "The stored participant set, seed, "
                    "algorithm, commitment, winners, "
                    "and proof all reproduce the recorded draw."
                ),
                color=discord.Color.green(),
            )

        else:

            embed = discord.Embed(
                title=(
                    f"{EMOJI['error']} Verification Failed"
                ),
                description=(
                    "The recorded draw does not match "
                    "its cryptographic verification data."
                ),
                color=discord.Color.red(),
            )

        embed.add_field(
            name="Algorithm",
            value=(
                f"`{result.get('algorithm', 'Unknown')}`"
            ),
            inline=False,
        )

        embed.add_field(
            name="Round",
            value=str(
                result.get(
                    "round_number",
                    1,
                )
            ),
            inline=True,
        )

        embed.add_field(
            name="Participants",
            value=str(
                result.get(
                    "participant_count",
                    0,
                )
            ),
            inline=True,
        )

        embed.add_field(
            name="Proof",
            value=(
                f"`{result.get('proof', 'Unavailable')}`"
            ),
            inline=False,
        )

        await interaction.followup.send(
            embed=embed,
            ephemeral=True,
        )


# ============================================================
# SETUP
# ============================================================

async def setup(
    bot: commands.Bot,
):
    await bot.add_cog(
        Giveaway(bot)
    )
