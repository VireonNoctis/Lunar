from __future__ import annotations

import asyncio
import logging
import os
import threading
from typing import Any

import discord
from discord.ext import commands
from flask import Flask, jsonify, request


log = logging.getLogger("Lunar.API")


# ============================================================
# CONFIG
# ============================================================

API_HOST = os.getenv("LUNAR_API_HOST", "0.0.0.0")
API_PORT = int(os.getenv("LUNAR_API_PORT", "8080"))

# Secret shared between LunarX backend and this bot.
API_KEY = os.getenv("LUNAR_API_KEY")

# Discord channel where new cards are posted.
CARD_CHANNEL_ID = 69

app = Flask(__name__)
api_cog: "LunarAPI | None" = None


# ============================================================
# AUTH
# ============================================================

def is_authorized() -> bool:
  
    if not API_KEY:
        return False

    supplied = request.headers.get(
        "X-Lunar-API-Key"
    )

    return supplied == API_KEY


# ============================================================
# BOT LOOP BRIDGE
# ============================================================

def run_on_bot_loop(
    bot: commands.Bot,
    coroutine,
    timeout: float = 30.0,
):
 

    future = asyncio.run_coroutine_threadsafe(
        coroutine,
        bot.loop,
    )

    return future.result(timeout=timeout)


# ============================================================
# HEALTH
# ============================================================

@app.get("/")
def index():
    return jsonify(
        {
            "service": "Lunar Discord API",
            "status": "online",
        }
    )


@app.get("/health")
def health():
    return jsonify(
        {
            "ok": True,
            "discord": (
                api_cog is not None
                and api_cog.bot.is_ready()
            ),
        }
    )


# ============================================================
# CARD POSTING ENDPOINT
# ============================================================

@app.post("/api/cards") #need this
def receive_cards():


    # --------------------------------------------------------
    # AUTHENTICATION
    # --------------------------------------------------------

    if not is_authorized():
        return jsonify(
            {
                "ok": False,
                "error": "Unauthorized",
            }
        ), 401

    # --------------------------------------------------------
    # JSON
    # --------------------------------------------------------

    data: Any = request.get_json(
        silent=True
    )

    if not isinstance(data, dict):
        return jsonify(
            {
                "ok": False,
                "error": "Invalid JSON body.",
            }
        ), 400

    cards = data.get("cards")

    if not isinstance(cards, list):
        return jsonify(
            {
                "ok": False,
                "error": "'cards' must be an array.",
            }
        ), 400

    if not cards:
        return jsonify(
            {
                "ok": False,
                "error": "No cards supplied.",
            }
        ), 400

    if api_cog is None:
        return jsonify(
            {
                "ok": False,
                "error": "API system is not ready.",
            }
        ), 503

    # --------------------------------------------------------
    # PROCESS THROUGH DISCORD BOT
    # --------------------------------------------------------

    try:

        result = run_on_bot_loop(
            api_cog.bot,
            api_cog.post_cards(cards),
        )

    except TimeoutError:

        log.exception(
            "Timed out while posting cards."
        )

        return jsonify(
            {
                "ok": False,
                "error": "Discord operation timed out.",
            }
        ), 504

    except Exception:

        log.exception(
            "Failed to post cards."
        )

        return jsonify(
            {
                "ok": False,
                "error": "Failed to process cards.",
            }
        ), 500

    return jsonify(
        {
            "ok": True,
            "posted": result["posted"],
            "failed": result["failed"],
        }
    ), 200


# ============================================================
# DISCORD COG
# ============================================================

class LunarAPI(commands.Cog):
    """
    Flask API integration for LunarX.

    Flask runs beside Discord.py in its own thread.
    """

    def __init__(
        self,
        bot: commands.Bot,
    ):
        self.bot = bot
        self.server_thread: threading.Thread | None = None

        global api_cog
        api_cog = self

    # ========================================================
    # CARD PROCESSING
    # ========================================================

    async def post_cards(
        self,
        cards: list[dict[str, Any]],
    ) -> dict[str, int]:
        """
        Post every card received from LunarX.

        Duplicate cards are intentionally NOT removed.

        If LunarX sends the same JSON object multiple times,
        each occurrence will be posted.
        """

        channel = self.bot.get_channel(
            CARD_CHANNEL_ID
        )

        if channel is None:
            raise RuntimeError(
                f"Card channel {CARD_CHANNEL_ID} was not found."
            )

        if not isinstance(
            channel,
            discord.abc.Messageable,
        ):
            raise RuntimeError(
                "Configured card channel is not messageable."
            )

        posted = 0
        failed = 0

        for card in cards:

            if not isinstance(card, dict):
                failed += 1
                continue

            try:

                embed = self.build_card_embed(
                    card
                )

                await channel.send(
                    embed=embed
                )

                posted += 1

            except Exception:

                failed += 1

                log.exception(
                    "Failed to post card: %r",
                    card,
                )

        return {
            "posted": posted,
            "failed": failed,
        }

    # ========================================================
    # EMBED BUILDER
    # ========================================================

    @staticmethod
    def build_card_embed(
        card: dict[str, Any],
    ) -> discord.Embed:
        """
        Convert LunarX card JSON into a Discord embed.
        """

        name = str(
            card.get(
                "name",
                "Unknown Card",
            )
        )

        rarity = card.get(
            "rarity",
            0,
        )

        stars = card.get(
            "stars",
            "★" * int(rarity or 0),
        )

        role = card.get(
            "role",
            card.get(
                "class",
                "Unknown",
            ),
        )

        element = card.get(
            "element",
            "Unknown",
        )

        base_attack = card.get(
            "base_attack",
            0,
        )

        base_defense = card.get(
            "base_defense",
            0,
        )

        base_hp = card.get(
            "base_hp",
            0,
        )

        copies = card.get(
            "copies",
            0,
        )

        submitted_by = card.get(
            "submitted_by",
            "Unknown",
        )

        template_id = card.get(
            "template_id",
            "Unknown",
        )

        votes = card.get(
            "votes",
            0,
        )

        embed = discord.Embed(
            title=f"{stars} {name}",
            description=(
                f"**Role:** {role}\n"
                f"**Element:** {element}\n\n"
                f"**ATK:** {base_attack}\n"
                f"**DEF:** {base_defense}\n"
                f"**HP:** {base_hp}\n"
            ),
            color=discord.Color.gold(),
        )

        # ----------------------------------------------------
        # ABILITIES
        # ----------------------------------------------------

        abilities = card.get(
            "abilities",
            [],
        )

        if isinstance(
            abilities,
            list,
        ):

            for ability in abilities:

                if not isinstance(
                    ability,
                    dict,
                ):
                    continue

                ability_name = ability.get(
                    "name",
                    "Ability",
                )

                ability_description = ability.get(
                    "description",
                    "No description.",
                )

                embed.add_field(
                    name=str(
                        ability_name
                    ),
                    value=str(
                        ability_description
                    ),
                    inline=False,
                )

        # ----------------------------------------------------
        # IMAGE
        # ----------------------------------------------------

        image_url = card.get(
            "image_url"
        )

        if image_url:
            embed.set_image(
                url=str(image_url)
            )

        # ----------------------------------------------------
        # FOOTER
        # ----------------------------------------------------

        embed.set_footer(
            text=(
                f"Template: {template_id} • "
                f"Copies: {copies} • "
                f"Votes: {votes} • "
                f"Submitted by: {submitted_by}"
            )
        )

        return embed

    # ========================================================
    # SERVER
    # ========================================================

    def start_server(self) -> None:

        if self.server_thread is not None:
            return

        self.server_thread = threading.Thread(
            target=self.run_server,
            name="LunarFlaskAPI",
            daemon=True,
        )

        self.server_thread.start()

        log.info(
            "Lunar API listening on %s:%s",
            API_HOST,
            API_PORT,
        )

    def run_server(self) -> None:

        app.run(
            host=API_HOST,
            port=API_PORT,
            debug=False,
            use_reloader=False,
            threaded=True,
        )

    # ========================================================
    # COG LOAD
    # ========================================================

    async def cog_load(self) -> None:
        self.start_server()

        log.info(
            "Lunar Flask API loaded."
        )

    async def cog_unload(self) -> None:

        global api_cog

        api_cog = None

        log.info(
            "Lunar Flask API unloaded."
        )


# ============================================================
# SETUP
# ============================================================

async def setup(
    bot: commands.Bot,
) -> None:

    await bot.add_cog(
        LunarAPI(bot)
    )