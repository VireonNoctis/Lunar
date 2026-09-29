from __future__ import annotations

import asyncio
import hashlib
import io
import logging
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from cogs.utilities.emoji import EMOJI


log = logging.getLogger("lunar.proof")


# ============================================================
# Configuration
# ============================================================
#
# WHAT THIS PROVES
#
#   Every source file the bot is running from is hashed with
#   SHA-256, and the hashes are folded into a Merkle tree. The
#   single 32-byte root commits to the exact bytes of every file
#   (and its path): change one character anywhere and the root
#   changes. A per-file inclusion proof lets anyone check one file
#   against the root without needing the others.
#
# WHAT THIS DOES NOT PROVE
#
#   The bot computes this about itself. A tampered bot could simply
#   print a different root, so the number on its own only proves
#   "these are the hashes I'm reporting". The proof becomes
#   meaningful when the root is recomputed INDEPENDENTLY from the
#   published zip/repo (see `/proof script`) and compared with the
#   root the maintainers published. Matching roots mean the
#   running code is byte-identical to that zip.
#
# Only source/docs are hashed (never .env, keys, logs, or data
# files), so the manifest is safe to publish.

PROJECT_ROOT = Path(__file__).resolve().parents[2]

INCLUDE_EXTENSIONS = (".py", ".md", ".txt")
INCLUDE_NAMES = (".env.example",)
EXCLUDE_DIRS = (
    ".git",
    ".idea",
    ".vscode",
    ".venv",
    "venv",
    "env",
    "node_modules",
    "__pycache__",
    "__MACOSX",
    "logs",
)

CACHE_SECONDS = 60
EMBED_COLOR = 0x5865F2

LEAF_PREFIX = b"\x00"
NODE_PREFIX = b"\x01"


# ============================================================
# Hashing / Merkle tree (stdlib only)
# ============================================================
#
# leaf = SHA256( 0x00 || path_utf8 || 0x00 || SHA256(file_bytes) )
# node = SHA256( 0x01 || left || right )
#
# The 0x00/0x01 prefixes domain-separate leaves from inner nodes,
# so an inner node can never be passed off as a leaf (the classic
# second-preimage trick). An unpaired node at the end of a level is
# promoted unchanged rather than duplicated.

@dataclass(frozen=True, slots=True)
class Entry:
    path: str
    size: int
    digest: bytes
    leaf: bytes


@dataclass(frozen=True, slots=True)
class Manifest:
    entries: tuple[Entry, ...]
    levels: tuple[tuple[bytes, ...], ...]
    total_bytes: int
    generated_at: datetime

    @property
    def root(self) -> bytes:
        return self.levels[-1][0]

    @property
    def root_hex(self) -> str:
        return self.root.hex()

    def index_of(self, path: str) -> Optional[int]:
        for index, entry in enumerate(self.entries):
            if entry.path == path:
                return index

        return None


def _sha256(data: bytes) -> bytes:
    return hashlib.sha256(data).digest()


def _file_digest(path: Path) -> tuple[bytes, int]:
    digest = hashlib.sha256()
    size = 0

    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)

            if not chunk:
                break

            digest.update(chunk)
            size += len(chunk)

    return digest.digest(), size


def leaf_hash(path: str, file_digest: bytes) -> bytes:
    return _sha256(
        LEAF_PREFIX
        + path.encode("utf-8")
        + b"\x00"
        + file_digest
    )


def node_hash(left: bytes, right: bytes) -> bytes:
    return _sha256(NODE_PREFIX + left + right)


def collect_files(root: Path) -> list[Path]:
    """Every file that belongs in the manifest, unsorted."""

    found: list[Path] = []

    for current, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]

        for name in files:
            if name.startswith("._"):
                continue

            path = Path(current) / name

            if path.is_symlink():
                continue

            if (
                name in INCLUDE_NAMES
                or path.suffix.lower() in INCLUDE_EXTENSIONS
            ):
                found.append(path)

    return found


def build_levels(
    leaves: list[bytes],
) -> tuple[tuple[bytes, ...], ...]:
    levels: list[tuple[bytes, ...]] = [tuple(leaves)]

    while len(levels[-1]) > 1:
        current = levels[-1]
        upper: list[bytes] = []

        for index in range(0, len(current), 2):
            if index + 1 < len(current):
                upper.append(
                    node_hash(current[index], current[index + 1])
                )
            else:
                upper.append(current[index])

        levels.append(tuple(upper))

    return tuple(levels)


def build_manifest(root: Path) -> Manifest:
    """Hash every included file under `root` (blocking I/O)."""

    entries: list[Entry] = []

    for path in collect_files(root):
        relative = path.relative_to(root).as_posix()
        digest, size = _file_digest(path)

        entries.append(
            Entry(
                path=relative,
                size=size,
                digest=digest,
                leaf=leaf_hash(relative, digest),
            )
        )

    if not entries:
        raise RuntimeError(f"No source files found under {root}")

    entries.sort(key=lambda entry: entry.path.encode("utf-8"))

    return Manifest(
        entries=tuple(entries),
        levels=build_levels([entry.leaf for entry in entries]),
        total_bytes=sum(entry.size for entry in entries),
        generated_at=datetime.now(timezone.utc),
    )


def inclusion_proof(
    manifest: Manifest,
    index: int,
) -> list[tuple[str, bytes]]:
    """
    Sibling hashes from leaf to root as (side, hash) steps, where
    `side` is where the sibling sits: "L" or "R".
    """

    proof: list[tuple[str, bytes]] = []

    for level in manifest.levels[:-1]:
        if index % 2 == 1:
            proof.append(("L", level[index - 1]))

        elif index + 1 < len(level):
            proof.append(("R", level[index + 1]))

        # else: unpaired, promoted unchanged — no step at this level.

        index //= 2

    return proof


def verify_inclusion(
    leaf: bytes,
    proof: list[tuple[str, bytes]],
    root: bytes,
) -> bool:
    current = leaf

    for side, sibling in proof:
        current = (
            node_hash(sibling, current)
            if side == "L"
            else node_hash(current, sibling)
        )

    return current == root


def render_manifest(manifest: Manifest) -> str:
    lines = [
        "# Lunar source manifest",
        f"# merkle_root_sha256={manifest.root_hex}",
        f"# files={len(manifest.entries)}",
        f"# total_bytes={manifest.total_bytes}",
        f"# generated={manifest.generated_at.isoformat()}",
        "# leaf = SHA256(0x00 || path || 0x00 || SHA256(file))",
        "# node = SHA256(0x01 || left || right)",
        "",
    ]

    lines.extend(
        f"{entry.digest.hex()}  {entry.path}"
        for entry in manifest.entries
    )

    return "\n".join(lines) + "\n"


# ============================================================
# Standalone verifier (sent as an attachment by /proof script)
# ============================================================
#
# Deliberately a separate, dependency-free implementation of the
# same algorithm so users can run it against the extracted zip
# without trusting (or even installing) the bot.

_VERIFY_SCRIPT_TEMPLATE = '''\
#!/usr/bin/env python3
"""
Recompute the Lunar source Merkle root from an extracted zip/checkout.

    python verify_proof.py <project_dir> [expected_root_hex]

Prints the file count and root. If expected_root_hex is given (for
example the root shown by the bot's /proof summary), exits 0 on a
match and 1 on a mismatch. Add --list to print every file hash.
"""
import hashlib
import os
import sys

INCLUDE_EXTENSIONS = __EXTENSIONS__
INCLUDE_NAMES = __NAMES__
EXCLUDE_DIRS = __DIRS__


def sha(data):
    return hashlib.sha256(data).digest()


def file_digest(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.digest()


def collect(root):
    entries = []
    for cur, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
        for name in files:
            full = os.path.join(cur, name)
            if name.startswith("._") or os.path.islink(full):
                continue
            if name in INCLUDE_NAMES or os.path.splitext(name)[1].lower() in INCLUDE_EXTENSIONS:
                rel = os.path.relpath(full, root).replace(os.sep, "/")
                entries.append((rel, file_digest(full)))
    entries.sort(key=lambda e: e[0].encode("utf-8"))
    return entries


def merkle_root(leaves):
    level = leaves
    while len(level) > 1:
        nxt = []
        for i in range(0, len(level), 2):
            if i + 1 < len(level):
                nxt.append(sha(b"\\x01" + level[i] + level[i + 1]))
            else:
                nxt.append(level[i])
        level = nxt
    return level[0]


def main():
    args = [a for a in sys.argv[1:] if a != "--list"]
    if not args:
        sys.exit(__doc__)
    entries = collect(args[0])
    if not entries:
        sys.exit("No source files found under " + args[0])
    if "--list" in sys.argv:
        for rel, digest in entries:
            print(digest.hex() + "  " + rel)
    leaves = [sha(b"\\x00" + rel.encode("utf-8") + b"\\x00" + d) for rel, d in entries]
    root = merkle_root(leaves).hex()
    print("files: " + str(len(entries)))
    print("root:  " + root)
    if len(args) > 1:
        ok = root == args[1].strip().lower()
        print("MATCH" if ok else "MISMATCH")
        sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
'''

VERIFY_SCRIPT = (
    _VERIFY_SCRIPT_TEMPLATE
    .replace("__EXTENSIONS__", repr(tuple(INCLUDE_EXTENSIONS)))
    .replace("__NAMES__", repr(tuple(INCLUDE_NAMES)))
    .replace("__DIRS__", repr(tuple(EXCLUDE_DIRS)))
)


# ============================================================
# Cog
# ============================================================

def _format_size(size: int) -> str:
    value = float(size)

    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return (
                f"{int(value)} {unit}"
                if unit == "B"
                else f"{value:.1f} {unit}"
            )

        value /= 1024

    return f"{size} B"


class Proof(commands.Cog):
    """
    /proof — a SHA-256 / Merkle-tree attestation of the bot's own
    source, verifiable against the published zip.
    """

    group = app_commands.Group(
        name="proof",
        description="Cryptographic proof of the bot's source code.",
    )

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

        self._manifest: Optional[Manifest] = None
        self._manifest_at: float = 0.0
        self._lock = asyncio.Lock()

    # --------------------------------------------------------
    # Manifest (cached, hashed off the event loop)
    # --------------------------------------------------------

    async def get_manifest(self, *, force: bool = False) -> Manifest:
        async with self._lock:
            fresh = (
                self._manifest is not None
                and (time.monotonic() - self._manifest_at)
                < CACHE_SECONDS
            )

            if force or not fresh:
                self._manifest = await asyncio.to_thread(
                    build_manifest, PROJECT_ROOT
                )
                self._manifest_at = time.monotonic()

            return self._manifest

    async def _fail(
        self,
        interaction: discord.Interaction,
        error: Exception,
        context: str,
    ) -> None:
        from cogs.utilities.error import log_error

        await log_error(
            error,
            context=context,
            bot=self.bot,
            guild=interaction.guild,
            user=interaction.user,
        )

        await interaction.followup.send(
            f"{EMOJI['error']} Couldn't generate the proof — "
            "the error has been logged.",
            ephemeral=True,
        )

    # --------------------------------------------------------
    # Autocomplete
    # --------------------------------------------------------

    async def path_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        try:
            manifest = await self.get_manifest()

        except Exception:
            return []

        current = current.strip().lower()

        return [
            app_commands.Choice(
                name=entry.path[-100:],
                value=entry.path,
            )
            for entry in manifest.entries
            if current in entry.path.lower()
        ][:25]

    # --------------------------------------------------------
    # /proof summary
    # --------------------------------------------------------

    @group.command(
        name="summary",
        description="Show the Merkle root committing to every source file.",
    )
    @app_commands.describe(
        public="Post the proof in the channel instead of only to you.",
        refresh="Re-hash the files now instead of using the cached result.",
    )
    async def summary(
        self,
        interaction: discord.Interaction,
        public: bool = False,
        refresh: bool = False,
    ) -> None:
        await interaction.response.defer(ephemeral=not public)

        try:
            manifest = await self.get_manifest(force=refresh)

        except Exception as error:
            await self._fail(interaction, error, "Proof Summary")
            return

        embed = discord.Embed(
            title=f"{EMOJI['security']} Cryptographic Proof of Source",
            description=(
                "A SHA-256 **Merkle tree** over every source file the "
                "bot is running from. The root below commits to the "
                "exact bytes and path of every file — change a single "
                "character anywhere and it changes completely."
            ),
            color=EMBED_COLOR,
        )

        embed.add_field(
            name="Merkle Root (SHA-256)",
            value=f"```{manifest.root_hex}```",
            inline=False,
        )
        embed.add_field(
            name="Files",
            value=f"`{len(manifest.entries)}`",
            inline=True,
        )
        embed.add_field(
            name="Total Size",
            value=f"`{_format_size(manifest.total_bytes)}`",
            inline=True,
        )
        embed.add_field(
            name="Computed",
            value=discord.utils.format_dt(
                manifest.generated_at, "R"
            ),
            inline=True,
        )
        embed.add_field(
            name=f"{EMOJI['verify']} Verify it yourself",
            value=(
                "1. `/proof script` — download `verify_proof.py`\n"
                "2. Extract the published zip and run:\n"
                "`python verify_proof.py <folder> <root>`\n"
                "3. `MATCH` means the running code is byte-identical "
                "to that zip.\n"
                "`/proof file` gives a single-file inclusion proof, "
                "`/proof manifest` the full hash list."
            ),
            inline=False,
        )
        embed.add_field(
            name="Limits",
            value=(
                "The bot computes this about itself, so on its own it "
                "only proves *consistency*. The check that counts is "
                "recomputing the root **independently** from the zip and "
                "comparing it with the root the maintainers published. "
                "Only source/docs are hashed — never `.env`, keys, logs "
                "or data."
            ),
            inline=False,
        )

        embed.set_footer(
            text=(
                f"☾ Lunar Proof • Python "
                f"{sys.version_info.major}.{sys.version_info.minor}"
                f".{sys.version_info.micro} • discord.py "
                f"{discord.__version__}"
            )
        )

        await interaction.followup.send(embed=embed)

    # --------------------------------------------------------
    # /proof file
    # --------------------------------------------------------

    @group.command(
        name="file",
        description="Prove one file is part of the committed source tree.",
    )
    @app_commands.describe(path="Path of the file, e.g. bot.py")
    @app_commands.autocomplete(path=path_autocomplete)
    async def file(
        self,
        interaction: discord.Interaction,
        path: str,
    ) -> None:
        await interaction.response.defer(ephemeral=True)

        try:
            manifest = await self.get_manifest()

        except Exception as error:
            await self._fail(interaction, error, "Proof File")
            return

        index = manifest.index_of(path.strip().replace("\\", "/"))

        if index is None:
            await interaction.followup.send(
                f"{EMOJI['error']} `{path}` isn't part of the "
                "manifest. Start typing to autocomplete a real path.",
                ephemeral=True,
            )
            return

        entry = manifest.entries[index]
        proof = inclusion_proof(manifest, index)

        if not verify_inclusion(entry.leaf, proof, manifest.root):
            # Should be impossible; if it ever fires the tree
            # construction itself is broken, which is worth a log.
            log.error("Inclusion proof self-check failed for %s", path)

        steps = "\n".join(
            f"{side} {sibling.hex()}" for side, sibling in proof
        ) or "(single-file tree — the leaf is the root)"

        embed = discord.Embed(
            title=f"{EMOJI['security']} Inclusion Proof",
            description=f"`{entry.path}` • `{_format_size(entry.size)}`",
            color=EMBED_COLOR,
        )

        embed.add_field(
            name="File SHA-256",
            value=f"```{entry.digest.hex()}```",
            inline=False,
        )
        embed.add_field(
            name="Leaf",
            value=f"```{entry.leaf.hex()}```",
            inline=False,
        )
        embed.add_field(
            name=f"Proof path ({len(proof)} steps, leaf → root)",
            value=f"```{steps}```"[:1024],
            inline=False,
        )
        embed.add_field(
            name="Merkle Root",
            value=f"```{manifest.root_hex}```",
            inline=False,
        )
        embed.add_field(
            name=f"{EMOJI['verify']} How to check",
            value=(
                "`leaf = SHA256(0x00 ‖ path ‖ 0x00 ‖ file_sha256)`\n"
                "Start with the leaf. For each step: `L` → "
                "`SHA256(0x01 ‖ sibling ‖ h)`, `R` → "
                "`SHA256(0x01 ‖ h ‖ sibling)`. The result must equal "
                "the root. (`‖` = byte concatenation, hashes are raw "
                "bytes — not the hex text.)"
            ),
            inline=False,
        )

        embed.set_footer(text="☾ Lunar Proof")

        await interaction.followup.send(embed=embed, ephemeral=True)

    # --------------------------------------------------------
    # /proof manifest
    # --------------------------------------------------------

    @group.command(
        name="manifest",
        description="Download the full SHA-256 manifest of the source.",
    )
    async def manifest(
        self,
        interaction: discord.Interaction,
    ) -> None:
        await interaction.response.defer(ephemeral=True)

        try:
            manifest = await self.get_manifest()

        except Exception as error:
            await self._fail(interaction, error, "Proof Manifest")
            return

        payload = render_manifest(manifest).encode("utf-8")

        await interaction.followup.send(
            content=(
                f"{EMOJI['security']} **{len(manifest.entries)} files** "
                f"• root `{manifest.root_hex[:16]}…`\n"
                "Lines after the header are in `sha256sum` format."
            ),
            file=discord.File(
                io.BytesIO(payload),
                filename="manifest.sha256",
            ),
            ephemeral=True,
        )

    # --------------------------------------------------------
    # /proof script
    # --------------------------------------------------------

    @group.command(
        name="script",
        description="Download a standalone script that recomputes the root from the zip.",
    )
    async def script(
        self,
        interaction: discord.Interaction,
    ) -> None:
        await interaction.response.send_message(
            content=(
                f"{EMOJI['verify']} Extract the published zip, then run:\n"
                "```python verify_proof.py <folder> <root>```"
                "Use the root from `/proof summary`. It has no "
                "dependencies beyond Python 3, and it's short enough to "
                "read before you run it."
            ),
            file=discord.File(
                io.BytesIO(VERIFY_SCRIPT.encode("utf-8")),
                filename="verify_proof.py",
            ),
            ephemeral=True,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Proof(bot))
