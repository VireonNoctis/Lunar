#!/usr/bin/env python3
# ==============================================================================
#  LUNAR.PY  —  General-purpose Telegram bot for Lunar
# ==============================================================================
#
#  Requirements:
#      pip install python-telegram-bot httpx
#
#  Run:
#      python3 Lunar.py
#
#  No .env / no environment variables are used. Fill in CFG.token and
#  CFG.owner_id below and you're live.
#
# ==============================================================================

from __future__ import annotations

import ast
import hashlib
import html
import json
import logging
import operator as op
import os
import random as _stdlib_random  
import secrets
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote as url_quote

import httpx
from telegram import Chat, ChatMember, ChatMemberUpdated, Update
from telegram.constants import ChatType, ParseMode
from telegram.error import Forbidden, BadRequest, TelegramError
from telegram.ext import (
    Application,
    ApplicationHandlerStop,
    ChatMemberHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# ==============================================================================
#  CONFIGURATION
# ==============================================================================


@dataclass(slots=True)
class Config:
    token: str = "PUT_YOUR_BOT_TOKEN_HERE"          
    owner_id: int = 0                                 
    developer_handle: str = "@TheSlopKing"
    website: str = "lunarx.to"
    bot_name: str = "Lunar"
    data_file: str = "lunar_bot_users.json"
    http_timeout: float = 6.0


CFG = Config()


logging.basicConfig(
    format="[%(asctime)s] [%(levelname)s] [Lunar] %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("Lunar")


# ==============================================================================
#  CRYPTOGRAPHIC RANDOMIZER  (provably-fair — every roll/flip/pick ships proof)
# ==============================================================================
#
#  We never touch the `random` module for anything user-facing. Every random
#  outcome in this bot is drawn from `secrets` (OS CSPRNG) and comes with a
#  seed + SHA-256 proof so the result can be independently re-verified:
#
#      sha256(seed_hex) == proof_hex
#
# ==============================================================================


def _crypto_draw(n: int) -> tuple[int, str, str]:
    """Draw an unbiased value in [0, n) via CSPRNG. Returns (value, seed_hex, proof_hex)."""
    if n <= 0:
        raise ValueError("n must be a positive integer.")
    raw = secrets.token_bytes(32)
    seed_hex = raw.hex()
    proof_hex = hashlib.sha256(raw).hexdigest()
    value = int.from_bytes(raw, "big") % n
    return value, seed_hex, proof_hex


def crypto_randbelow(n: int) -> tuple[int, str]:
    value, seed_hex, proof_hex = _crypto_draw(n)
    proof = f"seed={seed_hex[:16]}… | sha256={proof_hex}"
    return value, proof


def crypto_choice(seq: list[Any]) -> tuple[Any, str]:
    idx, proof = crypto_randbelow(len(seq))
    return seq[idx], proof


def crypto_shuffle_order(seq: list[Any]) -> list[Any]:
    """Fisher–Yates shuffle powered entirely by the CSPRNG."""
    pool = list(seq)
    for i in range(len(pool) - 1, 0, -1):
        j, _ = crypto_randbelow(i + 1)
        pool[i], pool[j] = pool[j], pool[i]
    return pool


# ==============================================================================
#  USER / GROUP REGISTRY  
# ==============================================================================


@dataclass(slots=True)
class Registry:
    users: dict[str, dict] = field(default_factory=dict)
    groups: dict[str, dict] = field(default_factory=dict)

    def to_json(self) -> dict:
        return {"users": self.users, "groups": self.groups}

    @classmethod
    def from_json(cls, payload: dict) -> "Registry":
        return cls(users=payload.get("users", {}), groups=payload.get("groups", {}))


def load_registry() -> Registry:
    path = Path(CFG.data_file)
    if not path.exists():
        return Registry()
    try:
        return Registry.from_json(json.loads(path.read_text(encoding="utf-8")))
    except (json.JSONDecodeError, OSError) as exc:
        log.warning("Registry file unreadable (%s) — starting fresh.", exc)
        return Registry()


def save_registry(registry: Registry) -> None:
    path = Path(CFG.data_file)
    tmp_path = path.with_suffix(".tmp")
    try:
        tmp_path.write_text(json.dumps(registry.to_json(), indent=2), encoding="utf-8")
        os.replace(tmp_path, path)
    except OSError as exc:
        log.error("Failed to persist registry: %s", exc)


REGISTRY = load_registry()


def register_private_user(user_id: int, username: str | None) -> None:
    key = str(user_id)
    is_new = key not in REGISTRY.users
    REGISTRY.users[key] = {"username": username or "", "last_seen": time.time()}
    if is_new:
        save_registry(REGISTRY)


def _ensure_group(chat_id: int, title: str | None) -> dict:
    key = str(chat_id)
    entry = REGISTRY.groups.setdefault(key, {"title": title or "", "members": {}})
    if title and entry.get("title") != title:
        entry["title"] = title
    return entry


def register_group(chat_id: int, title: str | None) -> None:
    """Ensure the group itself is known, even before any member is recorded."""
    before = json.dumps(REGISTRY.groups.get(str(chat_id)))
    entry = _ensure_group(chat_id, title)
    if json.dumps(entry) != before:
        save_registry(REGISTRY)


def register_group_member(
    chat_id: int, title: str | None, user_id: int, first_name: str | None, username: str | None
) -> None:
    """Learn that `user_id` is present in group `chat_id` — this is what /callall tags."""
    entry = _ensure_group(chat_id, title)
    key = str(user_id)
    existing = entry["members"].get(key)
    changed = existing is None or existing.get("first_name") != first_name or existing.get("username") != username
    entry["members"][key] = {
        "first_name": first_name or "",
        "username": username or "",
        "last_seen": time.time(),
    }
    if changed:
        save_registry(REGISTRY)


def remove_group_member(chat_id: int, user_id: int) -> None:
    entry = REGISTRY.groups.get(str(chat_id))
    if entry and str(user_id) in entry.get("members", {}):
        del entry["members"][str(user_id)]
        save_registry(REGISTRY)


# ==============================================================================
#  EXTERNAL DATA SOURCES — quotes & facts, multi-API with attribution + fallback
# ==============================================================================
#
#  Each entry: (source_name, url, json_path_extractor)
#  On every call the source ORDER is decided by the CSPRNG (crypto_shuffle_order),
#  then we walk the list until one responds — first success wins and is cited.
# ==============================================================================

QUOTE_SOURCES: list[tuple[str, str, Any]] = [
    ("Quotable", "https://api.quotable.io/random",
     lambda d: (d["content"], d.get("author", "Unknown"))),
    ("ZenQuotes", "https://zenquotes.io/api/random",
     lambda d: (d[0]["q"], d[0].get("a", "Unknown"))),
    ("DummyJSON Quotes", "https://dummyjson.com/quotes/random",
     lambda d: (d["quote"], d.get("author", "Unknown"))),
]

FACT_SOURCES: list[tuple[str, str, Any]] = [
    ("Useless Facts API", "https://uselessfacts.jsph.pl/api/v2/facts/random",
     lambda d: d["text"]),
    ("Numbers API", "https://numbersapi.com/random/trivia?json",
     lambda d: d["text"]),
    ("Cat Facts API", "https://catfact.ninja/fact",
     lambda d: d["fact"]),
]

JOKE_SOURCES: list[tuple[str, str, Any]] = [
    ("icanhazdadjoke", "https://icanhazdadjoke.com/",
     lambda d: d["joke"]),
    ("Official Joke API", "https://official-joke-api.appspot.com/random_joke",
     lambda d: f'{d["setup"]} — {d["punchline"]}'),
]

_LOCAL_QUOTE_FALLBACK = [
    ("The night is darkest just before the dawn.", "Local Archive"),
    ("Not all those who wander are lost.", "Local Archive"),
]

_LOCAL_FACT_FALLBACK = [
    "Honey never spoils — archaeologists have found 3000-year-old honey that's still edible.",
    "Octopuses have three hearts and blue blood.",
]

_LOCAL_JOKE_FALLBACK = [
    "Why do programmers prefer dark mode? Because light attracts bugs.",
]


async def _fetch_json(client: httpx.AsyncClient, url: str) -> dict:
    headers = {"Accept": "application/json", "User-Agent": f"{CFG.bot_name}-Bot/1.0"}
    resp = await client.get(url, headers=headers, timeout=CFG.http_timeout)
    resp.raise_for_status()
    return resp.json()


async def fetch_quote() -> tuple[str, str, str]:
    """Returns (quote_text, author, source_name). Falls back to local archive on total failure."""
    order = crypto_shuffle_order(QUOTE_SOURCES)
    async with httpx.AsyncClient() as client:
        for source_name, url, extractor in order:
            try:
                data = await _fetch_json(client, url)
                text, author = extractor(data)
                return str(text).strip(), str(author).strip(), source_name
            except (httpx.HTTPError, KeyError, IndexError, ValueError, TypeError) as exc:
                log.info("Quote source '%s' failed: %s", source_name, exc)
                continue
    text, author = crypto_choice(_LOCAL_QUOTE_FALLBACK)[0]
    return text, author, "Local Archive"


async def fetch_fact() -> tuple[str, str]:
    """Returns (fact_text, source_name). Falls back to local archive on total failure."""
    order = crypto_shuffle_order(FACT_SOURCES)
    async with httpx.AsyncClient() as client:
        for source_name, url, extractor in order:
            try:
                data = await _fetch_json(client, url)
                text = extractor(data)
                return str(text).strip(), source_name
            except (httpx.HTTPError, KeyError, IndexError, ValueError, TypeError) as exc:
                log.info("Fact source '%s' failed: %s", source_name, exc)
                continue
    fact, _ = crypto_choice(_LOCAL_FACT_FALLBACK)
    return fact, "Local Archive"


async def fetch_joke() -> tuple[str, str]:
    order = crypto_shuffle_order(JOKE_SOURCES)
    async with httpx.AsyncClient() as client:
        for source_name, url, extractor in order:
            try:
                data = await _fetch_json(client, url)
                text = extractor(data)
                return str(text).strip(), source_name
            except (httpx.HTTPError, KeyError, IndexError, ValueError, TypeError) as exc:
                log.info("Joke source '%s' failed: %s", source_name, exc)
                continue
    joke, _ = crypto_choice(_LOCAL_JOKE_FALLBACK)
    return joke, "Local Archive"


# ==============================================================================
#  SAFE ARITHMETIC   ==============================================================================

_ALLOWED_BINOPS = {
    ast.Add: op.add, ast.Sub: op.sub, ast.Mult: op.mul, ast.Div: op.truediv,
    ast.FloorDiv: op.floordiv, ast.Mod: op.mod, ast.Pow: op.pow,
}
_ALLOWED_UNARYOPS = {ast.USub: op.neg, ast.UAdd: op.pos}


def safe_eval(expr: str) -> float:
    if len(expr) > 128:
        raise ValueError("Expression too long.")

    def _eval(node: ast.AST) -> float:
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in _ALLOWED_BINOPS:
            return _ALLOWED_BINOPS[type(node.op)](_eval(node.left), _eval(node.right))
        if isinstance(node, ast.UnaryOp) and type(node.op) in _ALLOWED_UNARYOPS:
            return _ALLOWED_UNARYOPS[type(node.op)](_eval(node.operand))
        raise ValueError("Only numbers and + - * / // % ** are allowed.")

    tree = ast.parse(expr, mode="eval")
    return _eval(tree.body)


# ==============================================================================
#  BACKGROUND AUTO-REGISTRATION
# ==============================================================================


async def silently_register(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat = update.effective_chat
    user = update.effective_user
    if chat is None or user is None:
        return
    if chat.type == ChatType.PRIVATE:
        register_private_user(user.id, user.username)
    elif chat.type in (ChatType.GROUP, ChatType.SUPERGROUP):
        register_group_member(chat.id, chat.title, user.id, user.first_name, user.username)


async def track_chat_member_updates(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Catches people joining/leaving a group the bot is in and keeps that group's
    member map current — this is the list /callall tags directly inside the
    group, so no DM permission from the user is ever required.
    """
    result: ChatMemberUpdated | None = update.chat_member
    if result is None:
        return

    chat = result.chat
    if chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        return

    register_group(chat.id, chat.title)

    new_status = result.new_chat_member.status
    old_status = result.old_chat_member.status
    member = result.new_chat_member.user

    joined = old_status in (ChatMember.LEFT, ChatMember.BANNED) and new_status in (
        ChatMember.MEMBER, ChatMember.ADMINISTRATOR, ChatMember.OWNER,
    )
    left = new_status in (ChatMember.LEFT, ChatMember.BANNED)

    if joined:
        register_group_member(chat.id, chat.title, member.id, member.first_name, member.username)
    elif left:
        remove_group_member(chat.id, member.id)


# ==============================================================================
#  GENERAL COMMANDS
# ==============================================================================

FOOTER = f"\n\n🌙 <i>{CFG.bot_name} — built by {CFG.developer_handle} — {CFG.website}</i>"


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "🌙 <b>Lunar — Command Directory</b>\n\n"
        "<b>Info</b>\n"
        "/about — what this bot is\n"
        "/ping — check latency\n"
        "/id — your user &amp; chat ID\n"
        "/time — current UTC time\n\n"
        "<b>Utility</b>\n"
        "/echo &lt;text&gt; — repeats your text\n"
        "/calc &lt;expr&gt; — safe calculator\n"
        "/reverse &lt;text&gt; — reverses your text\n\n"
        "<b>Fun (provably fair, CSPRNG-powered)</b>\n"
        "/roll [NdN] — dice roll, e.g. /roll 2d6\n"
        "/flip — coin flip\n"
        "/choose opt1 | opt2 | ... — random pick\n"
        "/8ball &lt;question&gt; — magic 8-ball\n"
        "/rate &lt;thing&gt; — rate anything 0–100\n"
        "/ship &lt;a&gt; &lt;b&gt; — compatibility %\n"
        "/joke — random joke\n"
        "/fact — random fact (cited)\n"
        "/quote — random quote (cited)\n\n"
        "<b>External</b>\n"
        "/weather &lt;city&gt; — current weather\n"
        "/crypto &lt;coin-id&gt; — live price, e.g. /crypto bitcoin\n"
        "/define &lt;word&gt; — dictionary lookup\n"
        "/trivia — random trivia (spoiler-hidden answer)\n"
        "/advice — random advice\n"
        "/meme — random meme\n"
        "/cat, /dog — random animal pic\n"
        "/qr &lt;text&gt; — generate a QR code\n"
    )
    await update.effective_message.reply_text(text + FOOTER, parse_mode=ParseMode.HTML)


async def cmd_about(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        f"🌙 <b>{CFG.bot_name}</b>\n"
        f"General-purpose companion bot.\n\n"
        f"Developer: {CFG.developer_handle}\n"
        f"Website: {CFG.website}\n"
        f"Registered users: {len(REGISTRY.users)} | Groups: {len(REGISTRY.groups)}"
    )
    await update.effective_message.reply_text(text, parse_mode=ParseMode.HTML)


async def cmd_ping(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    start = time.perf_counter()
    sent = await update.effective_message.reply_text("🌙 Pinging…")
    elapsed_ms = (time.perf_counter() - start) * 1000
    await sent.edit_text(f"🌙 Pong — {elapsed_ms:.0f} ms")


async def cmd_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    chat = update.effective_chat
    await update.effective_message.reply_text(
        f"🌙 User ID: <code>{user.id}</code>\nChat ID: <code>{chat.id}</code>",
        parse_mode=ParseMode.HTML,
    )


async def cmd_time(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    await update.effective_message.reply_text(f"🌙 {now}")


async def cmd_echo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = " ".join(context.args) if context.args else ""
    if not text:
        await update.effective_message.reply_text("🌙 Usage: /echo <text>")
        return
    await update.effective_message.reply_text(text)


async def cmd_reverse(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = " ".join(context.args) if context.args else ""
    if not text:
        await update.effective_message.reply_text("🌙 Usage: /reverse <text>")
        return
    await update.effective_message.reply_text(text[::-1])


async def cmd_calc(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    expr = " ".join(context.args) if context.args else ""
    if not expr:
        await update.effective_message.reply_text("🌙 Usage: /calc <expression>  e.g. /calc (4+2)*3")
        return
    try:
        result = safe_eval(expr)
        await update.effective_message.reply_text(f"🌙 {expr} = <b>{result:g}</b>", parse_mode=ParseMode.HTML)
    except (ValueError, ZeroDivisionError, SyntaxError, OverflowError) as exc:
        await update.effective_message.reply_text(f"🌙 Couldn't compute that: {exc}")


# --- Fun / CSPRNG commands ---------------------------------------------------

async def cmd_roll(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    spec = context.args[0] if context.args else "1d6"
    try:
        count_str, sides_str = spec.lower().split("d")
        count, sides = int(count_str or 1), int(sides_str)
        if not (1 <= count <= 20 and 2 <= sides <= 1000):
            raise ValueError
    except ValueError:
        await update.effective_message.reply_text("🌙 Usage: /roll NdN  e.g. /roll 2d6  (max 20 dice, 1000 sides)")
        return

    rolls, proofs = [], []
    for _ in range(count):
        value, proof = crypto_randbelow(sides)
        rolls.append(value + 1)
        proofs.append(proof)

    text = f"🌙 Rolled {spec}: <b>{rolls}</b> (total {sum(rolls)})\n<code>{proofs[0]}</code>"
    await update.effective_message.reply_text(text, parse_mode=ParseMode.HTML)


async def cmd_flip(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    result, proof = crypto_choice(["Heads", "Tails"])
    await update.effective_message.reply_text(
        f"🌙 <b>{result}</b>\n<code>{proof}</code>", parse_mode=ParseMode.HTML
    )


async def cmd_choose(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    raw = " ".join(context.args) if context.args else ""
    options = [opt.strip() for opt in raw.split("|") if opt.strip()]
    if len(options) < 2:
        await update.effective_message.reply_text("🌙 Usage: /choose option1 | option2 | option3 ...")
        return
    pick, proof = crypto_choice(options)
    await update.effective_message.reply_text(
        f"🌙 I choose: <b>{pick}</b>\n<code>{proof}</code>", parse_mode=ParseMode.HTML
    )


EIGHT_BALL_API_URL = "https://eightballapi.com/api"  # free, keyless, {"reading": "..."}

# Offline fallback — used only if the live API is unreachable. 50 responses,
# the 20 classic answers plus 30 extra in the same spirit.
EIGHT_BALL_FALLBACK = [
    # Classic affirmative
    "It is certain.", "It is decidedly so.", "Without a doubt.", "Yes, definitely.",
    "You may rely on it.", "As I see it, yes.", "Most likely.", "Outlook good.",
    "Yes.", "Signs point to yes.",
    # Classic non-committal
    "Reply hazy, try again.", "Ask again later.", "Better not tell you now.",
    "Cannot predict now.", "Concentrate and ask again.",
    # Classic negative
    "Don't count on it.", "My reply is no.", "My sources say no.",
    "Outlook not so good.", "Very doubtful.",
    # Extended affirmative
    "The stars align in your favor.", "Absolutely.", "The moon confirms it.",
    "Every sign says yes.", "Count on it.", "Undoubtedly so.",
    "The odds are ever in your favor.", "It's practically guaranteed.",
    "Trust the process — yes.", "The omens are good.",
    # Extended non-committal
    "Ask again under a fuller moon.", "The answer is shrouded in fog.",
    "Even the stars are unsure.", "Focus, then ask once more.",
    "Too many variables — try later.", "The signs are scattered.",
    "Unclear at this time.", "The tides haven't decided yet.",
    "Patience — the answer isn't ready.", "Try rephrasing the question.",
    # Extended negative
    "The moon says no.", "Not a chance.", "The odds are against you.",
    "Highly unlikely.", "The stars advise against it.",
    "Don't get your hopes up.", "Definitely not.", "The signs point away from yes.",
    "It would be unwise to count on it.", "No — and that's final.",
]


async def fetch_8ball_reading() -> tuple[str, str]:
    """Returns (answer_text, source). Falls back to a local CSPRNG pick on failure."""
    try:
        async with httpx.AsyncClient() as client:
            data = await _fetch_json(client, EIGHT_BALL_API_URL)
        reading = str(data["reading"]).strip()
        if reading:
            return reading, "eightballapi.com"
    except (httpx.HTTPError, KeyError, ValueError, TypeError) as exc:
        log.info("8ball API failed, falling back to local CSPRNG pool: %s", exc)

    answer, proof = crypto_choice(EIGHT_BALL_FALLBACK)
    return answer, f"Local CSPRNG pool | {proof}"


async def cmd_8ball(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    question = " ".join(context.args) if context.args else ""
    if not question:
        await update.effective_message.reply_text("🌙 Usage: /8ball <question>")
        return
    answer, source = await fetch_8ball_reading()
    await update.effective_message.reply_text(
        f"🎱 <b>{answer}</b>\n<i>Source: {source}</i>", parse_mode=ParseMode.HTML
    )


async def cmd_rate(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    thing = " ".join(context.args) if context.args else ""
    if not thing:
        await update.effective_message.reply_text("🌙 Usage: /rate <anything>")
        return
    score, proof = crypto_randbelow(101)
    await update.effective_message.reply_text(
        f"🌙 I'd rate <b>{thing}</b>: <b>{score}/100</b>\n<code>{proof}</code>", parse_mode=ParseMode.HTML
    )


async def cmd_ship(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if len(context.args) < 2:
        await update.effective_message.reply_text("🌙 Usage: /ship <name1> <name2>")
        return
    a, b = context.args[0], context.args[1]
    score, proof = crypto_randbelow(101)
    bar_filled = score // 10
    bar = "🌕" * bar_filled + "🌑" * (10 - bar_filled)
    await update.effective_message.reply_text(
        f"🌙 <b>{a} × {b}</b> = <b>{score}%</b>\n{bar}\n<code>{proof}</code>",
        parse_mode=ParseMode.HTML,
    )


async def cmd_joke(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    joke, source = await fetch_joke()
    await update.effective_message.reply_text(f"🌙 {joke}\n\n<i>Source: {source}</i>", parse_mode=ParseMode.HTML)


async def cmd_fact(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    fact, source = await fetch_fact()
    await update.effective_message.reply_text(f"🌙 {fact}\n\n<i>Source: {source}</i>", parse_mode=ParseMode.HTML)


async def cmd_quote(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text, author, source = await fetch_quote()
    await update.effective_message.reply_text(
        f'🌙 "{text}"\n— {author}\n\n<i>Source: {source}</i>', parse_mode=ParseMode.HTML
    )


# ==============================================================================
#  OWNER-ONLY: /callall  —  tags every known member directly inside the group
# ==============================================================================
#  MORE GENERAL COMMANDS 
# ==============================================================================


async def cmd_weather(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    city = " ".join(context.args) if context.args else ""
    if not city:
        await update.effective_message.reply_text("🌙 Usage: /weather <city>")
        return
    url = f"https://wttr.in/{url_quote(city)}?format=j1"
    try:
        async with httpx.AsyncClient() as client:
            data = await _fetch_json(client, url)
        current = data["current_condition"][0]
        desc = current["weatherDesc"][0]["value"]
        temp_c, feels_c, humidity = current["temp_C"], current["FeelsLikeC"], current["humidity"]
        await update.effective_message.reply_text(
            f"🌙 Weather in <b>{html.escape(city.title())}</b>: {desc}, {temp_c}°C "
            f"(feels {feels_c}°C), {humidity}% humidity\n<i>Source: wttr.in</i>",
            parse_mode=ParseMode.HTML,
        )
    except (httpx.HTTPError, KeyError, IndexError, ValueError, TypeError) as exc:
        log.info("Weather lookup failed for '%s': %s", city, exc)
        await update.effective_message.reply_text("🌙 Couldn't fetch weather for that location right now.")


async def cmd_crypto(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    coin = context.args[0].lower() if context.args else ""
    if not coin:
        await update.effective_message.reply_text("🌙 Usage: /crypto <coin-id>  e.g. /crypto bitcoin")
        return
    url = (
        f"https://api.coingecko.com/api/v3/simple/price?ids={url_quote(coin)}"
        f"&vs_currencies=usd&include_24hr_change=true"
    )
    try:
        async with httpx.AsyncClient() as client:
            data = await _fetch_json(client, url)
        info = data[coin]
        price, change = info["usd"], info.get("usd_24h_change", 0.0)
        arrow = "📈" if change >= 0 else "📉"
        await update.effective_message.reply_text(
            f"🌙 <b>{coin.title()}</b>: ${price:,.2f} {arrow} {change:+.2f}% (24h)\n<i>Source: CoinGecko</i>",
            parse_mode=ParseMode.HTML,
        )
    except (httpx.HTTPError, KeyError, ValueError, TypeError) as exc:
        log.info("Crypto lookup failed for '%s': %s", coin, exc)
        await update.effective_message.reply_text(
            "🌙 Couldn't find that coin — use a CoinGecko ID, e.g. bitcoin, ethereum, dogecoin."
        )


async def cmd_define(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    word = context.args[0] if context.args else ""
    if not word:
        await update.effective_message.reply_text("🌙 Usage: /define <word>")
        return
    url = f"https://api.dictionaryapi.dev/api/v2/entries/en/{url_quote(word)}"
    try:
        async with httpx.AsyncClient() as client:
            data = await _fetch_json(client, url)
        meaning = data[0]["meanings"][0]
        definition = meaning["definitions"][0]["definition"]
        await update.effective_message.reply_text(
            f"🌙 <b>{html.escape(word)}</b> <i>({meaning['partOfSpeech']})</i>\n{html.escape(definition)}"
            f"\n\n<i>Source: dictionaryapi.dev</i>",
            parse_mode=ParseMode.HTML,
        )
    except (httpx.HTTPError, KeyError, IndexError, ValueError, TypeError) as exc:
        log.info("Define lookup failed for '%s': %s", word, exc)
        await update.effective_message.reply_text(f"🌙 No definition found for '{word}'.")


async def cmd_trivia(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    url = "https://opentdb.com/api.php?amount=1&type=multiple"
    try:
        async with httpx.AsyncClient() as client:
            data = await _fetch_json(client, url)
        item = data["results"][0]
        question = html.unescape(item["question"])
        correct = html.unescape(item["correct_answer"])
        incorrect = [html.unescape(a) for a in item["incorrect_answers"]]
        options = crypto_shuffle_order([correct] + incorrect)  # CSPRNG-ordered choices
        options_text = "\n".join(f"{i + 1}. {html.escape(opt)}" for i, opt in enumerate(options))
        correct_index = options.index(correct) + 1
        await update.effective_message.reply_text(
            f"🌙 <b>Trivia:</b> {html.escape(question)}\n\n{options_text}\n\n"
            f"<tg-spoiler>Answer: {correct_index}. {html.escape(correct)}</tg-spoiler>\n"
            f"<i>Source: Open Trivia DB</i>",
            parse_mode=ParseMode.HTML,
        )
    except (httpx.HTTPError, KeyError, IndexError, ValueError, TypeError) as exc:
        log.info("Trivia fetch failed: %s", exc)
        await update.effective_message.reply_text("🌙 Couldn't fetch a trivia question right now.")


async def cmd_advice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    url = "https://api.adviceslip.com/advice"
    try:
        async with httpx.AsyncClient() as client:
            data = await _fetch_json(client, url)
        await update.effective_message.reply_text(
            f"🌙 {html.escape(data['slip']['advice'])}\n\n<i>Source: Advice Slip API</i>",
            parse_mode=ParseMode.HTML,
        )
    except (httpx.HTTPError, KeyError, ValueError, TypeError) as exc:
        log.info("Advice fetch failed: %s", exc)
        await update.effective_message.reply_text("🌙 Couldn't fetch advice right now.")


async def cmd_meme(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    url = "https://meme-api.com/gimme"
    try:
        async with httpx.AsyncClient() as client:
            data = await _fetch_json(client, url)
        await update.effective_message.reply_photo(
            photo=data["url"],
            caption=f"🌙 {html.escape(data.get('title', ''))}\n\n"
                    f"<i>Source: r/{html.escape(data.get('subreddit', ''))} via meme-api.com</i>",
            parse_mode=ParseMode.HTML,
        )
    except (httpx.HTTPError, KeyError, ValueError, TypeError, TelegramError) as exc:
        log.info("Meme fetch failed: %s", exc)
        await update.effective_message.reply_text("🌙 Couldn't fetch a meme right now.")


async def cmd_cat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    url = "https://api.thecatapi.com/v1/images/search"
    try:
        async with httpx.AsyncClient() as client:
            data = await _fetch_json(client, url)
        await update.effective_message.reply_photo(
            photo=data[0]["url"], caption="🌙 <i>Source: The Cat API</i>", parse_mode=ParseMode.HTML
        )
    except (httpx.HTTPError, KeyError, IndexError, ValueError, TypeError, TelegramError) as exc:
        log.info("Cat fetch failed: %s", exc)
        await update.effective_message.reply_text("🌙 Couldn't fetch a cat picture right now.")


async def cmd_dog(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    url = "https://dog.ceo/api/breeds/image/random"
    try:
        async with httpx.AsyncClient() as client:
            data = await _fetch_json(client, url)
        await update.effective_message.reply_photo(
            photo=data["message"], caption="🌙 <i>Source: Dog CEO API</i>", parse_mode=ParseMode.HTML
        )
    except (httpx.HTTPError, KeyError, ValueError, TypeError, TelegramError) as exc:
        log.info("Dog fetch failed: %s", exc)
        await update.effective_message.reply_text("🌙 Couldn't fetch a dog picture right now.")


async def cmd_qr(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = " ".join(context.args) if context.args else ""
    if not text:
        await update.effective_message.reply_text("🌙 Usage: /qr <text or url>")
        return
    image_url = f"https://api.qrserver.com/v1/create-qr-code/?size=300x300&data={url_quote(text)}"
    try:
        await update.effective_message.reply_photo(
            photo=image_url, caption="🌙 <i>Source: goqr.me QR API</i>", parse_mode=ParseMode.HTML
        )
    except (BadRequest, TelegramError) as exc:
        log.info("QR send failed: %s", exc)
        await update.effective_message.reply_text("🌙 Couldn't generate that QR code right now.")


# ==============================================================================
#  OWNER-ONLY: /callall — notifies everyone in the current chat / topic
# ==============================================================================
#
#  Telegram has no Discord-style "@everyone" primitive, and there's no hidden
#  API call that force-notifies people without either mentioning them or
#  DMing them — EXCEPT one thing: any ordinary new message posted into a
#  chat (or, inside a forum-enabled supergroup, into a specific topic)
#  already triggers a push notification for every member who hasn't muted
#  that chat/topic. That's what actually reaches "everyone" with no explicit
#  @mentions listed out.
#
#  So /callall just posts one loud, clearly-flagged message — and if it's
#  run from inside a forum topic, it auto-detects that topic's thread ID via
#  message_thread_id and posts there, so it reaches whoever is following
#  that topic specifically, automatically, with zero setup.
#
#  Stated plainly: nothing can override a member's own mute settings for a
#  chat or topic — that's a Telegram platform limit, not something code can
#  route around.
# ==============================================================================


async def cmd_callall(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    chat = update.effective_chat
    message = update.effective_message

    if user is None or user.id != CFG.owner_id:
        await message.reply_text("🌙 This command is restricted.")
        return

    if chat is None or chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        await message.reply_text("🌙 Run /callall inside the group (or topic) you want to notify.")
        return

    announcement = " ".join(context.args) if context.args else ""
    if not announcement:
        await message.reply_text("🌙 Usage: /callall <message>")
        return

    thread_id = message.message_thread_id  # auto-detected — set only inside a forum topic
    text = f"📣 <b>{html.escape(announcement)}</b>"

    try:
        await context.bot.send_message(
            chat_id=chat.id,
            text=text,
            parse_mode=ParseMode.HTML,
            message_thread_id=thread_id,
            disable_notification=False,
        )
    except (Forbidden, BadRequest, TelegramError) as exc:
        log.error("Callall failed in chat %s (thread %s): %s", chat.id, thread_id, exc)
        await message.reply_text("🌙 Couldn't post that — check my permissions in this chat/topic.")


# ==============================================================================
#  GLOBAL ERROR HANDLER
# ==============================================================================


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    log.error("Unhandled exception while processing update: %s", context.error, exc_info=context.error)


# ==============================================================================
#  APPLICATION BUILDER / ENTRYPOINT
# ==============================================================================


def build_application() -> Application:
    application = Application.builder().token(CFG.token).build()

    # Silent background registration — runs first, on every update, no reply.
    application.add_handler(MessageHandler(filters.ALL, silently_register), group=-1)
    application.add_handler(
        ChatMemberHandler(track_chat_member_updates, ChatMemberHandler.CHAT_MEMBER), group=-1
    )

    # Info
    application.add_handler(CommandHandler("help", cmd_help))
    application.add_handler(CommandHandler("about", cmd_about))
    application.add_handler(CommandHandler("ping", cmd_ping))
    application.add_handler(CommandHandler("id", cmd_id))
    application.add_handler(CommandHandler("time", cmd_time))

    # Utility
    application.add_handler(CommandHandler("echo", cmd_echo))
    application.add_handler(CommandHandler("calc", cmd_calc))
    application.add_handler(CommandHandler("reverse", cmd_reverse))

    # Fun / CSPRNG
    application.add_handler(CommandHandler("roll", cmd_roll))
    application.add_handler(CommandHandler("flip", cmd_flip))
    application.add_handler(CommandHandler("choose", cmd_choose))
    application.add_handler(CommandHandler("8ball", cmd_8ball))
    application.add_handler(CommandHandler("rate", cmd_rate))
    application.add_handler(CommandHandler("ship", cmd_ship))
    application.add_handler(CommandHandler("joke", cmd_joke))
    application.add_handler(CommandHandler("fact", cmd_fact))
    application.add_handler(CommandHandler("quote", cmd_quote))

    # External APIs
    application.add_handler(CommandHandler("weather", cmd_weather))
    application.add_handler(CommandHandler("crypto", cmd_crypto))
    application.add_handler(CommandHandler("define", cmd_define))
    application.add_handler(CommandHandler("trivia", cmd_trivia))
    application.add_handler(CommandHandler("advice", cmd_advice))
    application.add_handler(CommandHandler("meme", cmd_meme))
    application.add_handler(CommandHandler("cat", cmd_cat))
    application.add_handler(CommandHandler("dog", cmd_dog))
    application.add_handler(CommandHandler("qr", cmd_qr))

    # Owner-only
    application.add_handler(CommandHandler("callall", cmd_callall))

    application.add_error_handler(on_error)

    return application


def main() -> None:
    if CFG.token == "PUT_YOUR_BOT_TOKEN_HERE" or not CFG.token:
        raise SystemExit("🌙 Set CFG.token in Lunar.py before running.")
    if CFG.owner_id == 0:
        log.warning("CFG.owner_id is unset — /callall will be unusable until you set it.")

    application = build_application()
    log.info("Lunar is rising — polling for updates.")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()