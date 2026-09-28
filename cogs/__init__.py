from __future__ import annotations
from typing import Final


# ============================================================
# PACKAGE METADATA
# ============================================================

NAME: Final[str] = "Lunar"
VERSION: Final[str] = "3.0"
AUTHOR: Final[str] = "Vireon"
DESCRIPTION: Final[str] = (
    "Lunar Discord Bot — modular commands, integrations "
    "and utility systems."
)


# ============================================================
# COG PACKAGE NAMESPACES
# ============================================================

COMMANDS_PACKAGE: Final[str] = "cogs.commands"
INTEGRATIONS_PACKAGE: Final[str] = "cogs.integrations"
UTILITIES_PACKAGE: Final[str] = "cogs.utilities"


# ============================================================
# COMMAND EXTENSIONS
# ============================================================
#
# NOTE: bot.py loads cogs by auto-discovering every *.py file
# under cogs/ (excluding cogs/utilities/) at startup — see
# discover_cogs() in bot.py. These tuples are NOT read by that
# loader; they exist as a human-readable registry of what's on
# disk. Keep them in sync with the actual files so they stay
# useful as documentation/tooling metadata.

COMMAND_MODULES: Final[tuple[str, ...]] = (
    "about",
    "akinator",
    "anime",
    "channel",
    "close",
    "coinflip",
    "dadjoke",
    "fun",
    "gacha",
    "giveaway",
    "help",
    "inbox",
    "interactions",
    "leaderboard",
    "level",
    "linkaccount",
    "randommeme",
    "restart",
    "search",
    "steal",
    "system",
    "tmusic",
)


# ============================================================
# INTEGRATION EXTENSIONS
# ============================================================

INTEGRATION_MODULES: Final[tuple[str, ...]] = (
    "coins",
    "collectionreply",
    "counting",
    "gacha-int",
    "github",
    "guild_xp",
    "staffguide",
    "xp",
)


# ============================================================
# NON-EXTENSION UTILITIES
# ============================================================


UTILITY_MODULES: Final[tuple[str, ...]] = (
    "api",
    "database",
    "emoji",
    "error",
    "generatecode",
    "info",
    "level_card",
    "mathematical_random",
    "randomizer",
    "xp",
    "xp_announcment",
)


# ============================================================
# FULL EXTENSION REGISTRY
# ============================================================

EXTENSION_MODULES: Final[tuple[str, ...]] = tuple(
    f"{COMMANDS_PACKAGE}.{module}"
    for module in COMMAND_MODULES
) + tuple(
    f"{INTEGRATIONS_PACKAGE}.{module}"
    for module in INTEGRATION_MODULES
)


# ============================================================
# PACKAGE HELPERS
# ============================================================

def command_extensions() -> tuple[str, ...]:
 
    return tuple(
        f"{COMMANDS_PACKAGE}.{module}"
        for module in COMMAND_MODULES
    )


def integration_extensions() -> tuple[str, ...]:

    return tuple(
        f"{INTEGRATIONS_PACKAGE}.{module}"
        for module in INTEGRATION_MODULES
    )


def extension_modules() -> tuple[str, ...]:
 
    return EXTENSION_MODULES


def is_extension(module: str) -> bool:
    """
    Return True when a module belongs to Lunar's extension set.

    Parameters
    ----------
    module:
        Fully-qualified Python module path.

    Examples
    --------
    ``is_extension("cogs.commands.about")``
        True

    ``is_extension("cogs.utilities.database")``
        False
    """
    return module in EXTENSION_MODULES


def is_command(module: str) -> bool:

    return module.startswith(
        f"{COMMANDS_PACKAGE}."
    )


def is_integration(module: str) -> bool:
 
    return module.startswith(
        f"{INTEGRATIONS_PACKAGE}."
    )


def is_utility(module: str) -> bool:
 
    return module.startswith(
        f"{UTILITIES_PACKAGE}."
    )


# ============================================================
# PUBLIC EXPORTS
# ============================================================

__all__ = (
    "NAME",
    "VERSION",
    "AUTHOR",
    "DESCRIPTION",
    "COMMANDS_PACKAGE",
    "INTEGRATIONS_PACKAGE",
    "UTILITIES_PACKAGE",
    "COMMAND_MODULES",
    "INTEGRATION_MODULES",
    "UTILITY_MODULES",
    "EXTENSION_MODULES",
    "command_extensions",
    "integration_extensions",
    "extension_modules",
    "is_extension",
    "is_command",
    "is_integration",
    "is_utility",
)
