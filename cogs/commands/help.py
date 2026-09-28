from __future__ import annotations

import logging
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

from cogs.utilities.emoji import EMOJI


log = logging.getLogger("lunar.help")

# Custom Lunar emoji aliases.
E = EMOJI
MOON = E["moon"]
ECONOMY = E["yellowstar"]
GACHA = E["cards"]
GIVEAWAY = E["crown"]
ACCOUNT = E["verify"]
FUN = E["aniheart"]
MUSIC = E["spotify"]
ANIME = E["lunar"]
UTILITY = E["commands"]
STAFF = E["staff"]
XP = E["yellowstar"]
DONATOR = E["Donator"]
BOOSTER = E["approved"]


# ============================================================
# Content
# ============================================================
#
# Each page is one dropdown option. `description` is full
# markdown, rendered straight into the embed description
# (4096-char budget) — keep individual pages under that.

HELP_PAGES: dict[str, dict[str, Any]] = {

    "overview": {
        "label": "Overview",
        "emoji": MOON,
        "short": "What Lunar is and how this menu works.",
        "description": (
            f"## {MOON} Welcome to Lunar\n"
            "Lunar is the Discord companion to **lunarx.to** — "
            "an anime/manga platform with its own leveling, coin "
            "economy, and gacha card game. This bot links your "
            "Discord account to your Lunar account and lets you "
            "interact with all of that from here.\n\n"
            "**Use the dropdown below** to browse commands by "
            f"category, or jump straight to **{XP} XP & Coins "
            f"System** / **{GACHA} Gacha System** for a full breakdown "
            "of how earning and rewards actually work under the "
            "hood.\n\n"
            "### Quick Start\n"
            "1. Run `/link` to connect your Discord account to "
            "your Lunar account.\n"
            "2. Chat normally — you'll passively earn **XP** and "
            "**coins** on both Discord and the website.\n"
            "3. Check `/level` and `/leaderboard` to track "
            "progress.\n"
            "4. Use `/gacha list` to browse cards, and `/gacha "
            "owners <card>` to see who owns what.\n\n"
            "-# Every command below is a slash command — type `/` "
            "in any channel the bot can see and Discord will "
            "autocomplete it for you."
        ),
    },

    "economy": {
        "label": "Economy & Leveling",
        "emoji": ECONOMY,
        "short": "/level, /leaderboard, /coinflip",
        "description": (
            f"## {ECONOMY} Economy & Leveling Commands\n\n"
            "**`/level`** `[type]`\n"
            "Shows your current level card. `type` picks which "
            "leveling system to display:\n"
            "- **Guild XP** — this server's own Discord-only "
            "leveling\n"
            "- **Lunar XP** — your website level (source of "
            "truth lives on lunarx.to)\n"
            "- **Both** — side-by-side comparison\n\n"
            "**`/leaderboard`** `[type]`\n"
            "Server or website XP rankings. Website rankings are "
            "cached briefly to avoid hammering the Lunar API on "
            "every use.\n\n"
            "**`/leaderboard_sync`** *(staff)*\n"
            "Forces an immediate refresh of the cached Lunar "
            "leaderboard instead of waiting for the next natural "
            "refresh.\n\n"
            "**`/coinflip`** `[bet]`\n"
            "A provably-fair coinflip using the bot's "
            "cryptographic randomizer — the result embed includes "
            "the commitment/proof so you can verify it wasn't "
            "rigged after the fact.\n\n"
            f"-# See **{XP} XP & Coins System** for exactly how "
            "much you earn and how often."
        ),
    },

    "gacha": {
        "label": "Gacha",
        "emoji": GACHA,
        "short": "/gacha card, owners, list",
        "description": (
            f"## {GACHA} Gacha Commands\n\n"
            "**`/gacha card`** `template`\n"
            "Look up one card's full stats (ATK/DEF/HP + growth "
            "per level), class, max level, copy limit, and skill "
            "descriptions. `template` autocompletes as you type "
            "the card's name.\n\n"
            "**`/gacha owners`** `template`\n"
            "Shows every minted copy of a card — mint number and "
            "current owner, plus how many are listed vs. total "
            "minted vs. the max copy limit. Paginated with "
            "Previous/Next buttons for cards with a lot of "
            "copies.\n\n"
            "**`/gacha list`** `[rarity]`\n"
            "Browse the full card catalog, sorted highest rarity "
            "first. Pass `rarity` (1-6+) to filter to just that "
            "tier.\n\n"
            f"-# See **{GACHA} Gacha System** for how rarity, mint "
            "numbers, and copy limits work."
        ),
    },

    "giveaways": {
        "label": "Giveaways",
        "emoji": GIVEAWAY,
        "short": "/gcreate, gend, greroll, gverify...",
        "description": (
            f"## {GIVEAWAY} Giveaway Commands *(staff — Manage Server)*\n\n"
            "**`/gcreate`**\n"
            "Opens a modal to set the prize, duration, and winner "
            "count. Entrants must have a **linked, verified** "
            "Lunar account to enter.\n\n"
            "**Configure Rewards**\n"
            "During `/gcreate`, use the **Configure Rewards** button "
            "on the confirmation menu to choose what winners "
            "automatically receive when the giveaway ends. The "
            "reward picker supports Gacha Card / XP / Coins / "
            "Donator Role / Other.\n\n"
            "**`/gend`** `giveaway`\n"
            "Ends a giveaway immediately and draws winners using "
            "the cryptographic randomizer. If rewards were "
            "configured during `/gcreate`, they're granted "
            "automatically and the result announcement shows "
            "exactly who received what.\n\n"
            "**`/greroll`** `giveaway`\n"
            "Re-draws winners for an already-ended giveaway "
            "(e.g. a winner didn't claim, or was disqualified).\n\n"
            "**`/gdelete`** `giveaway`\n"
            "Deletes a giveaway outright — use before it ends if "
            "it was created by mistake.\n\n"
            "**`/gverify`** `giveaway`\n"
            "Re-checks that every entrant is still linked/"
            "verified, in case someone unlinked after entering.\n\n"
            "-# `giveaway` accepts either the internal giveaway "
            "ID or the giveaway message's Discord ID."
        ),
    },

    "account": {
        "label": "Account Linking",
        "emoji": ACCOUNT,
        "short": "/link",
        "description": (
            f"## {ACCOUNT} Account Linking\n\n"
            "**`/link`** `username`\n"
            "Links your Discord account to your Lunar account. "
            "You'll get a one-time code sent to your Lunar "
            "notifications — reply with `!link-code <code>` to "
            "confirm.\n\n"
            "Why link at all? **Every** earning system in this "
            "bot — website XP, coins, gacha ownership, giveaway "
            "rewards — is keyed to your *Lunar* account, not your "
            "Discord ID. Guild XP (this server's own Discord-only "
            "leveling) works without linking, but nothing that "
            "touches the website does.\n\n"
            "Linking also syncs Lunar-side roles (like Website "
            "Donator) onto your Discord roles automatically, "
            "which in turn boosts how much XP and coins you earn "
            f"here — see **{XP} XP & Coins System**."
        ),
    },

    "fun": {
        "label": "Fun & Games",
        "emoji": FUN,
        "short": "/8ball, dice, rate, dadjoke, aki, interact...",
        "description": (
            f"## {FUN} Fun & Games\n\n"
            "**`/8ball`** `question` — Magic 8-ball, cryptographically "
            "random.\n"
            "**`/dice`** `[sides] [count]` — Roll one or more dice.\n"
            "**`/rate`** `thing` — Gives whatever you name a random "
            "score with commentary.\n"
            "**`/dadjoke`** — A random dad joke.\n"
            "**`/randommeme`** — A random meme pulled from Reddit.\n"
            "**`/aki`** — Starts an Akinator game in the channel.\n"
            "**`/interact`** `action` `target` — Send an anime-gif "
            "interaction (hug, pat, slap, etc.) at another member.\n"
            "**`/interaction-help`** — Lists every available "
            "interaction action.\n"
            "**`/steal`** `emoji` — Grabs an emoji from another "
            "server's message and lets you add it to this one "
            "(needs Manage Expressions)."
        ),
    },

    "music": {
        "label": "Music Tracking",
        "emoji": MUSIC,
        "short": "/tmusic and its subcommands",
        "description": (
            f"## {MUSIC} Music Release Tracking\n\n"
            "This isn't a music *player* — it's a release "
            "*tracker* that watches artists/tags on supported "
            "platforms and posts here when something new drops.\n\n"
            "**`/tmusic`** — Shows current tracker status: how "
            "many trackers are active, which platforms are "
            "configured, and polling health.\n"
            "**`/tmusic_add`** `artist` `platform` — Start "
            "tracking an artist/tag.\n"
            "**`/tmusic_remove`** `artist` — Stop tracking one.\n"
            "**`/tmusic_list`** — Lists everything currently "
            "tracked in this server.\n"
            "**`/tmusic_pause`** / **`/tmusic_resume`** — "
            "Temporarily pause or resume polling without deleting "
            "the tracker.\n"
            "**`/tmusic_test`** — Manually trigger a poll cycle "
            "to sanity-check a tracker works."
        ),
    },

    "anime": {
        "label": "Anime & Manga",
        "emoji": ANIME,
        "short": "/anime, /search",
        "description": (
            f"## {ANIME} Anime & Manga\n\n"
            "**`/anime`** `[recommendation] [random]`\n"
            "Pulls anime info from AniList — search, get a "
            "recommendation based on genres, or get something "
            "completely random. Also shows your linked Lunar "
            "anime profile if you have one.\n\n"
            "**`/search`** `query`\n"
            "Searches manga on lunarx.to directly — titles, "
            "chapter counts, upload stats. Results and manga "
            "detail lookups are cached for 5 minutes."
        ),
    },

    "utility": {
        "label": "Utility",
        "emoji": UTILITY,
        "short": "/inbox, /channel, /private-channels...",
        "description": (
            f"## {UTILITY} Utility Commands\n\n"
            "**`/inbox`** — Opens your DM-relay inbox with staff "
            "for support conversations.\n"
            "**`/channel`** — Creates a private channel scoped to "
            "specific users.\n"
            "**`/private-channels`** — Lists private channels you "
            "have access to.\n"
            "**`/channel-delete`** — Deletes a private channel "
            "you own.\n"
            "**`/close`** — Closes/archives the current support "
            "or private channel."
        ),
    },

    "staff": {
        "label": "Staff Tools",
        "emoji": STAFF,
        "short": "/system, /restart (staff-only)",
        "description": (
            f"## {STAFF} Staff Tools *(restricted)*\n\n"
            "**`/system`**\n"
            "Full diagnostics panel — gateway/session health, "
            "database connection status, cache sizes, memory/"
            "Python/host info, and command usage stats. Built as "
            "a multi-page panel you navigate with buttons.\n\n"
            "**`/restart`**\n"
            "Gracefully restarts the bot process.\n\n"
            "-# Both of these check permissions internally — "
            "you'll only see them do anything if you're actually "
            "staff."
        ),
    },

    "xp_system": {
        "label": f"{XP} XP & Coins System",
        "emoji": XP,
        "short": "Deep dive: how earning actually works.",
        "description": (
            f"## {XP} How XP & Coins Actually Work\n\n"
            "### Website XP (message-based)\n"
            "Every qualifying message you send in a server the "
            "bot watches has a chance to earn Lunar website XP. "
            "The amount scales with message length and a random "
            "multiplier/penalty (discourages copy-paste spam), "
            "then gets sent straight to your Lunar profile — "
            "**Lunar's website is always the source of truth** "
            "for your level/XP, the bot never stores or "
            "calculates it locally.\n\n"
            "### Coins (message-based)\n"
            "Separately from XP, eligible messages have a "
            "**12% chance** to earn **1-5 coins**, capped at "
            "**250 coins/day** and gated by a **45-second "
            "cooldown** between grants — this keeps coins "
            "meaningfully rarer than XP. Rolls use the OS's "
            "cryptographic RNG (`secrets.SystemRandom`), the same "
            "entropy source as the giveaway randomizer — not the "
            "predictable `random` module.\n\n"
            "### Guild XP (this server only)\n"
            "A **separate**, Discord-only leveling track with its "
            "own level curve — unlike website XP, this doesn't "
            "require a linked account. Check it with `/level` "
            "(select **Guild XP**).\n\n"
            "### Level-Up Coin Bonuses\n"
            "Leveling up — on **either** the website or in this "
            "server's Guild XP — pays out a coin bonus "
            "automatically. It scales with the level you reach "
            "(higher levels pay more, up to a 5,000-coin ceiling "
            "per level crossed), and jumping multiple levels at "
            "once pays out for every level crossed, not just the "
            "final one.\n\n"
            "### Role Bonuses\n"
            "Two roles boost **everything above** — message XP, "
            "message coins, and level-up bonuses alike:\n"
            f"- {DONATOR} **Website Donator** — **+50%**\n"
            f"- {BOOSTER} **Server Booster** — **+25%**\n"
            "Having both stacks additively (**+75%** total). "
            "These apply automatically the moment you hold the "
            "role — nothing to claim.\n\n"
            "-# None of this works without `/link` first — see "
            f"**{ACCOUNT} Account Linking**."
        ),
    },

    "gacha_system": {
        "label": f"{GACHA} Gacha System",
        "emoji": GACHA,
        "short": "Deep dive: rarity, mint numbers, ownership.",
        "description": (
            f"## {GACHA} How the Gacha System Works\n\n"
            "### Rarity\n"
            "Cards range from **1 to 6+ stars**. Higher rarity "
            "generally means stronger base stats, a lower (or "
            "even fixed/limited) copy count, and flashier skills. "
            "`/gacha list rarity:6` shows every top-tier card at "
            "a glance.\n\n"
            "### Copies & Mint Numbers\n"
            "Some cards have **unlimited copies**; others are "
            "capped (`max_copies`) — once every copy is minted, "
            "no more can be obtained through normal means. Every "
            "individual copy has a **mint number** (1st, 2nd, "
            "3rd... copy ever created) shown via `/gacha owners`, "
            "so low mint numbers on a capped card are genuinely "
            "rare/valuable.\n\n"
            "### Ownership\n"
            "`/gacha owners <card>` lists every current owner by "
            "mint number. `listed` vs `total` in that command's "
            "header tells you how many are actively listed/"
            "tradeable versus how many exist in total.\n\n"
            "### Giveaway Gacha Rewards\n"
            "When a giveaway host configures a **Gacha Card** "
            "reward via the `/gcreate` Configure Rewards menu, the bot double-checks the "
            "card actually exists in the live catalog *before* "
            "saving the config — so a typo'd card name gets "
            "caught immediately instead of failing silently when "
            "the giveaway ends."
        ),
    },
}


PAGE_ORDER = [
    "overview",
    "economy",
    "gacha",
    "giveaways",
    "account",
    "fun",
    "music",
    "anime",
    "utility",
    "staff",
    "xp_system",
    "gacha_system",
]


# ============================================================
# UI
# ============================================================

def build_help_embed(page_key: str) -> discord.Embed:
    page = HELP_PAGES.get(page_key, HELP_PAGES["overview"])

    embed = discord.Embed(
        description=page["description"],
        color=0xF5C518,
    )

    embed.set_footer(
        text=(
            f"{MOON} Lunar Help • {page['label']} • "
            "Use the dropdown below to browse other categories"
        )
    )

    return embed


class HelpSelect(discord.ui.Select):
    def __init__(self, owner_id: int) -> None:
        self.owner_id = owner_id

        options = [
            discord.SelectOption(
                label=HELP_PAGES[key]["label"],
                value=key,
                description=HELP_PAGES[key]["short"][:100],
                emoji=HELP_PAGES[key]["emoji"],
            )
            for key in PAGE_ORDER
        ]

        super().__init__(
            placeholder="Browse a category...",
            options=options,
            min_values=1,
            max_values=1,
        )

    async def callback(
        self, interaction: discord.Interaction
    ) -> None:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                f"{EMOJI['error']} This isn't your help menu — "
                "run `/help` yourself to get your own.",
                ephemeral=True,
            )
            return

        await interaction.response.edit_message(
            embed=build_help_embed(self.values[0])
        )


class HelpView(discord.ui.View):
    def __init__(self, owner_id: int) -> None:
        super().__init__(timeout=300)
        self.add_item(HelpSelect(owner_id))

    async def on_timeout(self) -> None:
        for item in self.children:
            item.disabled = True


# ============================================================
# Cog
# ============================================================

class Help(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(
        name="help",
        description=(
            "Browse every command and how Lunar's systems work."
        ),
    )
    async def help(
        self, interaction: discord.Interaction
    ) -> None:
        await interaction.response.send_message(
            embed=build_help_embed("overview"),
            view=HelpView(interaction.user.id),
            ephemeral=True,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Help(bot))
