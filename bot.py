import asyncio
import importlib
import logging
import os
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands, tasks

# ============================================================
# CONFIG
# ============================================================

TOKEN = "YOUR_BOT_TOKEN"
COGS_DIR = Path("./cogs")
SCAN_INTERVAL = 1.0

# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

logger = logging.getLogger("LunarBot")

# ============================================================
# BOT
# ============================================================

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(
    command_prefix="!",
    intents=intents,
    status=discord.Status.idle,
)

# Track currently loaded cog modules and their modification times.
loaded_cogs: dict[str, float] = {}


# ============================================================
# COG DISCOVERY
# ============================================================

def discover_cogs() -> dict[str, tuple[Path, float]]:
    """
    Finds every Python file inside ./cogs/.

    Returns:
        {
            "cogs.example": (Path("cogs/example.py"), modified_time),
            ...
        }
    """
    discovered = {}

    if not COGS_DIR.exists():
        COGS_DIR.mkdir(parents=True, exist_ok=True)

    for file in COGS_DIR.rglob("*.py"):
        if file.name.startswith("_"):
            continue

        # Convert:
        # cogs/example.py
        # into:
        # cogs.example
        relative = file.relative_to(Path("."))
        module = str(relative.with_suffix("")).replace(os.sep, ".")

        discovered[module] = (file, file.stat().st_mtime)

    return discovered


# ============================================================
# COG LOADING
# ============================================================

async def load_cog(module: str):
    """Load a cog safely."""
    try:
        await bot.load_extension(module)

        logger.info("Loaded cog: %s", module)

    except commands.ExtensionAlreadyLoaded:
        logger.debug("Cog already loaded: %s", module)

    except Exception:
        logger.exception("Failed to load cog: %s", module)


async def reload_cog(module: str):
    """Reload a cog safely."""
    try:
        await bot.reload_extension(module)

        logger.info("Reloaded cog: %s", module)

    except commands.ExtensionNotLoaded:
        logger.warning(
            "Cog %s was not loaded, attempting to load it.",
            module,
        )
        await load_cog(module)

    except Exception:
        logger.exception("Failed to reload cog: %s", module)


async def unload_cog(module: str):
    """Unload a cog safely."""
    try:
        await bot.unload_extension(module)

        logger.info("Unloaded cog: %s", module)

    except commands.ExtensionNotLoaded:
        pass

    except Exception:
        logger.exception("Failed to unload cog: %s", module)


# ============================================================
# COG WATCHER
# ============================================================

@tasks.loop(seconds=SCAN_INTERVAL)
async def cog_watcher():
    """
    Watches ./cogs/ continuously.

    New files:
        Load automatically.

    Modified files:
        Reload automatically.

    Deleted files:
        Unload automatically.
    """

    try:
        discovered = discover_cogs()

        # --------------------------------------------------------
        # NEW / MODIFIED COGS
        # --------------------------------------------------------

        for module, (_, modified_time) in discovered.items():

            # New cog
            if module not in loaded_cogs:
                await load_cog(module)
                loaded_cogs[module] = modified_time
                continue

            # Existing cog changed
            old_modified_time = loaded_cogs[module]

            if modified_time != old_modified_time:
                await reload_cog(module)
                loaded_cogs[module] = modified_time

        # --------------------------------------------------------
        # DELETED COGS
        # --------------------------------------------------------

        deleted = set(loaded_cogs) - set(discovered)

        for module in deleted:
            await unload_cog(module)
            loaded_cogs.pop(module, None)

    except Exception:
        logger.exception("Error while watching cogs.")


@cog_watcher.before_loop
async def before_cog_watcher():
    await bot.wait_until_ready()


# ============================================================
# SLASH COMMANDS
# ============================================================

@bot.tree.command(
    name="ping",
    description="Check the bot's latency.",
)
async def ping(interaction: discord.Interaction):
    latency = round(bot.latency * 1000)

    await interaction.response.send_message(
        f"🏓 Pong! `{latency}ms`"
    )


# ============================================================
# EVENTS
# ============================================================

@bot.event
async def on_ready():
    logger.info(
        "Logged in as %s (%s)",
        bot.user,
        bot.user.id,
    )

    # Keep the bot Idle.
    await bot.change_presence(
        status=discord.Status.idle,
        activity=None,
    )

    # Sync slash commands.
    try:
        synced = await bot.tree.sync()

        logger.info(
            "Synced %d slash command(s).",
            len(synced),
        )

    except Exception:
        logger.exception("Failed to sync slash commands.")

    # Start watcher once.
    if not cog_watcher.is_running():
        cog_watcher.start()


# ============================================================
# STARTUP
# ============================================================

async def main():
    COGS_DIR.mkdir(parents=True, exist_ok=True)

    async with bot:
        await bot.start(TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
