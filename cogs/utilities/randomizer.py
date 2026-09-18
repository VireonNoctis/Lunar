from __future__ import annotations

import hashlib
import hmac
import os
import struct
from dataclasses import dataclass
from typing import Iterable, Sequence

from discord.ext import commands


RANDOMIZER_VERSION = "LUNAR-CRYPTO-RANDOMIZER-v1"


@dataclass(frozen=True, slots=True)
class RandomSelection:
    winners: tuple[str, ...]
    commitment: str
    proof: str
    algorithm: str


class CryptographicRandomizer:
    """Cryptographically secure random-selection engine."""

    algorithm = RANDOMIZER_VERSION

    @staticmethod
    def generate_seed() -> bytes:
        return os.urandom(64)

    @staticmethod
    def commitment(seed: bytes) -> str:
        if not isinstance(seed, bytes):
            raise TypeError("seed must be bytes.")
        return hashlib.sha256(seed).hexdigest()

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
        normalized = sorted({
            str(user_id).strip()
            for user_id in participants
            if str(user_id).strip()
        })

        payload = "\n".join([
            RANDOMIZER_VERSION,
            f"giveaway_id={giveaway_id}",
            f"guild_id={guild_id}",
            f"message_id={message_id}",
            f"winner_count={winner_count}",
            f"round={round_number}",
            f"participant_count={len(normalized)}",
            *[
                f"participant={user_id}"
                for user_id in normalized
            ],
        ])

        return payload.encode("utf-8")

    @staticmethod
    def derive_key(
        seed: bytes,
        context: bytes,
    ) -> bytes:
        if not isinstance(seed, bytes):
            raise TypeError("seed must be bytes.")

        if not isinstance(context, bytes):
            raise TypeError("context must be bytes.")

        return hmac.new(
            seed,
            b"LUNAR-GIVEAWAY-RANDOMIZER|" + context,
            hashlib.sha512,
        ).digest()

    @staticmethod
    def _block(
        key: bytes,
        counter: int,
    ) -> bytes:
        if counter < 0:
            raise ValueError(
                "counter cannot be negative."
            )

        return hmac.new(
            key,
            b"RNG-BLOCK|" + struct.pack(
                ">Q",
                counter,
            ),
            hashlib.sha512,
        ).digest()

    @classmethod
    def _random_u64(
        cls,
        key: bytes,
        counter: int,
    ) -> tuple[int, int]:
        value = struct.unpack(
            ">Q",
            cls._block(
                key,
                counter,
            )[:8],
        )[0]

        return (
            value,
            counter + 1,
        )

    @classmethod
    def randbelow(
        cls,
        key: bytes,
        upper_bound: int,
        counter: int,
    ) -> tuple[int, int]:
        if upper_bound <= 0:
            raise ValueError(
                "upper_bound must be greater than zero."
            )

        limit = (
            (1 << 64)
            - ((1 << 64) % upper_bound)
        )

        while True:
            value, counter = cls._random_u64(
                key,
                counter,
            )

            if value < limit:
                return (
                    value % upper_bound,
                    counter,
                )

    @classmethod
    def select(
        cls,
        items: Sequence[str],
        winner_count: int,
        *,
        context: str = "LUNAR-SELECT",
        seed: bytes | None = None,
        giveaway_id: str | None = None,
        guild_id: str | None = None,
        message_id: str | None = None,
        round_number: int = 1,
    ) -> RandomSelection:
        """
        Select unique items without replacement.

        Supports simple command selections as well as
        deterministic giveaway selections.
        """

        normalized = sorted({
            str(item).strip()
            for item in items
            if str(item).strip()
        })

        if not normalized:
            raise ValueError(
                "Cannot select from an empty item set."
            )

        if winner_count <= 0:
            raise ValueError(
                "winner_count must be greater than zero."
            )

        if winner_count > len(normalized):
            raise ValueError(
                "winner_count cannot exceed item count."
            )

        if round_number <= 0:
            raise ValueError(
                "round_number must be greater than zero."
            )

        if seed is None:
            seed = cls.generate_seed()

        elif not isinstance(seed, bytes):
            raise TypeError(
                "seed must be bytes."
            )

        if (
            giveaway_id is not None
            or guild_id is not None
            or message_id is not None
        ):
            context_bytes = cls.canonicalize(
                giveaway_id=str(
                    giveaway_id or ""
                ),
                guild_id=str(
                    guild_id or ""
                ),
                message_id=str(
                    message_id or ""
                ),
                participants=normalized,
                winner_count=winner_count,
                round_number=round_number,
            )

        else:
            context_bytes = "\n".join([
                RANDOMIZER_VERSION,
                f"context={context}",
                f"winner_count={winner_count}",
                f"participant_count={len(normalized)}",
                *[
                    f"participant={item}"
                    for item in normalized
                ],
            ]).encode("utf-8")

        key = cls.derive_key(
            seed,
            context_bytes,
        )

        pool = list(normalized)
        winners: list[str] = []
        counter = 0

        for index in range(winner_count):
            offset, counter = cls.randbelow(
                key,
                len(pool) - index,
                counter,
            )

            selected_index = (
                index + offset
            )

            pool[index], pool[selected_index] = (
                pool[selected_index],
                pool[index],
            )

            winners.append(
                pool[index]
            )

        proof_payload = (
            cls.algorithm.encode("utf-8")
            + b"|"
            + seed
            + b"|"
            + context_bytes
            + b"|"
            + b"\n".join(
                item.encode("utf-8")
                for item in winners
            )
        )

        return RandomSelection(
            winners=tuple(winners),
            commitment=cls.commitment(seed),
            proof=hashlib.sha256(
                proof_payload
            ).hexdigest(),
            algorithm=cls.algorithm,
        )

    @classmethod
    def choose(
        cls,
        items: Sequence[str],
        *,
        seed: bytes | None = None,
        context: str = "LUNAR-CHOICE",
    ) -> tuple[str, str]:

        result = cls.select(
            items,
            1,
            seed=seed,
            context=context,
        )

        return (
            result.winners[0],
            result.proof,
        )

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

        if not hmac.compare_digest(
            cls.commitment(seed),
            expected_commitment,
        ):
            return False

        result = cls.select(
            participants,
            winner_count,
            seed=seed,
            giveaway_id=giveaway_id,
            guild_id=guild_id,
            message_id=message_id,
            round_number=round_number,
        )

        return (
            tuple(
                str(user_id)
                for user_id in expected_winners
            ) == result.winners
            and hmac.compare_digest(
                result.proof,
                expected_proof,
            )
        )

    @classmethod
    def coinflip(
        cls,
        *,
        seed: bytes | None = None,
    ) -> tuple[str, str]:

        if seed is None:
            seed = cls.generate_seed()

        key = cls.derive_key(
            seed,
            b"LUNAR-COINFLIP",
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
            cls.algorithm.encode("utf-8")
            + b"|"
            + seed
            + b"|"
            + result.encode("utf-8")
        ).hexdigest()

        return (
            result,
            proof,
        )


class Randomizer(commands.Cog):
    """Discord Cog wrapper for the randomizer utility."""

    def __init__(
        self,
        bot: commands.Bot,
    ):
        self.bot = bot
        self._ready_logged = False

    @commands.Cog.listener()
    async def on_ready(self):
        if not self._ready_logged:
            self._ready_logged = True

            print(
                f"[Randomizer] "
                f"{CryptographicRandomizer.algorithm} "
                f"loaded."
            )


async def setup(
    bot: commands.Bot,
) -> None:
    await bot.add_cog(
        Randomizer(bot)
    )from __future__ import annotations

import hashlib
import hmac
import os
import struct
from dataclasses import dataclass
from typing import Iterable, Sequence

from discord.ext import commands


RANDOMIZER_VERSION = "LUNAR-CRYPTO-RANDOMIZER-v1"


@dataclass(frozen=True, slots=True)
class RandomSelection:
    winners: tuple[str, ...]
    commitment: str
    proof: str
    algorithm: str


class CryptographicRandomizer:
    """Cryptographically secure random-selection engine."""

    algorithm = RANDOMIZER_VERSION

    @staticmethod
    def generate_seed() -> bytes:
        return os.urandom(64)

    @staticmethod
    def commitment(seed: bytes) -> str:
        if not isinstance(seed, bytes):
            raise TypeError("seed must be bytes.")
        return hashlib.sha256(seed).hexdigest()

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
        normalized = sorted({
            str(user_id).strip()
            for user_id in participants
            if str(user_id).strip()
        })

        payload = "\n".join([
            RANDOMIZER_VERSION,
            f"giveaway_id={giveaway_id}",
            f"guild_id={guild_id}",
            f"message_id={message_id}",
            f"winner_count={winner_count}",
            f"round={round_number}",
            f"participant_count={len(normalized)}",
            *[
                f"participant={user_id}"
                for user_id in normalized
            ],
        ])

        return payload.encode("utf-8")

    @staticmethod
    def derive_key(
        seed: bytes,
        context: bytes,
    ) -> bytes:
        if not isinstance(seed, bytes):
            raise TypeError("seed must be bytes.")

        if not isinstance(context, bytes):
            raise TypeError("context must be bytes.")

        return hmac.new(
            seed,
            b"LUNAR-GIVEAWAY-RANDOMIZER|" + context,
            hashlib.sha512,
        ).digest()

    @staticmethod
    def _block(
        key: bytes,
        counter: int,
    ) -> bytes:
        if counter < 0:
            raise ValueError(
                "counter cannot be negative."
            )

        return hmac.new(
            key,
            b"RNG-BLOCK|" + struct.pack(
                ">Q",
                counter,
            ),
            hashlib.sha512,
        ).digest()

    @classmethod
    def _random_u64(
        cls,
        key: bytes,
        counter: int,
    ) -> tuple[int, int]:
        value = struct.unpack(
            ">Q",
            cls._block(
                key,
                counter,
            )[:8],
        )[0]

        return (
            value,
            counter + 1,
        )

    @classmethod
    def randbelow(
        cls,
        key: bytes,
        upper_bound: int,
        counter: int,
    ) -> tuple[int, int]:
        if upper_bound <= 0:
            raise ValueError(
                "upper_bound must be greater than zero."
            )

        limit = (
            (1 << 64)
            - ((1 << 64) % upper_bound)
        )

        while True:
            value, counter = cls._random_u64(
                key,
                counter,
            )

            if value < limit:
                return (
                    value % upper_bound,
                    counter,
                )

    @classmethod
    def select(
        cls,
        items: Sequence[str],
        winner_count: int,
        *,
        context: str = "LUNAR-SELECT",
        seed: bytes | None = None,
        giveaway_id: str | None = None,
        guild_id: str | None = None,
        message_id: str | None = None,
        round_number: int = 1,
    ) -> RandomSelection:
        """
        Select unique items without replacement.

        Supports simple command selections as well as
        deterministic giveaway selections.
        """

        normalized = sorted({
            str(item).strip()
            for item in items
            if str(item).strip()
        })

        if not normalized:
            raise ValueError(
                "Cannot select from an empty item set."
            )

        if winner_count <= 0:
            raise ValueError(
                "winner_count must be greater than zero."
            )

        if winner_count > len(normalized):
            raise ValueError(
                "winner_count cannot exceed item count."
            )

        if round_number <= 0:
            raise ValueError(
                "round_number must be greater than zero."
            )

        if seed is None:
            seed = cls.generate_seed()

        elif not isinstance(seed, bytes):
            raise TypeError(
                "seed must be bytes."
            )

        if (
            giveaway_id is not None
            or guild_id is not None
            or message_id is not None
        ):
            context_bytes = cls.canonicalize(
                giveaway_id=str(
                    giveaway_id or ""
                ),
                guild_id=str(
                    guild_id or ""
                ),
                message_id=str(
                    message_id or ""
                ),
                participants=normalized,
                winner_count=winner_count,
                round_number=round_number,
            )

        else:
            context_bytes = "\n".join([
                RANDOMIZER_VERSION,
                f"context={context}",
                f"winner_count={winner_count}",
                f"participant_count={len(normalized)}",
                *[
                    f"participant={item}"
                    for item in normalized
                ],
            ]).encode("utf-8")

        key = cls.derive_key(
            seed,
            context_bytes,
        )

        pool = list(normalized)
        winners: list[str] = []
        counter = 0

        for index in range(winner_count):
            offset, counter = cls.randbelow(
                key,
                len(pool) - index,
                counter,
            )

            selected_index = (
                index + offset
            )

            pool[index], pool[selected_index] = (
                pool[selected_index],
                pool[index],
            )

            winners.append(
                pool[index]
            )

        proof_payload = (
            cls.algorithm.encode("utf-8")
            + b"|"
            + seed
            + b"|"
            + context_bytes
            + b"|"
            + b"\n".join(
                item.encode("utf-8")
                for item in winners
            )
        )

        return RandomSelection(
            winners=tuple(winners),
            commitment=cls.commitment(seed),
            proof=hashlib.sha256(
                proof_payload
            ).hexdigest(),
            algorithm=cls.algorithm,
        )

    @classmethod
    def choose(
        cls,
        items: Sequence[str],
        *,
        seed: bytes | None = None,
        context: str = "LUNAR-CHOICE",
    ) -> tuple[str, str]:

        result = cls.select(
            items,
            1,
            seed=seed,
            context=context,
        )

        return (
            result.winners[0],
            result.proof,
        )

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

        if not hmac.compare_digest(
            cls.commitment(seed),
            expected_commitment,
        ):
            return False

        result = cls.select(
            participants,
            winner_count,
            seed=seed,
            giveaway_id=giveaway_id,
            guild_id=guild_id,
            message_id=message_id,
            round_number=round_number,
        )

        return (
            tuple(
                str(user_id)
                for user_id in expected_winners
            ) == result.winners
            and hmac.compare_digest(
                result.proof,
                expected_proof,
            )
        )

    @classmethod
    def coinflip(
        cls,
        *,
        seed: bytes | None = None,
    ) -> tuple[str, str]:

        if seed is None:
            seed = cls.generate_seed()

        key = cls.derive_key(
            seed,
            b"LUNAR-COINFLIP",
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
            cls.algorithm.encode("utf-8")
            + b"|"
            + seed
            + b"|"
            + result.encode("utf-8")
        ).hexdigest()

        return (
            result,
            proof,
        )


class Randomizer(commands.Cog):
    """Discord Cog wrapper for the randomizer utility."""

    def __init__(
        self,
        bot: commands.Bot,
    ):
        self.bot = bot
        self._ready_logged = False

    @commands.Cog.listener()
    async def on_ready(self):
        if not self._ready_logged:
            self._ready_logged = True

            print(
                f"[Randomizer] "
                f"{CryptographicRandomizer.algorithm} "
                f"loaded."
            )


async def setup(
    bot: commands.Bot,
) -> None:
    await bot.add_cog(
        Randomizer(bot)
    )
