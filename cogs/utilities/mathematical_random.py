from __future__ import annotations

import hashlib
import hmac
import secrets
import struct
from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True, slots=True)
class RandomProof:
    winners: tuple[str, ...]
    commitment: str
    context_hash: str
    proof: str
    algorithm: str


class MathematicalRandomness:
    """
    Cryptographically secure, bias-free, independently verifiable randomness.

    Entropy source:
        secrets.token_bytes() -> operating-system CSPRNG

    Mathematical sampling:
        u = int(HMAC-SHA512(K, counter), 16)
        L = 2^512 - (2^512 mod n)
        accept u only when u < L
        result = u mod n

    Rejection sampling makes every result in [0, n) exactly uniform,
    avoiding modulo bias.

    The proof verifies that the revealed seed, context and participants
    reproduce the published result. It does not mathematically prove
    that the operating-system entropy source was physically random.
    """

    VERSION = "LUNAR-MATH-RNG-v1"
    BLOCK_BITS = 512
    BLOCK_SIZE = BLOCK_BITS // 8

    @classmethod
    def entropy(cls) -> bytes:
        return secrets.token_bytes(64)

    @classmethod
    def commit(cls, seed: bytes) -> str:
        if not isinstance(seed, bytes) or len(seed) < 32:
            raise ValueError("seed must contain at least 32 random bytes.")

        return hashlib.sha512(
            b"LUNAR-COMMIT|" + seed
        ).hexdigest()

    @staticmethod
    def _normalize(items: Sequence[str]) -> tuple[str, ...]:
        values = tuple(
            sorted({
                str(x).strip()
                for x in items
                if str(x).strip()
            })
        )

        if not values:
            raise ValueError("items cannot be empty.")

        return values

    @classmethod
    def _context(
        cls,
        items: Sequence[str],
        winner_count: int,
        context: str,
    ) -> bytes:
        values = cls._normalize(items)

        if winner_count < 1 or winner_count > len(values):
            raise ValueError(
                "winner_count must be between 1 and item count."
            )

        payload = "\n".join((
            cls.VERSION,
            f"context={context}",
            f"count={len(values)}",
            f"winners={winner_count}",
            *values,
        ))

        return payload.encode("utf-8")

    @classmethod
    def _key(
        cls,
        seed: bytes,
        context: bytes,
    ) -> bytes:
        return hmac.new(
            seed,
            b"LUNAR-DERIVE|" +
            hashlib.sha512(context).digest(),
            hashlib.sha512,
        ).digest()

    @classmethod
    def _block(
        cls,
        key: bytes,
        counter: int,
    ) -> int:
        raw = hmac.new(
            key,
            b"LUNAR-BLOCK|" +
            struct.pack(">Q", counter),
            hashlib.sha512,
        ).digest()

        return int.from_bytes(
            raw,
            "big",
        )

    @classmethod
    def _randbelow(
        cls,
        key: bytes,
        n: int,
        counter: int,
    ) -> tuple[int, int]:
        if n <= 0:
            raise ValueError(
                "n must be greater than zero."
            )

        space = 1 << cls.BLOCK_BITS
        limit = space - (space % n)

        while True:
            value = cls._block(
                key,
                counter,
            )

            counter += 1

            if value < limit:
                return (
                    value % n,
                    counter,
                )

    @classmethod
    def select(
        cls,
        items: Sequence[str],
        winner_count: int,
        *,
        context: str = "LUNAR",
        seed: bytes | None = None,
    ) -> RandomProof:
        values = cls._normalize(items)
        context_bytes = cls._context(
            values,
            winner_count,
            context,
        )

        seed = (
            cls.entropy()
            if seed is None
            else seed
        )

        if not isinstance(seed, bytes) or len(seed) < 32:
            raise ValueError(
                "seed must contain at least 32 random bytes."
            )

        key = cls._key(
            seed,
            context_bytes,
        )

        pool = list(values)
        winners: list[str] = []
        counter = 0

        # Fisher-Yates-style sampling without replacement.
        for i in range(winner_count):
            offset, counter = cls._randbelow(
                key,
                len(pool) - i,
                counter,
            )

            j = i + offset

            pool[i], pool[j] = (
                pool[j],
                pool[i],
            )

            winners.append(
                pool[i]
            )

        commitment = cls.commit(seed)

        context_hash = hashlib.sha512(
            context_bytes
        ).hexdigest()

        transcript = b"|".join((
            cls.VERSION.encode(),
            commitment.encode(),
            context_hash.encode(),
            b"\n".join(
                x.encode()
                for x in winners
            ),
        ))

        proof = hashlib.sha512(
            b"LUNAR-PROOF|" +
            transcript
        ).hexdigest()

        return RandomProof(
            winners=tuple(winners),
            commitment=commitment,
            context_hash=context_hash,
            proof=proof,
            algorithm=cls.VERSION,
        )

    @classmethod
    def verify(
        cls,
        items: Sequence[str],
        winner_count: int,
        *,
        context: str,
        seed: bytes,
        expected_winners: Sequence[str],
        commitment: str,
        context_hash: str,
        proof: str,
    ) -> bool:
        if not hmac.compare_digest(
            cls.commit(seed),
            commitment,
        ):
            return False

        result = cls.select(
            items,
            winner_count,
            context=context,
            seed=seed,
        )

        return (
            result.winners
            == tuple(
                str(x)
                for x in expected_winners
            )
            and hmac.compare_digest(
                result.context_hash,
                context_hash,
            )
            and hmac.compare_digest(
                result.proof,
                proof,
            )
        )
