from __future__ import annotations

import hashlib
import hmac
import os
import struct

from dataclasses import dataclass
from typing import Iterable, Sequence

import discord

from discord.ext import commands


# ============================================================
# CONSTANTS
# ============================================================

RANDOMIZER_VERSION = (
    "LUNAR-CRYPTO-RANDOMIZER-v1"
)


# ============================================================
# RESULT
# ============================================================

@dataclass(
    frozen=True,
    slots=True,
)
class RandomSelection:
    winners: tuple[str, ...]
    commitment: str
    proof: str
    algorithm: str


# ============================================================
# CRYPTOGRAPHIC RANDOMIZER
# ============================================================

class CryptographicRandomizer:
    """
    Cryptographically secure random-selection engine.

    The randomizer itself is completely independent from
    giveaway storage and giveaway state.

    Pipeline:

        OS CSPRNG
            ↓
        512-bit seed
            ↓
        SHA-256 commitment
            ↓
        canonical selection context
            ↓
        HMAC-SHA-512
            ↓
        rejection sampling
            ↓
        partial Fisher-Yates
            ↓
        winners
            ↓
        cryptographic proof
    """

    algorithm = RANDOMIZER_VERSION

    # ========================================================
    # SEED
    # ========================================================

    @staticmethod
    def generate_seed() -> bytes:
        """
        Generate 512 bits of operating-system-backed
        cryptographically secure entropy.
        """

        return os.urandom(
            64
        )

    # ========================================================
    # COMMITMENT
    # ========================================================

    @staticmethod
    def commitment(
        seed: bytes,
    ) -> str:
        """
        SHA-256 commitment of the secret seed.
        """

        if not isinstance(
            seed,
            bytes,
        ):
            raise TypeError(
                "seed must be bytes"
            )

        return hashlib.sha256(
            seed
        ).hexdigest()

    # ========================================================
    # CANONICAL CONTEXT
    # ========================================================

    @staticmethod
    def canonicalize(
        *,
        giveaway_id: str,
        guild_id: str,
        message_id: str,
        participants: Iterable[str],
        winner_count: int,
        round_number: int = 1,
    ) -> bytes:
        """
        Canonically serialize the complete draw context.

        Participant ordering is normalized so unordered
        database/set ordering cannot change the result.
        """

        normalized_participants = sorted(
            {
                str(user_id).strip()
                for user_id in participants
                if str(user_id).strip()
            }
        )

        payload = "\n".join(
            [
                RANDOMIZER_VERSION,
                f"giveaway_id={giveaway_id}",
                f"guild_id={guild_id}",
                f"message_id={message_id}",
                f"winner_count={winner_count}",
                f"round={round_number}",
                f"participant_count={len(normalized_participants)}",
                *[
                    f"participant={user_id}"
                    for user_id in normalized_participants
                ],
            ]
        )

        return payload.encode(
            "utf-8"
        )

    # ========================================================
    # KEY DERIVATION
    # ========================================================

    @staticmethod
    def derive_key(
        seed: bytes,
        context: bytes,
    ) -> bytes:
        """
        Derive a domain-separated HMAC-SHA-512 key.
        """

        if not isinstance(
            seed,
            bytes,
        ):
            raise TypeError(
                "seed must be bytes"
            )

        if not isinstance(
            context,
            bytes,
        ):
            raise TypeError(
                "context must be bytes"
            )

        return hmac.new(
            seed,
            b"LUNAR-GIVEAWAY-RANDOMIZER|"
            + context,
            hashlib.sha512,
        ).digest()

    # ========================================================
    # RANDOM BLOCK
    # ========================================================

    @staticmethod
    def _block(
        key: bytes,
        counter: int,
    ) -> bytes:
        """
        Generate one deterministic 512-bit HMAC block.
        """

        if counter < 0:
            raise ValueError(
                "counter cannot be negative"
            )

        counter_bytes = struct.pack(
            ">Q",
            counter,
        )

        return hmac.new(
            key,
            b"RNG-BLOCK|"
            + counter_bytes,
            hashlib.sha512,
        ).digest()

    # ========================================================
    # UINT64
    # ========================================================

    @classmethod
    def _random_u64(
        cls,
        key: bytes,
        counter: int,
    ) -> tuple[int, int]:
        """
        Generate a deterministic unsigned 64-bit integer.
        """

        block = cls._block(
            key,
            counter,
        )

        value = struct.unpack(
            ">Q",
            block[:8],
        )[0]

        return (
            value,
            counter + 1,
        )

    # ========================================================
    # UNBIASED RANDOM INTEGER
    # ========================================================

    @classmethod
    def randbelow(
        cls,
        key: bytes,
        upper_bound: int,
        counter: int,
    ) -> tuple[int, int]:
        """
        Generate an unbiased integer:

            0 <= result < upper_bound

        Rejection sampling eliminates modulo bias.
        """

        if upper_bound <= 0:
            raise ValueError(
                "upper_bound must be greater than zero"
            )

        max_value = 1 << 64

        limit = (
            max_value
            - (
                max_value
                % upper_bound
            )
        )

        while True:

            value, counter = (
                cls._random_u64(
                    key,
                    counter,
                )
            )

            if value < limit:

                return (
                    value % upper_bound,
                    counter,
                )

    # ========================================================
    # WINNER SELECTION
    # ========================================================

    @classmethod
    def select(
        cls,
        *,
        seed: bytes,
        giveaway_id: str,
        guild_id: str,
        message_id: str,
        participants: Sequence[str],
        winner_count: int,
        round_number: int = 1,
    ) -> RandomSelection:
        """
        Select unique winners without replacement.
        """

        normalized = sorted(
            {
                str(user_id).strip()
                for user_id in participants
                if str(user_id).strip()
            }
        )

        if not normalized:
            raise ValueError(
                "Cannot select winners from an empty participant set."
            )

        if winner_count <= 0:
            raise ValueError(
                "winner_count must be greater than zero."
            )

        if winner_count > len(
            normalized
        ):
            raise ValueError(
                "winner_count cannot exceed participant count."
            )

        if round_number <= 0:
            raise ValueError(
                "round_number must be greater than zero."
            )

        context = cls.canonicalize(
            giveaway_id=giveaway_id,
            guild_id=guild_id,
            message_id=message_id,
            participants=normalized,
            winner_count=winner_count,
            round_number=round_number,
        )

        key = cls.derive_key(
            seed,
            context,
        )

        pool = list(
            normalized
        )

        counter = 0
    # ========================================================
    # SECURE CHOICE
    # ========================================================

    @classmethod
    def choose(
        cls,
        items: Sequence[str],
        *,
        seed: bytes | None = None,
        context: str = "LUNAR-CHOICE",
    ) -> tuple[str, str]:
        """
        Cryptographically secure selection of one item.

        Returns:

            (selected_item, proof)

        The selection uses the same HMAC-SHA-512 /
        rejection-sampling pipeline as the giveaway randomizer.
        """

        if not items:
            raise ValueError(
                "items cannot be empty."
            )

        if seed is None:
            seed = cls.generate_seed()

        normalized = [
            str(item).strip()
            for item in items
            if str(item).strip()
        ]

        if not normalized:
            raise ValueError(
                "items cannot contain only empty values."
            )

        context_bytes = (
            context.encode("utf-8")
            + b"|"
            + str(len(normalized)).encode("utf-8")
        )

        key = cls.derive_key(
            seed,
            context_bytes,
        )

        selected_index, _ = cls.randbelow(
            key,
            len(normalized),
            0,
        )

        selected = normalized[selected_index]

        proof = hashlib.sha256(
            cls.algorithm.encode("utf-8")
            + b"|"
            + seed
            + b"|"
            + context_bytes
            + b"|"
            + selected.encode("utf-8")
        ).hexdigest()

        return (
            selected,
            proof,
        )
        # ----------------------------------------------------
        # Partial Fisher-Yates
        # ----------------------------------------------------
        #
        # We only randomize enough positions to obtain the
        # requested number of winners.

        for index in range(
            len(pool) - 1,
            len(pool) - winner_count - 1,
            -1,
        ):

            swap_index, counter = (
                cls.randbelow(
                    key,
                    index + 1,
                    counter,
                )
            )

            pool[index], pool[
                swap_index
            ] = (
                pool[swap_index],
                pool[index],
            )

        winners = tuple(
            pool[
                len(pool) - winner_count:
            ]
        )

        # ----------------------------------------------------
        # Cryptographic proof
        # ----------------------------------------------------

        proof_payload = (
            RANDOMIZER_VERSION.encode(
                "utf-8"
            )
            + b"|"
            + seed
            + b"|"
            + context
            + b"|"
            + b",".join(
                user_id.encode(
                    "utf-8"
                )
                for user_id in winners
            )
        )

        proof = hashlib.sha256(
            proof_payload
        ).hexdigest()

        return RandomSelection(
            winners=winners,
            commitment=cls.commitment(
                seed
            ),
            proof=proof,
            algorithm=cls.algorithm,
        )

    # ========================================================
    # VERIFICATION
    # ========================================================

    @classmethod
    def verify(
        cls,
        *,
        seed: bytes,
        giveaway_id: str,
        guild_id: str,
        message_id: str,
        participants: Sequence[str],
        winner_count: int,
        expected_winners: Sequence[str],
        expected_commitment: str,
        expected_proof: str,
        round_number: int = 1,
    ) -> bool:
        """
        Reproduce and verify a previous draw.
        """

        actual_commitment = (
            cls.commitment(
                seed
            )
        )

        if not hmac.compare_digest(
            actual_commitment,
            expected_commitment,
        ):
            return False

        result = cls.select(
            seed=seed,
            giveaway_id=giveaway_id,
            guild_id=guild_id,
            message_id=message_id,
            participants=participants,
            winner_count=winner_count,
            round_number=round_number,
        )

        expected = tuple(
            str(user_id)
            for user_id in expected_winners
        )

        if expected != result.winners:
            return False

        return hmac.compare_digest(
            result.proof,
            expected_proof,
        )
    # ========================================================
    # COIN FLIP
    # ========================================================

    @classmethod
    def coinflip(
        cls,
        *,
        seed: bytes | None = None,
    ) -> tuple[str, str]:
        """
        Perform a cryptographically secure coin flip.

        Returns:

            (result, proof)

        Result is either:
            "heads"
            "tails"
        """

        if seed is None:
            seed = cls.generate_seed()

        context = (
            b"LUNAR-COINFLIP|"
            + seed
        )

        key = cls.derive_key(
            seed,
            context,
        )

        value, _ = cls._random_u64(
            key,
            0,
        )

        result = (
            "heads"
            if value & 1
            else "tails"
        )

        proof = hashlib.sha256(
            cls.algorithm.encode(
                "utf-8"
            )
            + b"|"
            + seed
            + b"|"
            + result.encode(
                "utf-8"
            )
        ).hexdigest()

        return (
            result,
            proof,
        )

# ============================================================
# RANDOMIZER COG
# ============================================================

class Randomizer(
    commands.Cog
):
    """
    Discord Cog wrapper for the randomizer utility.

    The giveaway cog imports CryptographicRandomizer directly.

    This Cog intentionally contains no giveaway state, database
    storage, expiration logic, or participant management.
    """

    def __init__(
        self,
        bot: commands.Bot,
    ):
        self.bot = bot

    # ========================================================
    # RANDOMIZER INFO
    # ========================================================

    @commands.Cog.listener()
    async def on_ready(
        self,
    ):
        """
        Log that the randomizer component is loaded.
        """

        if not getattr(
            self,
            "_ready_logged",
            False,
        ):

            self._ready_logged = True

            print(
                f"[Randomizer] "
                f"{CryptographicRandomizer.algorithm} "
                f"loaded."
            )


# ============================================================
# SETUP
# ============================================================

async def setup(
    bot: commands.Bot,
):
    await bot.add_cog(
        Randomizer(bot)
    )
