#!/usr/bin/env python3
# ==============================================================================
#  Sapphire  —  Group moderation bot, part of the Lunar family 
#  Developer : @TheSlopKing
# ==============================================================================
#
#  Moderation only — no fun/game/API-toy commands live here. That's          #  Lunar.py's job. Sapphire is a standalone bot: separate token, separate      #  process, separate data file. Run both side by side if you want, they.      #  never touch each other's state.
#
#  Requirements:
#      pip install "python-telegram-bot[job-queue]"
#
#  Run:
#      python3 sapphire.py
#
#   ==============================================================================

from __future__ import annotations

import copy
import functools
import html
import io
import json
import logging
import os
import re
import secrets
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from datetime import time as dt_time
from pathlib import Path
from typing import Any

from telegram import (
    ChatMember,
    ChatMemberUpdated,
    ChatPermissions,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
    User,
)
from telegram.constants import ChatType, ParseMode
from telegram.error import BadRequest, Forbidden, TelegramError
from telegram.ext import (
    Application,
    CallbackQueryHandler,
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
    bot_name: str = "Sapphire"
    data_file: str = "sapphire_data.json"
    version: str = "1.0.0"


CFG = Config()
START_TIME = time.time()

logging.basicConfig(
    format="[%(asctime)s] [%(levelname)s] [Sapphire] %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("Sapphire")


# ==============================================================================
#  CRYPTOGRAPHIC RANDOMIZER  (used only for captcha math generation)
# ==============================================================================


def _crypto_draw(n: int) -> int:
    if n <= 0:
        raise ValueError("n must be a positive integer.")
    raw = secrets.token_bytes(8)
    return int.from_bytes(raw, "big") % n


def crypto_randbelow(n: int) -> int:
    return _crypto_draw(n)


def crypto_shuffle_order(seq: list[Any]) -> list[Any]:
    pool = list(seq)
    for i in range(len(pool) - 1, 0, -1):
        j = crypto_randbelow(i + 1)
        pool[i], pool[j] = pool[j], pool[i]
    return pool


# ==============================================================================
#  PERSISTENCE — one JSON file, one in-memory dict, a dirty flag + flush job
# ==============================================================================

DEFAULT_SETTINGS: dict[str, Any] = {
    "captcha_enabled": False,
    "captcha_type": "button",          # "button" or "math"
    "captcha_timeout": 180,            # seconds
    "antispam_enabled": False,
    "antiflood_enabled": False,
    "flood_limit": 6,
    "flood_window": 10,                # seconds
    "flood_action": "mute",            # mute | kick | ban
    "nightmode_enabled": False,
    "night_start_hour": 23,            # UTC
    "night_end_hour": 7,               # UTC
    "slowmode_seconds": 0,
    "clean_welcome": False,
    "warn_limit": 3,
    "warn_action": "mute",             # mute | kick | ban
    "antiraid_enabled": False,
}

DEFAULT_CHAT_ENTRY: dict[str, Any] = {
    "title": "",
    "settings": dict(DEFAULT_SETTINGS),
    "welcome": {"enabled": True, "text": ""},
    "goodbye": {"enabled": False, "text": ""},
    "rules": "",
    "filters": {},
    "custom_commands": {},
    "banned_words": [],
    "blacklist_users": [],
    "whitelist_users": [],
    "locks": [],
    "log_chat_id": None,
    "log_thread_id": None,
    "warnings": {},
    "muted_users": {},
    "banned_users": {},
    "stats": {},
    "last_welcome_message_id": None,
    "raid_lockdown_until": 0,
}

DEFAULT_WELCOME_TEXT = "🌙 Welcome to {group}, {mention}!"
DEFAULT_GOODBYE_TEXT = "🌙 {name} has left {group}."

DATA: dict[str, Any] = {"chats": {}, "broadcasts": {}}
_DIRTY = False


def load_data() -> None:
    global DATA
    path = Path(CFG.data_file)
    if not path.exists():
        return
    try:
        DATA = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        log.warning("Data file unreadable (%s) — starting fresh.", exc)
        DATA = {"chats": {}, "broadcasts": {}}
    DATA.setdefault("chats", {})
    DATA.setdefault("broadcasts", {})


def save_data() -> None:
    global _DIRTY
    path = Path(CFG.data_file)
    tmp_path = path.with_suffix(".tmp")
    try:
        tmp_path.write_text(json.dumps(DATA, indent=2), encoding="utf-8")
        os.replace(tmp_path, path)
        _DIRTY = False
    except OSError as exc:
        log.error("Failed to persist data: %s", exc)


def mark_dirty() -> None:
    global _DIRTY
    _DIRTY = True


async def periodic_flush(context: ContextTypes.DEFAULT_TYPE) -> None:
    if _DIRTY:
        save_data()


def get_chat_entry(chat_id: int, title: str | None) -> dict:
    key = str(chat_id)
    chats = DATA.setdefault("chats", {})
    entry = chats.get(key)
    if entry is None:
        entry = copy.deepcopy(DEFAULT_CHAT_ENTRY)
        chats[key] = entry
        mark_dirty()
    for top_key, default_val in DEFAULT_CHAT_ENTRY.items():
        if top_key not in entry:
            entry[top_key] = copy.deepcopy(default_val)
    for set_key, set_val in DEFAULT_SETTINGS.items():
        entry["settings"].setdefault(set_key, set_val)
    if title and entry.get("title") != title:
        entry["title"] = title
    return entry


# ==============================================================================
#  PERMISSIONS — admins are real Telegram chat admins (plus a global owner)
# ==============================================================================

_ADMIN_CACHE: dict[int, tuple[float, set[int]]] = {}
_ADMIN_CACHE_TTL = 300  # seconds


async def get_admin_ids(context: ContextTypes.DEFAULT_TYPE, chat_id: int) -> set[int]:
    cached = _ADMIN_CACHE.get(chat_id)
    now = time.time()
    if cached and now - cached[0] < _ADMIN_CACHE_TTL:
        return cached[1]
    try:
        admins = await context.bot.get_chat_administrators(chat_id)
        ids = {a.user.id for a in admins}
    except TelegramError:
        ids = cached[1] if cached else set()
    _ADMIN_CACHE[chat_id] = (now, ids)
    return ids


async def is_privileged(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user = update.effective_user
    chat = update.effective_chat
    if user is None or chat is None:
        return False
    if user.id == CFG.owner_id:
        return True
    admin_ids = await get_admin_ids(context, chat.id)
    return user.id in admin_ids


def admin_only(handler):
    @functools.wraps(handler)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat = update.effective_chat
        if chat is None or chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
            await update.effective_message.reply_text("🌙 This only works inside a group.")
            return
        if not await is_privileged(update, context):
            await update.effective_message.reply_text("🌙 Admins only.")
            return
        return await handler(update, context)
    return wrapper


# ==============================================================================
#  SHARED HELPERS — target resolution, durations, punishments, logging
# ==============================================================================

_DURATION_RE = re.compile(r"(\d+)([smhdw])")
_UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}


def parse_duration(text: str) -> timedelta | None:
    matches = _DURATION_RE.findall(text.lower())
    if not matches:
        return None
    total = sum(int(n) * _UNIT_SECONDS[u] for n, u in matches)
    return timedelta(seconds=total) if total > 0 else None


async def resolve_target(update: Update, context: ContextTypes.DEFAULT_TYPE) -> tuple[int, str] | None:
    message = update.effective_message
    if message.reply_to_message and message.reply_to_message.from_user:
        u = message.reply_to_message.from_user
        return u.id, u.first_name or u.username or str(u.id)
    if context.args:
        token = context.args[0]
        try:
            uid = int(token)
            return uid, str(uid)
        except ValueError:
            pass
        username = token.lstrip("@")
        try:
            chat = await context.bot.get_chat(f"@{username}")
            return chat.id, chat.first_name or chat.username or str(chat.id)
        except TelegramError:
            return None
    return None


MUTED_PERMISSIONS = ChatPermissions(
    can_send_messages=False,
    can_send_audios=False,
    can_send_documents=False,
    can_send_photos=False,
    can_send_videos=False,
    can_send_video_notes=False,
    can_send_voice_notes=False,
    can_send_polls=False,
    can_send_other_messages=False,
    can_add_web_page_previews=False,
    can_change_info=False,
    can_invite_users=False,
    can_pin_messages=False,
)


async def _default_permissions(context: ContextTypes.DEFAULT_TYPE, chat_id: int) -> ChatPermissions:
    try:
        chat = await context.bot.get_chat(chat_id)
        if chat.permissions:
            return chat.permissions
    except TelegramError:
        pass
    return ChatPermissions(can_send_messages=True, can_send_polls=True, can_send_other_messages=True,
                            can_add_web_page_previews=True, can_invite_users=True)


async def apply_punishment(
    context: ContextTypes.DEFAULT_TYPE, chat_id: int, user_id: int, action: str, duration: timedelta | None = None
) -> bool:
    try:
        if action == "mute":
            until = datetime.now(timezone.utc) + duration if duration else None
            await context.bot.restrict_chat_member(chat_id, user_id, permissions=MUTED_PERMISSIONS, until_date=until)
        elif action == "kick":
            await context.bot.ban_chat_member(chat_id, user_id)
            await context.bot.unban_chat_member(chat_id, user_id, only_if_banned=True)
        elif action == "ban":
            until = datetime.now(timezone.utc) + duration if duration else None
            await context.bot.ban_chat_member(chat_id, user_id, until_date=until)
        else:
            return False
        return True
    except TelegramError as exc:
        log.info("Punishment '%s' failed for %s in %s: %s", action, user_id, chat_id, exc)
        return False


async def log_action(context: ContextTypes.DEFAULT_TYPE, chat_id: int, text: str) -> None:
    entry = get_chat_entry(chat_id, None)
    log_id = entry.get("log_chat_id")
    if not log_id:
        return
    try:
        await context.bot.send_message(
            chat_id=log_id, text=text, message_thread_id=entry.get("log_thread_id"), parse_mode=ParseMode.HTML
        )
    except TelegramError:
        pass


def fill_placeholders(template: str, user: User, chat) -> str:
    return (
        template
        .replace("{name}", html.escape(user.first_name or user.username or str(user.id)))
        .replace("{mention}", user.mention_html())
        .replace("{group}", html.escape(chat.title) if chat and chat.title else "")
        .replace("{id}", str(user.id))
    )


async def safe_delete(context: ContextTypes.DEFAULT_TYPE, chat_id: int, message_id: int) -> None:
    try:
        await context.bot.delete_message(chat_id, message_id)
    except TelegramError:
        pass


# ==============================================================================
#  MODERATION PIPELINE — one pass over every non-command group message
# ==============================================================================

VALID_LOCK_TYPES = {"media", "links", "stickers", "gifs", "voice", "polls", "forwards"}

_FLOOD_TRACKER: dict[tuple[int, int], deque] = defaultdict(deque)
_SPAM_TRACKER: dict[tuple[int, int], deque] = defaultdict(lambda: deque(maxlen=4))
_LAST_MESSAGE_TIME: dict[tuple[int, int], float] = {}


def check_locks(message, locks: list[str]) -> str | None:
    if not locks:
        return None
    if "media" in locks and (message.photo or message.video or message.document or message.animation):
        return "media"
    if "stickers" in locks and message.sticker:
        return "stickers"
    if "gifs" in locks and message.animation:
        return "gifs"
    if "voice" in locks and (message.voice or message.video_note):
        return "voice"
    if "polls" in locks and message.poll:
        return "polls"
    if "forwards" in locks and (
        getattr(message, "forward_origin", None)
        or getattr(message, "forward_from", None)
        or getattr(message, "forward_from_chat", None)
    ):
        return "forwards"
    if "links" in locks and message.text:
        if message.entities and any(e.type in ("url", "text_link", "mention") for e in message.entities):
            return "links"
        if re.search(r"https?://|t\.me/|www\.", message.text, re.IGNORECASE):
            return "links"
    return None


def in_night_window(settings: dict) -> bool:
    start, end = settings.get("night_start_hour", 23), settings.get("night_end_hour", 7)
    if start == end:
        return False
    hour = datetime.now(timezone.utc).hour
    if start < end:
        return start <= hour < end
    return hour >= start or hour < end


def register_flood_hit(chat_id: int, user_id: int, settings: dict) -> bool:
    window, limit = settings.get("flood_window", 10), settings.get("flood_limit", 6)
    key = (chat_id, user_id)
    now = time.time()
    dq = _FLOOD_TRACKER[key]
    dq.append(now)
    while dq and now - dq[0] > window:
        dq.popleft()
    return len(dq) > limit


def register_spam_hit(chat_id: int, user_id: int, text: str) -> bool:
    key = (chat_id, user_id)
    dq = _SPAM_TRACKER[key]
    dq.append(text.strip().lower())
    return len(dq) >= 3 and len(set(list(dq)[-3:])) == 1


def check_banned_words(text: str, words: list[str]) -> str | None:
    lowered = text.lower()
    for w in words:
        if w and w.lower() in lowered:
            return w
    return None


def match_filter(text: str, filters_map: dict[str, str]) -> str | None:
    lowered = text.lower().strip()
    for trigger, response in filters_map.items():
        if trigger.lower() in lowered:
            return response
    return None


def bump_stats(entry: dict, user: User) -> None:
    stats = entry.setdefault("stats", {})
    key = str(user.id)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    record = stats.setdefault(key, {"total": 0, "name": user.first_name or user.username or key, "daily": {}})
    record["total"] += 1
    record["name"] = user.first_name or user.username or key
    daily = record.setdefault("daily", {})
    daily[today] = daily.get(today, 0) + 1
    if len(daily) > 7:
        for old_day in sorted(daily.keys())[:-7]:
            del daily[old_day]
    mark_dirty()


async def issue_warn(update: Update, context: ContextTypes.DEFAULT_TYPE, entry: dict, user: User, reason: str) -> None:
    chat_id = update.effective_chat.id
    warnings = entry.setdefault("warnings", {})
    key = str(user.id)
    warnings[key] = warnings.get(key, 0) + 1
    count = warnings[key]
    limit = entry["settings"].get("warn_limit", 3)
    if count >= limit:
        action = entry["settings"].get("warn_action", "mute")
        await apply_punishment(context, chat_id, user.id, action)
        if action == "mute":
            entry.setdefault("muted_users", {})[key] = None
        elif action == "ban":
            entry.setdefault("banned_users", {})[key] = reason
        warnings[key] = 0
        await log_action(context, chat_id, f"⚠️ {user.mention_html()} hit the warning limit ({limit}) — {action} applied.")
        try:
            await update.effective_message.reply_text(f"🌙 {user.first_name or user.id} hit {limit} warnings — {action} applied.")
        except TelegramError:
            pass
    else:
        try:
            await update.effective_message.reply_text(
                f"🌙 ⚠️ Warned {user.first_name or user.id} ({count}/{limit}) — {reason}"
            )
        except TelegramError:
            pass
    save_data()


async def moderate_incoming(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    chat = update.effective_chat
    user = update.effective_user
    if message is None or chat is None or user is None:
        return
    if chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        return

    entry = get_chat_entry(chat.id, chat.title)
    settings = entry["settings"]

    if user.id == CFG.owner_id:
        bump_stats(entry, user)
        return

    admin_ids = await get_admin_ids(context, chat.id)
    if user.id in admin_ids or user.id in entry.get("whitelist_users", []):
        bump_stats(entry, user)
        return

    if user.id in entry.get("blacklist_users", []):
        await safe_delete(context, chat.id, message.message_id)
        if await apply_punishment(context, chat.id, user.id, "ban"):
            await log_action(context, chat.id, f"🚫 Auto-banned blacklisted user {user.mention_html()}.")
        return

    if settings.get("nightmode_enabled") and in_night_window(settings):
        await safe_delete(context, chat.id, message.message_id)
        return

    limit = settings.get("slowmode_seconds", 0)
    if limit:
        key = (chat.id, user.id)
        last = _LAST_MESSAGE_TIME.get(key, 0)
        now = time.time()
        if now - last < limit:
            await safe_delete(context, chat.id, message.message_id)
            return
        _LAST_MESSAGE_TIME[key] = now

    lock_hit = check_locks(message, entry.get("locks", []))
    if lock_hit:
        await safe_delete(context, chat.id, message.message_id)
        await log_action(context, chat.id, f"🔒 Deleted a {lock_hit} message from {user.mention_html()} (locked).")
        return

    if settings.get("antiflood_enabled") and register_flood_hit(chat.id, user.id, settings):
        action = settings.get("flood_action", "mute")
        await safe_delete(context, chat.id, message.message_id)
        if await apply_punishment(context, chat.id, user.id, action):
            key = str(user.id)
            if action == "mute":
                entry.setdefault("muted_users", {})[key] = None
            elif action == "ban":
                entry.setdefault("banned_users", {})[key] = "flood"
            save_data()
            await log_action(context, chat.id, f"🌊 Flood detected — {action} applied to {user.mention_html()}.")
        return

    if settings.get("antispam_enabled") and message.text and register_spam_hit(chat.id, user.id, message.text):
        await safe_delete(context, chat.id, message.message_id)
        await issue_warn(update, context, entry, user, reason="Spam detected")
        return

    if message.text:
        hit_word = check_banned_words(message.text, entry.get("banned_words", []))
        if hit_word:
            await safe_delete(context, chat.id, message.message_id)
            await log_action(context, chat.id, f"🧹 Deleted a message from {user.mention_html()} (banned word).")
            return

    if message.text:
        response = match_filter(message.text, entry.get("filters", {}))
        if response:
            try:
                await message.reply_text(response)
            except TelegramError:
                pass

    bump_stats(entry, user)


# ==============================================================================
#  JOIN / LEAVE — captcha, welcome, goodbye, anti-raid, blacklist auto-ban
# ==============================================================================

_PENDING_CAPTCHA: dict[tuple[int, int], dict] = {}
CAPTCHA_TIMEOUT_DEFAULT = 180


async def greet_new_member(context: ContextTypes.DEFAULT_TYPE, chat, entry: dict, user: User) -> None:
    settings = entry["settings"]

    if time.time() < entry.get("raid_lockdown_until", 0):
        if await apply_punishment(context, chat.id, user.id, "kick"):
            await log_action(context, chat.id, f"🛑 Raid lockdown active — removed {user.mention_html()} on join.")
        return

    captcha_needed = settings.get("captcha_enabled") or settings.get("antiraid_enabled")

    if captcha_needed:
        try:
            await context.bot.restrict_chat_member(chat.id, user.id, permissions=MUTED_PERMISSIONS)
        except TelegramError as exc:
            log.info("Could not restrict %s in %s for captcha: %s", user.id, chat.id, exc)

        captcha_type = settings.get("captcha_type", "button")
        if captcha_type == "math":
            a, b = crypto_randbelow(9) + 1, crypto_randbelow(9) + 1
            answer = a + b
            wrong_options: set[int] = set()
            while len(wrong_options) < 3:
                candidate = answer + crypto_randbelow(7) - 3
                if candidate != answer and candidate > 0:
                    wrong_options.add(candidate)
            option_values = crypto_shuffle_order([answer, *wrong_options])
            buttons = [InlineKeyboardButton(str(v), callback_data=f"captcha:{chat.id}:{user.id}:{v}") for v in option_values]
            rows = [buttons[i:i + 2] for i in range(0, len(buttons), 2)]
            prompt = f"🌙 Welcome, {user.mention_html()}! What is {a} + {b}?"
        else:
            answer = 1
            rows = [[InlineKeyboardButton("✅ I'm human — verify me", callback_data=f"captcha:{chat.id}:{user.id}:1")]]
            prompt = f"🌙 Welcome, {user.mention_html()}! Tap below to verify you're human."

        try:
            sent = await context.bot.send_message(
                chat.id, prompt, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(rows)
            )
        except TelegramError as exc:
            log.info("Could not send captcha prompt in %s: %s", chat.id, exc)
            return

        job = None
        if context.job_queue:
            timeout = settings.get("captcha_timeout", CAPTCHA_TIMEOUT_DEFAULT)
            job = context.job_queue.run_once(
                captcha_timeout_job, when=timeout,
                data={"chat_id": chat.id, "user_id": user.id, "message_id": sent.message_id},
            )
        _PENDING_CAPTCHA[(chat.id, user.id)] = {"answer": answer, "message_id": sent.message_id, "job": job}
        return

    await send_welcome(context, chat, entry, user)


async def send_welcome(context: ContextTypes.DEFAULT_TYPE, chat, entry: dict, user: User) -> None:
    welcome = entry.get("welcome", {})
    if not welcome.get("enabled", True):
        return
    template = welcome.get("text") or DEFAULT_WELCOME_TEXT
    text = fill_placeholders(template, user, chat)
    try:
        sent = await context.bot.send_message(chat.id, text, parse_mode=ParseMode.HTML)
    except TelegramError:
        return
    if entry["settings"].get("clean_welcome"):
        last_id = entry.get("last_welcome_message_id")
        if last_id:
            await safe_delete(context, chat.id, last_id)
        entry["last_welcome_message_id"] = sent.message_id
        mark_dirty()


async def captcha_timeout_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    data = context.job.data
    chat_id, user_id, message_id = data["chat_id"], data["user_id"], data["message_id"]
    if (chat_id, user_id) not in _PENDING_CAPTCHA:
        return
    del _PENDING_CAPTCHA[(chat_id, user_id)]
    await apply_punishment(context, chat_id, user_id, "kick")
    try:
        await context.bot.edit_message_text(chat_id=chat_id, message_id=message_id, text="🌙 Captcha expired — user removed.")
    except TelegramError:
        pass
    await log_action(context, chat_id, f"⏳ Captcha timed out for user {user_id} — removed.")


async def captcha_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    _, chat_id_s, user_id_s, value_s = query.data.split(":")
    chat_id, target_user_id = int(chat_id_s), int(user_id_s)

    if query.from_user.id != target_user_id:
        await query.answer("🌙 This captcha isn't for you.", show_alert=True)
        return

    pending = _PENDING_CAPTCHA.get((chat_id, target_user_id))
    if not pending:
        await query.answer("🌙 This captcha already expired.", show_alert=True)
        return
    if str(pending["answer"]) != value_s:
        await query.answer("🌙 Incorrect — try again.", show_alert=True)
        return

    if pending.get("job"):
        pending["job"].schedule_removal()
    del _PENDING_CAPTCHA[(chat_id, target_user_id)]

    entry = get_chat_entry(chat_id, None)
    try:
        chat = await context.bot.get_chat(chat_id)
    except TelegramError:
        chat = None
    perms = (chat.permissions if chat and chat.permissions else None) or ChatPermissions(
        can_send_messages=True, can_send_polls=True, can_send_other_messages=True,
        can_add_web_page_previews=True, can_invite_users=True,
    )
    try:
        await context.bot.restrict_chat_member(chat_id, target_user_id, permissions=perms)
    except TelegramError as exc:
        log.info("Could not lift captcha restriction for %s in %s: %s", target_user_id, chat_id, exc)

    await query.answer("🌙 Verified! Welcome.")
    try:
        await query.edit_message_text(f"✅ {query.from_user.mention_html()} verified successfully.", parse_mode=ParseMode.HTML)
    except TelegramError:
        pass
    if chat:
        await send_welcome(context, chat, entry, query.from_user)


async def farewell_member(context: ContextTypes.DEFAULT_TYPE, chat, entry: dict, user: User) -> None:
    goodbye = entry.get("goodbye", {})
    if not goodbye.get("enabled", False):
        return
    template = goodbye.get("text") or DEFAULT_GOODBYE_TEXT
    text = fill_placeholders(template, user, chat)
    try:
        await context.bot.send_message(chat.id, text, parse_mode=ParseMode.HTML)
    except TelegramError:
        pass


async def track_membership(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    result: ChatMemberUpdated | None = update.chat_member
    if result is None:
        return
    chat = result.chat
    if chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        return

    entry = get_chat_entry(chat.id, chat.title)
    old_status, new_status = result.old_chat_member.status, result.new_chat_member.status
    member_user = result.new_chat_member.user
    if member_user.is_bot:
        return

    joined = old_status in (ChatMember.LEFT, ChatMember.BANNED) and new_status in (ChatMember.MEMBER, ChatMember.RESTRICTED)
    left = new_status in (ChatMember.LEFT, ChatMember.BANNED) and old_status not in (ChatMember.LEFT, ChatMember.BANNED)

    if joined:
        if member_user.id in entry.get("blacklist_users", []):
            if await apply_punishment(context, chat.id, member_user.id, "ban"):
                await log_action(context, chat.id, f"🚫 Auto-banned blacklisted user {member_user.mention_html()} on join.")
            return
        await greet_new_member(context, chat, entry, member_user)
    elif left:
        await farewell_member(context, chat, entry, member_user)


# ==============================================================================
#  COMMANDS — Info & utility
# ==============================================================================

HELP_TEXT = (
    "🌙 <b>Sapphire — Moderation Command Directory</b>\n\n"
    "<b>Info</b>\n"
    "/help /about /ping /version /uptime /id /info /userinfo /admins\n\n"
    "<b>Punishments</b> (reply or give @user/ID)\n"
    "/ban /unban /kick /mute /unmute /tban /tmute /unmuteall\n"
    "/warn /unwarn /warnings /resetwarns /warnlist /setwarnlimit /warnaction\n\n"
    "<b>Message moderation</b>\n"
    "/purge /del /pin /unpin /report\n\n"
    "<b>Admin management</b>\n"
    "/promote /demote\n\n"
    "<b>Protection settings</b>\n"
    "/settings /captcha /setcaptchatype /setcaptchatimeout\n"
    "/antispam /antiflood /setfloodlimit /setfloodaction\n"
    "/nightmode /setnighttime /antiraid /raidmode /slowmode /slowmodeoff\n\n"
    "<b>Locks</b>\n"
    "/lock /unlock /locks /lockdown /unlockall /antilink\n\n"
    "<b>Welcome / Goodbye / Rules</b>\n"
    "/welcome /setwelcome /resetwelcome /cleanwelcome\n"
    "/goodbye /setgoodbye /resetgoodbye\n"
    "/rules /setrules /resetrules\n\n"
    "<b>Filters, words &amp; custom commands</b>\n"
    "/filters /addfilter /removefilter /stopallfilters\n"
    "/badwords /addbadword /removebadword /clearbadwords\n"
    "/commands /addcommand /removecommand\n\n"
    "<b>Blacklist / Approve</b>\n"
    "/blacklist /blacklistadd /blacklistremove\n"
    "/approve /unapprove /approved\n\n"
    "<b>Logging</b>\n"
    "/setlog /unsetlog /logstatus /logtest\n\n"
    "<b>Stats</b>\n"
    "/stats /trend /graphic /top10 /myactivity /resetstats\n\n"
    "<b>Broadcasts</b>\n"
    "/broadcast /schedule /scheduled /cancelschedule\n\n"
    "<b>Backup</b>\n"
    "/exportsettings /importsettings /resetsettings /mutelist /banlist\n\n"
    f"🌙 <i>{CFG.bot_name} — built by {CFG.developer_handle} — {CFG.website}</i>"
)


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(HELP_TEXT, parse_mode=ParseMode.HTML)


async def cmd_about(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(
        f"🌙 <b>{CFG.bot_name}</b>\nGroup moderation &amp; protection bot.\n\n"
        f"Developer: {CFG.developer_handle}\nWebsite: {CFG.website}\nVersion: {CFG.version}",
        parse_mode=ParseMode.HTML,
    )


async def cmd_ping(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    start = time.perf_counter()
    sent = await update.effective_message.reply_text("🌙 Pinging…")
    elapsed_ms = (time.perf_counter() - start) * 1000
    await sent.edit_text(f"🌙 Pong — {elapsed_ms:.0f} ms")


async def cmd_version(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(f"🌙 {CFG.bot_name} v{CFG.version}")


async def cmd_uptime(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    elapsed = int(time.time() - START_TIME)
    d, rem = divmod(elapsed, 86400)
    h, rem = divmod(rem, 3600)
    m, s = divmod(rem, 60)
    await update.effective_message.reply_text(f"🌙 Uptime: {d}d {h}h {m}m {s}s")


async def cmd_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(
        f"🌙 User ID: <code>{update.effective_user.id}</code>\nChat ID: <code>{update.effective_chat.id}</code>",
        parse_mode=ParseMode.HTML,
    )


async def cmd_info(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat = update.effective_chat
    entry = get_chat_entry(chat.id, chat.title)
    settings = entry["settings"]
    try:
        member_count = await context.bot.get_chat_member_count(chat.id)
    except TelegramError:
        member_count = "unknown"
    await update.effective_message.reply_text(
        f"🌙 <b>{html.escape(chat.title or 'this chat')}</b>\n"
        f"ID: <code>{chat.id}</code>\nMembers: {member_count}\n"
        f"Captcha: {'on' if settings['captcha_enabled'] else 'off'} | "
        f"Anti-flood: {'on' if settings['antiflood_enabled'] else 'off'} | "
        f"Night mode: {'on' if settings['nightmode_enabled'] else 'off'}",
        parse_mode=ParseMode.HTML,
    )


async def cmd_userinfo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    target = await resolve_target(update, context)
    if not target:
        u = update.effective_user
        target = (u.id, u.first_name or u.username or str(u.id))
    uid, name = target
    entry = get_chat_entry(update.effective_chat.id, update.effective_chat.title)
    warnings = entry.get("warnings", {}).get(str(uid), 0)
    await update.effective_message.reply_text(
        f"🌙 <b>{html.escape(name)}</b>\nID: <code>{uid}</code>\nWarnings: {warnings}", parse_mode=ParseMode.HTML
    )


async def cmd_admins(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        admins = await context.bot.get_chat_administrators(update.effective_chat.id)
        lines = [f"• {html.escape(a.user.first_name or a.user.username or str(a.user.id))}" for a in admins]
    except TelegramError:
        lines = ["🌙 Couldn't fetch the admin list right now."]
    await update.effective_message.reply_text("🌙 <b>Admins</b>\n" + "\n".join(lines), parse_mode=ParseMode.HTML)


# ==============================================================================
#  COMMANDS — Punishments & warnings
# ==============================================================================


@admin_only
async def cmd_ban(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    target = await resolve_target(update, context)
    if not target:
        await update.effective_message.reply_text("🌙 Reply to a user or give their ID/@username.")
        return
    uid, name = target
    chat_id = update.effective_chat.id
    if await apply_punishment(context, chat_id, uid, "ban"):
        entry = get_chat_entry(chat_id, update.effective_chat.title)
        entry.setdefault("banned_users", {})[str(uid)] = "manual"
        save_data()
        await update.effective_message.reply_text(f"🌙 Banned {name}.")
        await log_action(context, chat_id, f"⛔ Banned {html.escape(name)} ({uid}).")
    else:
        await update.effective_message.reply_text("🌙 Couldn't ban that user — check my permissions.")


@admin_only
async def cmd_unban(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    target = await resolve_target(update, context)
    if not target:
        await update.effective_message.reply_text("🌙 Give the user's ID/@username to unban.")
        return
    uid, name = target
    chat_id = update.effective_chat.id
    try:
        await context.bot.unban_chat_member(chat_id, uid, only_if_banned=True)
        entry = get_chat_entry(chat_id, update.effective_chat.title)
        entry.get("banned_users", {}).pop(str(uid), None)
        save_data()
        await update.effective_message.reply_text(f"🌙 Unbanned {name}.")
        await log_action(context, chat_id, f"✅ Unbanned {html.escape(name)} ({uid}).")
    except TelegramError as exc:
        await update.effective_message.reply_text(f"🌙 Couldn't unban: {exc}")


@admin_only
async def cmd_kick(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    target = await resolve_target(update, context)
    if not target:
        await update.effective_message.reply_text("🌙 Reply to a user or give their ID/@username.")
        return
    uid, name = target
    chat_id = update.effective_chat.id
    if await apply_punishment(context, chat_id, uid, "kick"):
        await update.effective_message.reply_text(f"🌙 Kicked {name}.")
        await log_action(context, chat_id, f"👢 Kicked {html.escape(name)} ({uid}).")
    else:
        await update.effective_message.reply_text("🌙 Couldn't kick that user — check my permissions.")


@admin_only
async def cmd_mute(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    target = await resolve_target(update, context)
    if not target:
        await update.effective_message.reply_text("🌙 Reply to a user or give their ID/@username.")
        return
    uid, name = target
    chat_id = update.effective_chat.id
    if await apply_punishment(context, chat_id, uid, "mute"):
        entry = get_chat_entry(chat_id, update.effective_chat.title)
        entry.setdefault("muted_users", {})[str(uid)] = None
        save_data()
        await update.effective_message.reply_text(f"🌙 Muted {name}.")
        await log_action(context, chat_id, f"🔇 Muted {html.escape(name)} ({uid}).")
    else:
        await update.effective_message.reply_text("🌙 Couldn't mute that user — check my permissions.")


@admin_only
async def cmd_unmute(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    target = await resolve_target(update, context)
    if not target:
        await update.effective_message.reply_text("🌙 Reply to a user or give their ID/@username.")
        return
    uid, name = target
    chat_id = update.effective_chat.id
    perms = await _default_permissions(context, chat_id)
    try:
        await context.bot.restrict_chat_member(chat_id, uid, permissions=perms)
        entry = get_chat_entry(chat_id, update.effective_chat.title)
        entry.get("muted_users", {}).pop(str(uid), None)
        save_data()
        await update.effective_message.reply_text(f"🌙 Unmuted {name}.")
        await log_action(context, chat_id, f"🔈 Unmuted {html.escape(name)} ({uid}).")
    except TelegramError as exc:
        await update.effective_message.reply_text(f"🌙 Couldn't unmute: {exc}")


@admin_only
async def cmd_unmuteall(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    entry = get_chat_entry(chat_id, update.effective_chat.title)
    muted = entry.get("muted_users", {})
    perms = await _default_permissions(context, chat_id)
    count = 0
    for uid_str in list(muted.keys()):
        try:
            await context.bot.restrict_chat_member(chat_id, int(uid_str), permissions=perms)
            count += 1
        except TelegramError:
            pass
        muted.pop(uid_str, None)
    save_data()
    await update.effective_message.reply_text(f"🌙 Unmuted {count} user(s).")


@admin_only
async def cmd_tban(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    target = await resolve_target(update, context)
    if not target or not context.args:
        await update.effective_message.reply_text("🌙 Usage: /tban <user> <duration>  e.g. /tban @user 1d")
        return
    uid, name = target
    duration = parse_duration(context.args[-1])
    if not duration:
        await update.effective_message.reply_text("🌙 Bad duration — try formats like 30m, 2h, 1d.")
        return
    chat_id = update.effective_chat.id
    if await apply_punishment(context, chat_id, uid, "ban", duration=duration):
        entry = get_chat_entry(chat_id, update.effective_chat.title)
        entry.setdefault("banned_users", {})[str(uid)] = f"temp until {(datetime.now(timezone.utc) + duration).isoformat()}"
        save_data()
        await update.effective_message.reply_text(f"🌙 Temp-banned {name} for {context.args[-1]}.")
        await log_action(context, chat_id, f"⛔ Temp-banned {html.escape(name)} ({uid}) for {context.args[-1]}.")
    else:
        await update.effective_message.reply_text("🌙 Couldn't temp-ban that user — check my permissions.")


@admin_only
async def cmd_tmute(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    target = await resolve_target(update, context)
    if not target or not context.args:
        await update.effective_message.reply_text("🌙 Usage: /tmute <user> <duration>  e.g. /tmute @user 30m")
        return
    uid, name = target
    duration = parse_duration(context.args[-1])
    if not duration:
        await update.effective_message.reply_text("🌙 Bad duration — try formats like 30m, 2h, 1d.")
        return
    chat_id = update.effective_chat.id
    if await apply_punishment(context, chat_id, uid, "mute", duration=duration):
        entry = get_chat_entry(chat_id, update.effective_chat.title)
        entry.setdefault("muted_users", {})[str(uid)] = (datetime.now(timezone.utc) + duration).isoformat()
        save_data()
        await update.effective_message.reply_text(f"🌙 Temp-muted {name} for {context.args[-1]}.")
        await log_action(context, chat_id, f"🔇 Temp-muted {html.escape(name)} ({uid}) for {context.args[-1]}.")
    else:
        await update.effective_message.reply_text("🌙 Couldn't temp-mute that user — check my permissions.")


@admin_only
async def cmd_warn(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    target = await resolve_target(update, context)
    if not target:
        await update.effective_message.reply_text("🌙 Reply to a user or give their ID/@username.")
        return
    uid, name = target
    reason = " ".join(context.args[1:]) if len(context.args) > 1 else "No reason given"
    entry = get_chat_entry(update.effective_chat.id, update.effective_chat.title)
    fake_user = User(id=uid, first_name=name, is_bot=False)
    await issue_warn(update, context, entry, fake_user, reason)


@admin_only
async def cmd_unwarn(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    target = await resolve_target(update, context)
    if not target:
        await update.effective_message.reply_text("🌙 Reply to a user or give their ID/@username.")
        return
    uid, name = target
    entry = get_chat_entry(update.effective_chat.id, update.effective_chat.title)
    warnings = entry.setdefault("warnings", {})
    key = str(uid)
    warnings[key] = max(0, warnings.get(key, 0) - 1)
    save_data()
    await update.effective_message.reply_text(f"🌙 {name} now has {warnings[key]} warning(s).")


@admin_only
async def cmd_warnings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    target = await resolve_target(update, context)
    if not target:
        u = update.effective_user
        target = (u.id, u.first_name or str(u.id))
    uid, name = target
    entry = get_chat_entry(update.effective_chat.id, update.effective_chat.title)
    count = entry.get("warnings", {}).get(str(uid), 0)
    await update.effective_message.reply_text(f"🌙 {name}: {count}/{entry['settings'].get('warn_limit', 3)} warnings.")


@admin_only
async def cmd_resetwarns(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    target = await resolve_target(update, context)
    if not target:
        await update.effective_message.reply_text("🌙 Reply to a user or give their ID/@username.")
        return
    uid, name = target
    entry = get_chat_entry(update.effective_chat.id, update.effective_chat.title)
    entry.setdefault("warnings", {})[str(uid)] = 0
    save_data()
    await update.effective_message.reply_text(f"🌙 Reset warnings for {name}.")


@admin_only
async def cmd_warnlist(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    entry = get_chat_entry(update.effective_chat.id, update.effective_chat.title)
    active = {k: v for k, v in entry.get("warnings", {}).items() if v > 0}
    if not active:
        await update.effective_message.reply_text("🌙 No active warnings.")
        return
    lines = [f"{uid}: {count}" for uid, count in active.items()]
    await update.effective_message.reply_text("🌙 <b>Active warnings</b>\n" + "\n".join(lines), parse_mode=ParseMode.HTML)


@admin_only
async def cmd_setwarnlimit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args or not context.args[0].isdigit():
        await update.effective_message.reply_text("🌙 Usage: /setwarnlimit <number>")
        return
    entry = get_chat_entry(update.effective_chat.id, update.effective_chat.title)
    entry["settings"]["warn_limit"] = max(1, int(context.args[0]))
    save_data()
    await update.effective_message.reply_text(f"🌙 Warn limit set to {entry['settings']['warn_limit']}.")


@admin_only
async def cmd_warnaction(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    action = context.args[0].lower() if context.args else ""
    if action not in ("mute", "kick", "ban"):
        await update.effective_message.reply_text("🌙 Usage: /warnaction <mute|kick|ban>")
        return
    entry = get_chat_entry(update.effective_chat.id, update.effective_chat.title)
    entry["settings"]["warn_action"] = action
    save_data()
    await update.effective_message.reply_text(f"🌙 Warn action set to {action}.")


# ==============================================================================
#  COMMANDS — Message moderation & admin management
# ==============================================================================


@admin_only
async def cmd_purge(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if not message.reply_to_message:
        await message.reply_text("🌙 Reply to the message to start purging from.")
        return
    chat_id = update.effective_chat.id
    start_id, end_id = message.reply_to_message.message_id, message.message_id
    deleted = 0
    for mid in range(start_id, end_id + 1):
        try:
            await context.bot.delete_message(chat_id, mid)
            deleted += 1
        except TelegramError:
            continue
    await context.bot.send_message(chat_id, f"🌙 Purged {deleted} message(s).")
    await log_action(context, chat_id, f"🧹 Purged {deleted} message(s).")


@admin_only
async def cmd_del(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if not message.reply_to_message:
        await message.reply_text("🌙 Reply to the message you want deleted.")
        return
    await safe_delete(context, update.effective_chat.id, message.reply_to_message.message_id)
    await safe_delete(context, update.effective_chat.id, message.message_id)


@admin_only
async def cmd_pin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if not message.reply_to_message:
        await message.reply_text("🌙 Reply to the message you want pinned.")
        return
    try:
        await context.bot.pin_chat_message(update.effective_chat.id, message.reply_to_message.message_id)
        await message.reply_text("🌙 Pinned.")
    except TelegramError as exc:
        await message.reply_text(f"🌙 Couldn't pin: {exc}")


@admin_only
async def cmd_unpin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        await context.bot.unpin_chat_message(update.effective_chat.id)
        await update.effective_message.reply_text("🌙 Unpinned.")
    except TelegramError as exc:
        await update.effective_message.reply_text(f"🌙 Couldn't unpin: {exc}")


async def cmd_report(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if not message.reply_to_message:
        await message.reply_text("🌙 Reply to the message you want to report with /report.")
        return
    admin_ids = await get_admin_ids(context, update.effective_chat.id)
    ping = "".join(f'<a href="tg://user?id={i}">​</a>' for i in list(admin_ids)[:10])
    reported = message.reply_to_message.from_user
    try:
        await message.reply_to_message.reply_text(
            f"🚨 Reported by {message.from_user.mention_html()} — admins notified.{ping}", parse_mode=ParseMode.HTML
        )
    except TelegramError:
        pass
    await log_action(
        context, update.effective_chat.id,
        f"🚨 {message.from_user.mention_html()} reported a message from "
        f"{reported.mention_html() if reported else 'unknown'}.",
    )


PROMOTE_PERMISSIONS = dict(
    can_manage_chat=True, can_delete_messages=True, can_manage_video_chats=True,
    can_restrict_members=True, can_promote_members=False, can_change_info=False,
    can_invite_users=True, can_pin_messages=True,
)
DEMOTE_PERMISSIONS = dict(
    can_manage_chat=False, can_delete_messages=False, can_manage_video_chats=False,
    can_restrict_members=False, can_promote_members=False, can_change_info=False,
    can_invite_users=False, can_pin_messages=False,
)


@admin_only
async def cmd_promote(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    target = await resolve_target(update, context)
    if not target:
        await update.effective_message.reply_text("🌙 Reply to a user or give their ID/@username.")
        return
    uid, name = target
    chat_id = update.effective_chat.id
    try:
        await context.bot.promote_chat_member(chat_id, uid, **PROMOTE_PERMISSIONS)
        await update.effective_message.reply_text(f"🌙 Promoted {name}.")
        await log_action(context, chat_id, f"⬆️ Promoted {html.escape(name)} ({uid}).")
    except TelegramError as exc:
        await update.effective_message.reply_text(f"🌙 Couldn't promote: {exc}")


@admin_only
async def cmd_demote(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    target = await resolve_target(update, context)
    if not target:
        await update.effective_message.reply_text("🌙 Reply to a user or give their ID/@username.")
        return
    uid, name = target
    chat_id = update.effective_chat.id
    try:
        await context.bot.promote_chat_member(chat_id, uid, **DEMOTE_PERMISSIONS)
        await update.effective_message.reply_text(f"🌙 Demoted {name}.")
        await log_action(context, chat_id, f"⬇️ Demoted {html.escape(name)} ({uid}).")
    except TelegramError as exc:
        await update.effective_message.reply_text(f"🌙 Couldn't demote: {exc}")


# ==============================================================================
#  COMMANDS — Protection settings
# ==============================================================================


@admin_only
async def cmd_captcha(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    state = context.args[0].lower() if context.args else ""
    if state not in ("on", "off"):
        await update.effective_message.reply_text("🌙 Usage: /captcha <on|off>")
        return
    entry = get_chat_entry(update.effective_chat.id, update.effective_chat.title)
    entry["settings"]["captcha_enabled"] = state == "on"
    save_data()
    await update.effective_message.reply_text(f"🌙 Captcha {state}.")


@admin_only
async def cmd_setcaptchatype(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    kind = context.args[0].lower() if context.args else ""
    if kind not in ("button", "math"):
        await update.effective_message.reply_text("🌙 Usage: /setcaptchatype <button|math>")
        return
    entry = get_chat_entry(update.effective_chat.id, update.effective_chat.title)
    entry["settings"]["captcha_type"] = kind
    save_data()
    await update.effective_message.reply_text(f"🌙 Captcha type set to {kind}.")


@admin_only
async def cmd_setcaptchatimeout(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args or not context.args[0].isdigit():
        await update.effective_message.reply_text("🌙 Usage: /setcaptchatimeout <seconds>")
        return
    entry = get_chat_entry(update.effective_chat.id, update.effective_chat.title)
    entry["settings"]["captcha_timeout"] = max(30, int(context.args[0]))
    save_data()
    await update.effective_message.reply_text(f"🌙 Captcha timeout set to {entry['settings']['captcha_timeout']}s.")


@admin_only
async def cmd_antispam(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    state = context.args[0].lower() if context.args else ""
    if state not in ("on", "off"):
        await update.effective_message.reply_text("🌙 Usage: /antispam <on|off>")
        return
    entry = get_chat_entry(update.effective_chat.id, update.effective_chat.title)
    entry["settings"]["antispam_enabled"] = state == "on"
    save_data()
    await update.effective_message.reply_text(f"🌙 Anti-spam {state}.")


@admin_only
async def cmd_antiflood(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    state = context.args[0].lower() if context.args else ""
    if state not in ("on", "off"):
        await update.effective_message.reply_text("🌙 Usage: /antiflood <on|off>")
        return
    entry = get_chat_entry(update.effective_chat.id, update.effective_chat.title)
    entry["settings"]["antiflood_enabled"] = state == "on"
    save_data()
    await update.effective_message.reply_text(f"🌙 Anti-flood {state}.")


@admin_only
async def cmd_setfloodlimit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args or not context.args[0].isdigit():
        await update.effective_message.reply_text("🌙 Usage: /setfloodlimit <messages>")
        return
    entry = get_chat_entry(update.effective_chat.id, update.effective_chat.title)
    entry["settings"]["flood_limit"] = max(2, int(context.args[0]))
    save_data()
    await update.effective_message.reply_text(f"🌙 Flood limit set to {entry['settings']['flood_limit']}.")


@admin_only
async def cmd_setfloodaction(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    action = context.args[0].lower() if context.args else ""
    if action not in ("mute", "kick", "ban"):
        await update.effective_message.reply_text("🌙 Usage: /setfloodaction <mute|kick|ban>")
        return
    entry = get_chat_entry(update.effective_chat.id, update.effective_chat.title)
    entry["settings"]["flood_action"] = action
    save_data()
    await update.effective_message.reply_text(f"🌙 Flood action set to {action}.")


@admin_only
async def cmd_nightmode(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    state = context.args[0].lower() if context.args else ""
    if state not in ("on", "off"):
        await update.effective_message.reply_text("🌙 Usage: /nightmode <on|off>")
        return
    entry = get_chat_entry(update.effective_chat.id, update.effective_chat.title)
    entry["settings"]["nightmode_enabled"] = state == "on"
    save_data()
    await update.effective_message.reply_text(f"🌙 Night mode {state}.")


@admin_only
async def cmd_setnighttime(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if len(context.args) != 2 or not all(a.isdigit() for a in context.args):
        await update.effective_message.reply_text("🌙 Usage: /setnighttime <start_hour_utc> <end_hour_utc>  e.g. /setnighttime 23 7")
        return
    start_h, end_h = int(context.args[0]), int(context.args[1])
    if not (0 <= start_h <= 23 and 0 <= end_h <= 23):
        await update.effective_message.reply_text("🌙 Hours must be 0-23.")
        return
    entry = get_chat_entry(update.effective_chat.id, update.effective_chat.title)
    entry["settings"]["night_start_hour"] = start_h
    entry["settings"]["night_end_hour"] = end_h
    save_data()
    await update.effective_message.reply_text(f"🌙 Night mode window set to {start_h}:00–{end_h}:00 UTC.")


@admin_only
async def cmd_antiraid(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    state = context.args[0].lower() if context.args else ""
    if state not in ("on", "off"):
        await update.effective_message.reply_text("🌙 Usage: /antiraid <on|off>")
        return
    entry = get_chat_entry(update.effective_chat.id, update.effective_chat.title)
    entry["settings"]["antiraid_enabled"] = state == "on"
    save_data()
    await update.effective_message.reply_text(f"🌙 Anti-raid mode {state}.")


@admin_only
async def cmd_raidmode(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args or not context.args[0].isdigit():
        await update.effective_message.reply_text("🌙 Usage: /raidmode <minutes>")
        return
    minutes = int(context.args[0])
    entry = get_chat_entry(update.effective_chat.id, update.effective_chat.title)
    entry["raid_lockdown_until"] = time.time() + minutes * 60
    save_data()
    await update.effective_message.reply_text(f"🌙 Raid lockdown engaged for {minutes} minute(s) — new joiners will be removed.")
    await log_action(context, update.effective_chat.id, f"🛑 Raid lockdown engaged for {minutes}m by an admin.")


@admin_only
async def cmd_slowmode(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args or not context.args[0].isdigit():
        await update.effective_message.reply_text("🌙 Usage: /slowmode <seconds>")
        return
    entry = get_chat_entry(update.effective_chat.id, update.effective_chat.title)
    entry["settings"]["slowmode_seconds"] = max(0, int(context.args[0]))
    save_data()
    await update.effective_message.reply_text(f"🌙 Slow mode set to {entry['settings']['slowmode_seconds']}s.")


@admin_only
async def cmd_slowmodeoff(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    entry = get_chat_entry(update.effective_chat.id, update.effective_chat.title)
    entry["settings"]["slowmode_seconds"] = 0
    save_data()
    await update.effective_message.reply_text("🌙 Slow mode disabled.")


# ==============================================================================
#  COMMANDS — Locks
# ==============================================================================


@admin_only
async def cmd_lock(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lock_type = context.args[0].lower() if context.args else ""
    if lock_type not in VALID_LOCK_TYPES:
        await update.effective_message.reply_text(f"🌙 Usage: /lock <{'|'.join(sorted(VALID_LOCK_TYPES))}>")
        return
    entry = get_chat_entry(update.effective_chat.id, update.effective_chat.title)
    locks = entry.setdefault("locks", [])
    if lock_type not in locks:
        locks.append(lock_type)
        save_data()
    await update.effective_message.reply_text(f"🌙 Locked: {lock_type}")


@admin_only
async def cmd_unlock(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lock_type = context.args[0].lower() if context.args else ""
    entry = get_chat_entry(update.effective_chat.id, update.effective_chat.title)
    locks = entry.setdefault("locks", [])
    if lock_type in locks:
        locks.remove(lock_type)
        save_data()
    await update.effective_message.reply_text(f"🌙 Unlocked: {lock_type or '(nothing specified)'}")


async def cmd_locks(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    entry = get_chat_entry(update.effective_chat.id, update.effective_chat.title)
    locks = entry.get("locks", [])
    await update.effective_message.reply_text("🌙 Active locks: " + (", ".join(locks) if locks else "none"))


@admin_only
async def cmd_lockdown(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    entry = get_chat_entry(update.effective_chat.id, update.effective_chat.title)
    entry["locks"] = sorted(VALID_LOCK_TYPES)
    save_data()
    await update.effective_message.reply_text("🌙 Lockdown engaged — all trackable content types locked.")


@admin_only
async def cmd_unlockall(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    entry = get_chat_entry(update.effective_chat.id, update.effective_chat.title)
    entry["locks"] = []
    save_data()
    await update.effective_message.reply_text("🌙 All locks cleared.")


@admin_only
async def cmd_antilink(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    entry = get_chat_entry(update.effective_chat.id, update.effective_chat.title)
    locks = entry.setdefault("locks", [])
    if "links" in locks:
        locks.remove("links")
        state = "disabled"
    else:
        locks.append("links")
        state = "enabled"
    save_data()
    await update.effective_message.reply_text(f"🌙 Anti-link {state}.")


# ==============================================================================
#  COMMANDS — Welcome / Goodbye / Rules
# ==============================================================================


async def cmd_welcome(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    entry = get_chat_entry(update.effective_chat.id, update.effective_chat.title)
    welcome = entry.get("welcome", {})
    await update.effective_message.reply_text(
        f"🌙 Welcome messages: {'on' if welcome.get('enabled', True) else 'off'}\n"
        f"Current text:\n{html.escape(welcome.get('text') or DEFAULT_WELCOME_TEXT)}",
        parse_mode=ParseMode.HTML,
    )


@admin_only
async def cmd_setwelcome(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = update.effective_message.text.partition(" ")[2]
    if not text:
        await update.effective_message.reply_text(
            "🌙 Usage: /setwelcome <text>  (placeholders: {name} {mention} {group} {id})"
        )
        return
    entry = get_chat_entry(update.effective_chat.id, update.effective_chat.title)
    entry.setdefault("welcome", {})["text"] = text
    entry["welcome"]["enabled"] = True
    save_data()
    await update.effective_message.reply_text("🌙 Welcome message updated.")


@admin_only
async def cmd_resetwelcome(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    entry = get_chat_entry(update.effective_chat.id, update.effective_chat.title)
    entry["welcome"] = {"enabled": True, "text": ""}
    save_data()
    await update.effective_message.reply_text("🌙 Welcome message reset to default.")


@admin_only
async def cmd_cleanwelcome(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    state = context.args[0].lower() if context.args else ""
    if state not in ("on", "off"):
        await update.effective_message.reply_text("🌙 Usage: /cleanwelcome <on|off>")
        return
    entry = get_chat_entry(update.effective_chat.id, update.effective_chat.title)
    entry["settings"]["clean_welcome"] = state == "on"
    save_data()
    await update.effective_message.reply_text(f"🌙 Clean welcome {state}.")


async def cmd_goodbye(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    entry = get_chat_entry(update.effective_chat.id, update.effective_chat.title)
    goodbye = entry.get("goodbye", {})
    await update.effective_message.reply_text(
        f"🌙 Goodbye messages: {'on' if goodbye.get('enabled', False) else 'off'}\n"
        f"Current text:\n{html.escape(goodbye.get('text') or DEFAULT_GOODBYE_TEXT)}",
        parse_mode=ParseMode.HTML,
    )


@admin_only
async def cmd_setgoodbye(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = update.effective_message.text.partition(" ")[2]
    if not text:
        await update.effective_message.reply_text("🌙 Usage: /setgoodbye <text>  (placeholders: {name} {group} {id})")
        return
    entry = get_chat_entry(update.effective_chat.id, update.effective_chat.title)
    entry.setdefault("goodbye", {})["text"] = text
    entry["goodbye"]["enabled"] = True
    save_data()
    await update.effective_message.reply_text("🌙 Goodbye message updated.")


@admin_only
async def cmd_resetgoodbye(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    entry = get_chat_entry(update.effective_chat.id, update.effective_chat.title)
    entry["goodbye"] = {"enabled": False, "text": ""}
    save_data()
    await update.effective_message.reply_text("🌙 Goodbye message reset to default (and disabled).")


async def cmd_rules(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    entry = get_chat_entry(update.effective_chat.id, update.effective_chat.title)
    rules = entry.get("rules", "")
    await update.effective_message.reply_text(
        "🌙 <b>Rules</b>\n" + (html.escape(rules) if rules else "No rules have been set yet."), parse_mode=ParseMode.HTML
    )


@admin_only
async def cmd_setrules(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = update.effective_message.text.partition(" ")[2]
    if not text:
        await update.effective_message.reply_text("🌙 Usage: /setrules <text>")
        return
    entry = get_chat_entry(update.effective_chat.id, update.effective_chat.title)
    entry["rules"] = text
    save_data()
    await update.effective_message.reply_text("🌙 Rules updated.")


@admin_only
async def cmd_resetrules(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    entry = get_chat_entry(update.effective_chat.id, update.effective_chat.title)
    entry["rules"] = ""
    save_data()
    await update.effective_message.reply_text("🌙 Rules cleared.")


# ==============================================================================
#  COMMANDS — Filters, banned words, custom commands
# ==============================================================================


@admin_only
async def cmd_filters(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    entry = get_chat_entry(update.effective_chat.id, update.effective_chat.title)
    filters_map = entry.get("filters", {})
    if not filters_map:
        await update.effective_message.reply_text("🌙 No filters set.")
        return
    lines = [f"• {html.escape(k)}" for k in filters_map]
    await update.effective_message.reply_text("🌙 <b>Filters</b>\n" + "\n".join(lines), parse_mode=ParseMode.HTML)


@admin_only
async def cmd_addfilter(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if len(context.args) < 2:
        await update.effective_message.reply_text("🌙 Usage: /addfilter <trigger> <response>")
        return
    trigger = context.args[0].lower()
    response = " ".join(context.args[1:])
    entry = get_chat_entry(update.effective_chat.id, update.effective_chat.title)
    entry.setdefault("filters", {})[trigger] = response
    save_data()
    await update.effective_message.reply_text(f"🌙 Filter added: {trigger}")


@admin_only
async def cmd_removefilter(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.effective_message.reply_text("🌙 Usage: /removefilter <trigger>")
        return
    trigger = context.args[0].lower()
    entry = get_chat_entry(update.effective_chat.id, update.effective_chat.title)
    if entry.get("filters", {}).pop(trigger, None) is not None:
        save_data()
        await update.effective_message.reply_text(f"🌙 Filter removed: {trigger}")
    else:
        await update.effective_message.reply_text("🌙 No such filter.")


@admin_only
async def cmd_stopallfilters(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    entry = get_chat_entry(update.effective_chat.id, update.effective_chat.title)
    entry["filters"] = {}
    save_data()
    await update.effective_message.reply_text("🌙 All filters cleared.")


@admin_only
async def cmd_badwords(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    entry = get_chat_entry(update.effective_chat.id, update.effective_chat.title)
    words = entry.get("banned_words", [])
    await update.effective_message.reply_text("🌙 Banned words: " + (", ".join(words) if words else "none"))


@admin_only
async def cmd_addbadword(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.effective_message.reply_text("🌙 Usage: /addbadword <word>")
        return
    word = " ".join(context.args).lower()
    entry = get_chat_entry(update.effective_chat.id, update.effective_chat.title)
    words = entry.setdefault("banned_words", [])
    if word not in words:
        words.append(word)
        save_data()
    await update.effective_message.reply_text(f"🌙 Banned word added: {word}")


@admin_only
async def cmd_removebadword(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.effective_message.reply_text("🌙 Usage: /removebadword <word>")
        return
    word = " ".join(context.args).lower()
    entry = get_chat_entry(update.effective_chat.id, update.effective_chat.title)
    words = entry.setdefault("banned_words", [])
    if word in words:
        words.remove(word)
        save_data()
        await update.effective_message.reply_text(f"🌙 Removed: {word}")
    else:
        await update.effective_message.reply_text("🌙 That word wasn't on the list.")


@admin_only
async def cmd_clearbadwords(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    entry = get_chat_entry(update.effective_chat.id, update.effective_chat.title)
    entry["banned_words"] = []
    save_data()
    await update.effective_message.reply_text("🌙 Banned word list cleared.")


RESERVED_COMMAND_NAMES = {
    "help", "about", "ping", "version", "uptime", "id", "info", "userinfo", "admins",
    "ban", "unban", "kick", "mute", "unmute", "tban", "tmute", "unmuteall",
    "warn", "unwarn", "warnings", "resetwarns", "warnlist", "setwarnlimit", "warnaction",
    "purge", "del", "pin", "unpin", "report", "promote", "demote",
    "settings", "captcha", "setcaptchatype", "setcaptchatimeout", "antispam", "antiflood",
    "setfloodlimit", "setfloodaction", "nightmode", "setnighttime", "antiraid", "raidmode",
    "slowmode", "slowmodeoff", "lock", "unlock", "locks", "lockdown", "unlockall", "antilink",
    "welcome", "setwelcome", "resetwelcome", "cleanwelcome", "goodbye", "setgoodbye",
    "resetgoodbye", "rules", "setrules", "resetrules", "filters", "addfilter", "removefilter",
    "stopallfilters", "badwords", "addbadword", "removebadword", "clearbadwords",
    "commands", "addcommand", "removecommand", "blacklist", "blacklistadd", "blacklistremove",
    "approve", "unapprove", "approved", "setlog", "unsetlog", "logstatus", "logtest",
    "stats", "trend", "graphic", "top10", "myactivity", "resetstats",
    "broadcast", "schedule", "scheduled", "cancelschedule",
    "exportsettings", "importsettings", "resetsettings", "mutelist", "banlist",
}


@admin_only
async def cmd_commands(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    entry = get_chat_entry(update.effective_chat.id, update.effective_chat.title)
    custom = entry.get("custom_commands", {})
    if not custom:
        await update.effective_message.reply_text("🌙 No custom commands set.")
        return
    lines = [f"• /{html.escape(k)}" for k in custom]
    await update.effective_message.reply_text("🌙 <b>Custom commands</b>\n" + "\n".join(lines), parse_mode=ParseMode.HTML)


@admin_only
async def cmd_addcommand(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if len(context.args) < 2:
        await update.effective_message.reply_text("🌙 Usage: /addcommand <name> <response>")
        return
    name = context.args[0].lower().lstrip("/")
    if name in RESERVED_COMMAND_NAMES:
        await update.effective_message.reply_text("🌙 That name is already a built-in command.")
        return
    response = " ".join(context.args[1:])
    entry = get_chat_entry(update.effective_chat.id, update.effective_chat.title)
    entry.setdefault("custom_commands", {})[name] = response
    save_data()
    await update.effective_message.reply_text(f"🌙 Custom command added: /{name}")


@admin_only
async def cmd_removecommand(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.effective_message.reply_text("🌙 Usage: /removecommand <name>")
        return
    name = context.args[0].lower().lstrip("/")
    entry = get_chat_entry(update.effective_chat.id, update.effective_chat.title)
    if entry.get("custom_commands", {}).pop(name, None) is not None:
        save_data()
        await update.effective_message.reply_text(f"🌙 Removed: /{name}")
    else:
        await update.effective_message.reply_text("🌙 No such custom command.")


async def custom_command_dispatch(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    chat = update.effective_chat
    if not message or not message.text or chat is None or chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        return
    command_name = message.text.split()[0][1:].split("@")[0].lower()
    if command_name in RESERVED_COMMAND_NAMES:
        return
    entry = get_chat_entry(chat.id, chat.title)
    response = entry.get("custom_commands", {}).get(command_name)
    if response:
        try:
            await message.reply_text(response)
        except TelegramError:
            pass


# ==============================================================================
#  COMMANDS — Blacklist / Approve
# ==============================================================================


@admin_only
async def cmd_blacklist(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    entry = get_chat_entry(update.effective_chat.id, update.effective_chat.title)
    ids = entry.get("blacklist_users", [])
    await update.effective_message.reply_text("🌙 Blacklisted: " + (", ".join(str(i) for i in ids) if ids else "none"))


@admin_only
async def cmd_blacklistadd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    target = await resolve_target(update, context)
    if not target:
        await update.effective_message.reply_text("🌙 Reply to a user or give their ID/@username.")
        return
    uid, name = target
    entry = get_chat_entry(update.effective_chat.id, update.effective_chat.title)
    ids = entry.setdefault("blacklist_users", [])
    if uid not in ids:
        ids.append(uid)
        save_data()
    await update.effective_message.reply_text(f"🌙 Blacklisted {name}.")


@admin_only
async def cmd_blacklistremove(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    target = await resolve_target(update, context)
    if not target:
        await update.effective_message.reply_text("🌙 Reply to a user or give their ID/@username.")
        return
    uid, name = target
    entry = get_chat_entry(update.effective_chat.id, update.effective_chat.title)
    ids = entry.setdefault("blacklist_users", [])
    if uid in ids:
        ids.remove(uid)
        save_data()
    await update.effective_message.reply_text(f"🌙 Removed {name} from the blacklist.")


@admin_only
async def cmd_approve(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    target = await resolve_target(update, context)
    if not target:
        await update.effective_message.reply_text("🌙 Reply to a user or give their ID/@username.")
        return
    uid, name = target
    entry = get_chat_entry(update.effective_chat.id, update.effective_chat.title)
    ids = entry.setdefault("whitelist_users", [])
    if uid not in ids:
        ids.append(uid)
        save_data()
    await update.effective_message.reply_text(f"🌙 Approved {name} — exempt from filters, locks, and flood/spam checks.")


@admin_only
async def cmd_unapprove(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    target = await resolve_target(update, context)
    if not target:
        await update.effective_message.reply_text("🌙 Reply to a user or give their ID/@username.")
        return
    uid, name = target
    entry = get_chat_entry(update.effective_chat.id, update.effective_chat.title)
    ids = entry.setdefault("whitelist_users", [])
    if uid in ids:
        ids.remove(uid)
        save_data()
    await update.effective_message.reply_text(f"🌙 Unapproved {name}.")


@admin_only
async def cmd_approved(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    entry = get_chat_entry(update.effective_chat.id, update.effective_chat.title)
    ids = entry.get("whitelist_users", [])
    await update.effective_message.reply_text("🌙 Approved: " + (", ".join(str(i) for i in ids) if ids else "none"))


# ==============================================================================
#  COMMANDS — Logging
# ==============================================================================


@admin_only
async def cmd_setlog(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat = update.effective_chat
    message = update.effective_message
    entry = get_chat_entry(chat.id, chat.title)
    entry["log_chat_id"] = chat.id
    entry["log_thread_id"] = message.message_thread_id
    save_data()
    await message.reply_text("🌙 This chat (and topic, if any) is now the moderation log destination.")


@admin_only
async def cmd_unsetlog(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    entry = get_chat_entry(update.effective_chat.id, update.effective_chat.title)
    entry["log_chat_id"] = None
    entry["log_thread_id"] = None
    save_data()
    await update.effective_message.reply_text("🌙 Logging disabled.")


async def cmd_logstatus(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    entry = get_chat_entry(update.effective_chat.id, update.effective_chat.title)
    log_id = entry.get("log_chat_id")
    await update.effective_message.reply_text(f"🌙 Logging: {'configured' if log_id else 'not set'}")


@admin_only
async def cmd_logtest(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    entry = get_chat_entry(update.effective_chat.id, update.effective_chat.title)
    if not entry.get("log_chat_id"):
        await update.effective_message.reply_text("🌙 No log destination set — use /setlog first.")
        return
    await log_action(context, update.effective_chat.id, "🌙 This is a test log entry from /logtest.")
    await update.effective_message.reply_text("🌙 Test entry sent.")


# ==============================================================================
#  COMMANDS — Stats
# ==============================================================================


async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    entry = get_chat_entry(update.effective_chat.id, update.effective_chat.title)
    stats = entry.get("stats", {})
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    today_total = sum(r.get("daily", {}).get(today, 0) for r in stats.values())
    all_total = sum(r.get("total", 0) for r in stats.values())
    await update.effective_message.reply_text(
        f"🌙 <b>Chat stats</b>\nTracked users: {len(stats)}\nMessages today: {today_total}\nMessages total: {all_total}",
        parse_mode=ParseMode.HTML,
    )


async def cmd_trend(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    entry = get_chat_entry(update.effective_chat.id, update.effective_chat.title)
    totals: dict[str, int] = {}
    for record in entry.get("stats", {}).values():
        for day, count in record.get("daily", {}).items():
            totals[day] = totals.get(day, 0) + count
    if not totals:
        await update.effective_message.reply_text("🌙 Not enough activity data yet.")
        return
    lines = [f"{day}: {count}" for day, count in sorted(totals.items())]
    await update.effective_message.reply_text("🌙 <b>7-day trend</b>\n" + "\n".join(lines), parse_mode=ParseMode.HTML)


async def cmd_graphic(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    entry = get_chat_entry(update.effective_chat.id, update.effective_chat.title)
    ranked = sorted(entry.get("stats", {}).values(), key=lambda r: r.get("total", 0), reverse=True)[:10]
    if not ranked:
        await update.effective_message.reply_text("🌙 Not enough activity data yet.")
        return
    max_total = max(r.get("total", 0) for r in ranked) or 1
    lines = []
    for r in ranked:
        bar_len = max(1, round((r.get("total", 0) / max_total) * 20))
        lines.append(f"{r.get('name', '?')[:15]:<15} {'█' * bar_len} {r.get('total', 0)}")
    await update.effective_message.reply_text(
        "🌙 <b>Activity graphic</b>\n<code>" + "\n".join(lines) + "</code>", parse_mode=ParseMode.HTML
    )


async def cmd_top10(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    entry = get_chat_entry(update.effective_chat.id, update.effective_chat.title)
    ranked = sorted(entry.get("stats", {}).values(), key=lambda r: r.get("total", 0), reverse=True)[:10]
    if not ranked:
        await update.effective_message.reply_text("🌙 Not enough activity data yet.")
        return
    lines = [f"{i + 1}. {r.get('name', '?')} — {r.get('total', 0)} messages" for i, r in enumerate(ranked)]
    await update.effective_message.reply_text("🌙 <b>Top 10 most active</b>\n" + "\n".join(lines), parse_mode=ParseMode.HTML)


async def cmd_myactivity(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    entry = get_chat_entry(update.effective_chat.id, update.effective_chat.title)
    record = entry.get("stats", {}).get(str(update.effective_user.id))
    if not record:
        await update.effective_message.reply_text("🌙 No activity recorded for you yet.")
        return
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    await update.effective_message.reply_text(
        f"🌙 Your activity — today: {record.get('daily', {}).get(today, 0)} | total: {record.get('total', 0)}"
    )


@admin_only
async def cmd_resetstats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    entry = get_chat_entry(update.effective_chat.id, update.effective_chat.title)
    entry["stats"] = {}
    save_data()
    await update.effective_message.reply_text("🌙 Stats reset.")


# ==============================================================================
#  COMMANDS — Broadcasts & scheduling
# ==============================================================================


@admin_only
async def cmd_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = update.effective_message.text.partition(" ")[2]
    if not text:
        await update.effective_message.reply_text("🌙 Usage: /broadcast <message>")
        return
    thread_id = update.effective_message.message_thread_id
    try:
        await context.bot.send_message(
            chat_id=update.effective_chat.id, text=f"📣 <b>{html.escape(text)}</b>",
            parse_mode=ParseMode.HTML, message_thread_id=thread_id,
        )
    except TelegramError as exc:
        await update.effective_message.reply_text(f"🌙 Couldn't post that: {exc}")


def _register_schedule(chat_id: int, mode: str, spec: str, text: str) -> str:
    broadcasts = DATA.setdefault("broadcasts", {})
    job_id = f"sched_{chat_id}_{int(time.time() * 1000)}_{secrets.token_hex(3)}"
    broadcasts[job_id] = {"chat_id": chat_id, "mode": mode, "spec": spec, "text": text}
    save_data()
    return job_id


async def scheduled_broadcast_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    data = context.job.data
    try:
        await context.bot.send_message(chat_id=data["chat_id"], text=f"📣 {data['text']}")
    except TelegramError as exc:
        log.info("Scheduled broadcast failed: %s", exc)
    job_id = context.job.name
    if job_id and DATA.get("broadcasts", {}).get(job_id, {}).get("mode") == "once":
        DATA["broadcasts"].pop(job_id, None)
        save_data()


@admin_only
async def cmd_schedule(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.job_queue:
        await update.effective_message.reply_text('🌙 Scheduling needs the job-queue extra: pip install "python-telegram-bot[job-queue]"')
        return
    args = context.args
    if len(args) < 3 or args[0].lower() not in ("once", "daily"):
        await update.effective_message.reply_text(
            "🌙 Usage:\n/schedule once <duration> <message>  e.g. /schedule once 2h Meeting soon!\n"
            "/schedule daily <HH:MM> <message>  e.g. /schedule daily 09:00 Good morning!"
        )
        return
    mode = args[0].lower()
    chat_id = update.effective_chat.id
    text = " ".join(args[2:])

    if mode == "once":
        duration = parse_duration(args[1])
        if not duration:
            await update.effective_message.reply_text("🌙 Bad duration — try formats like 30m, 2h, 1d.")
            return
        run_at = datetime.now(timezone.utc) + duration
        job_id = _register_schedule(chat_id, "once", run_at.isoformat(), text)
        context.job_queue.run_once(scheduled_broadcast_job, when=duration, data={"chat_id": chat_id, "text": text}, name=job_id)
        await update.effective_message.reply_text(f"🌙 Scheduled ({job_id}) for {run_at.strftime('%Y-%m-%d %H:%M UTC')}.")
    else:
        try:
            hh, mm = map(int, args[1].split(":"))
            target_time = dt_time(hour=hh, minute=mm, tzinfo=timezone.utc)
        except ValueError:
            await update.effective_message.reply_text("🌙 Bad time — use HH:MM (24h, UTC).")
            return
        job_id = _register_schedule(chat_id, "daily", args[1], text)
        context.job_queue.run_daily(scheduled_broadcast_job, time=target_time, data={"chat_id": chat_id, "text": text}, name=job_id)
        await update.effective_message.reply_text(f"🌙 Scheduled ({job_id}) daily at {args[1]} UTC.")


@admin_only
async def cmd_scheduled(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    entries = {k: v for k, v in DATA.get("broadcasts", {}).items() if v["chat_id"] == chat_id}
    if not entries:
        await update.effective_message.reply_text("🌙 Nothing scheduled for this chat.")
        return
    lines = [f"• {job_id} ({info['mode']} @ {info['spec']}): {info['text'][:40]}" for job_id, info in entries.items()]
    await update.effective_message.reply_text("🌙 <b>Scheduled broadcasts</b>\n" + "\n".join(lines), parse_mode=ParseMode.HTML)


@admin_only
async def cmd_cancelschedule(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.effective_message.reply_text("🌙 Usage: /cancelschedule <id>  (see /scheduled)")
        return
    job_id = context.args[0]
    if job_id not in DATA.get("broadcasts", {}):
        await update.effective_message.reply_text("🌙 No such scheduled broadcast.")
        return
    DATA["broadcasts"].pop(job_id, None)
    save_data()
    if context.job_queue:
        for job in context.job_queue.get_jobs_by_name(job_id):
            job.schedule_removal()
    await update.effective_message.reply_text(f"🌙 Cancelled {job_id}.")


def register_persisted_jobs(application: Application) -> None:
    if not application.job_queue:
        log.warning('Job queue unavailable — install "python-telegram-bot[job-queue]" for scheduled broadcasts.')
        return
    now = datetime.now(timezone.utc)
    for job_id, info in list(DATA.get("broadcasts", {}).items()):
        chat_id, mode, text = info["chat_id"], info["mode"], info["text"]
        if mode == "daily":
            hh, mm = map(int, info["spec"].split(":"))
            application.job_queue.run_daily(
                scheduled_broadcast_job, time=dt_time(hour=hh, minute=mm, tzinfo=timezone.utc),
                data={"chat_id": chat_id, "text": text}, name=job_id,
            )
        elif mode == "once":
            run_at = datetime.fromisoformat(info["spec"])
            if run_at <= now:
                DATA["broadcasts"].pop(job_id, None)
                continue
            application.job_queue.run_once(scheduled_broadcast_job, when=run_at, data={"chat_id": chat_id, "text": text}, name=job_id)
    save_data()


# ==============================================================================
#  COMMANDS — Backup / config management
# ==============================================================================


@admin_only
async def cmd_exportsettings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat = update.effective_chat
    entry = get_chat_entry(chat.id, chat.title)
    export = {k: v for k, v in entry.items() if k != "stats"}
    payload = json.dumps(export, indent=2).encode("utf-8")
    buffer = io.BytesIO(payload)
    buffer.name = f"sapphire_settings_{chat.id}.json"
    await update.effective_message.reply_document(document=buffer, filename=buffer.name, caption="🌙 Current configuration export.")


@admin_only
async def cmd_importsettings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    target_msg = message.reply_to_message
    if not target_msg or not target_msg.document:
        await message.reply_text("🌙 Reply to an exported settings .json file with /importsettings.")
        return
    try:
        file = await target_msg.document.get_file()
        raw = await file.download_as_bytearray()
        payload = json.loads(bytes(raw).decode("utf-8"))
    except (TelegramError, json.JSONDecodeError, UnicodeDecodeError):
        await message.reply_text("🌙 That file isn't valid settings JSON.")
        return
    chat = update.effective_chat
    entry = get_chat_entry(chat.id, chat.title)
    for key in ("settings", "welcome", "goodbye", "rules", "filters", "custom_commands",
                "banned_words", "blacklist_users", "whitelist_users", "locks",
                "log_chat_id", "log_thread_id"):
        if key in payload:
            entry[key] = payload[key]
    save_data()
    await message.reply_text("🌙 Settings imported successfully.")


@admin_only
async def cmd_resetsettings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat = update.effective_chat
    key = str(chat.id)
    stats = DATA["chats"].get(key, {}).get("stats", {})
    fresh = copy.deepcopy(DEFAULT_CHAT_ENTRY)
    fresh["title"] = chat.title or ""
    fresh["stats"] = stats
    DATA["chats"][key] = fresh
    save_data()
    await update.effective_message.reply_text("🌙 This chat's configuration has been reset to defaults.")


@admin_only
async def cmd_mutelist(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    entry = get_chat_entry(update.effective_chat.id, update.effective_chat.title)
    muted = entry.get("muted_users", {})
    await update.effective_message.reply_text("🌙 Muted: " + (", ".join(muted.keys()) if muted else "none"))


@admin_only
async def cmd_banlist(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    entry = get_chat_entry(update.effective_chat.id, update.effective_chat.title)
    banned = entry.get("banned_users", {})
    await update.effective_message.reply_text("🌙 Banned (by Sapphire): " + (", ".join(banned.keys()) if banned else "none"))


# ==============================================================================
#  INTERACTIVE SETTINGS MENU
# ==============================================================================


def _build_settings_keyboard(entry: dict, page: str) -> InlineKeyboardMarkup:
    settings = entry["settings"]
    mark = lambda flag: "✅" if flag else "❌"  # noqa: E731

    if page == "protection":
        rows = [
            [InlineKeyboardButton(f"Captcha {mark(settings.get('captcha_enabled'))}", callback_data="settings:toggle:captcha_enabled")],
            [InlineKeyboardButton(f"Anti-spam {mark(settings.get('antispam_enabled'))}", callback_data="settings:toggle:antispam_enabled")],
            [InlineKeyboardButton(f"Anti-flood {mark(settings.get('antiflood_enabled'))}", callback_data="settings:toggle:antiflood_enabled")],
            [InlineKeyboardButton(f"Night mode {mark(settings.get('nightmode_enabled'))}", callback_data="settings:toggle:nightmode_enabled")],
            [InlineKeyboardButton(f"Anti-raid {mark(settings.get('antiraid_enabled'))}", callback_data="settings:toggle:antiraid_enabled")],
            [InlineKeyboardButton("⬅️ Back", callback_data="settings:page:main")],
        ]
    elif page == "welcome":
        welcome_on = entry.get("welcome", {}).get("enabled", True)
        goodbye_on = entry.get("goodbye", {}).get("enabled", False)
        rows = [
            [InlineKeyboardButton(f"Welcome {'✅' if welcome_on else '❌'}", callback_data="settings:toggle:welcome_enabled")],
            [InlineKeyboardButton(f"Goodbye {'✅' if goodbye_on else '❌'}", callback_data="settings:toggle:goodbye_enabled")],
            [InlineKeyboardButton(f"Clean welcome {mark(settings.get('clean_welcome'))}", callback_data="settings:toggle:clean_welcome")],
            [InlineKeyboardButton("⬅️ Back", callback_data="settings:page:main")],
        ]
    elif page == "logs":
        state = "configured" if entry.get("log_chat_id") else "not set — use /setlog"
        rows = [
            [InlineKeyboardButton(f"Log channel: {state}", callback_data="settings:noop")],
            [InlineKeyboardButton("⬅️ Back", callback_data="settings:page:main")],
        ]
    else:
        rows = [
            [InlineKeyboardButton("🛡️ Protection", callback_data="settings:page:protection")],
            [InlineKeyboardButton("👋 Welcome / Goodbye", callback_data="settings:page:welcome")],
            [InlineKeyboardButton("📋 Logs", callback_data="settings:page:logs")],
            [InlineKeyboardButton("✖️ Close", callback_data="settings:close")],
        ]
    return InlineKeyboardMarkup(rows)


@admin_only
async def cmd_settings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat = update.effective_chat
    entry = get_chat_entry(chat.id, chat.title)
    await update.effective_message.reply_text(
        f"🌙 <b>Sapphire settings — {html.escape(chat.title or '')}</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=_build_settings_keyboard(entry, "main"),
    )


async def settings_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    chat = update.effective_chat
    if not await is_privileged(update, context):
        await query.answer("🌙 Admins only.", show_alert=True)
        return

    entry = get_chat_entry(chat.id, chat.title)
    parts = query.data.split(":")
    action = parts[1]

    if action == "close":
        try:
            await query.message.delete()
        except TelegramError:
            pass
        await query.answer()
        return

    if action == "page":
        try:
            await query.edit_message_reply_markup(reply_markup=_build_settings_keyboard(entry, parts[2]))
        except TelegramError:
            pass
        await query.answer()
        return

    if action == "toggle":
        key = parts[2]
        if key == "welcome_enabled":
            entry.setdefault("welcome", {})["enabled"] = not entry.get("welcome", {}).get("enabled", True)
            page = "welcome"
        elif key == "goodbye_enabled":
            entry.setdefault("goodbye", {})["enabled"] = not entry.get("goodbye", {}).get("enabled", False)
            page = "welcome"
        elif key == "clean_welcome":
            entry["settings"]["clean_welcome"] = not entry["settings"].get("clean_welcome", False)
            page = "welcome"
        else:
            entry["settings"][key] = not entry["settings"].get(key, False)
            page = "protection"
        save_data()
        try:
            await query.edit_message_reply_markup(reply_markup=_build_settings_keyboard(entry, page))
        except TelegramError:
            pass
        await query.answer("🌙 Updated.")
        return

    await query.answer()


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

    # Passive pipeline: moderation checks + stats, then custom-command fallback
    application.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, moderate_incoming), group=1)
    application.add_handler(MessageHandler(filters.COMMAND, custom_command_dispatch), group=2)
    application.add_handler(ChatMemberHandler(track_membership, ChatMemberHandler.CHAT_MEMBER), group=1)

    # Info
    for name, handler in {
        "help": cmd_help, "about": cmd_about, "ping": cmd_ping, "version": cmd_version,
        "uptime": cmd_uptime, "id": cmd_id, "info": cmd_info, "userinfo": cmd_userinfo, "admins": cmd_admins,
    }.items():
        application.add_handler(CommandHandler(name, handler))

    # Punishments & warnings
    for name, handler in {
        "ban": cmd_ban, "unban": cmd_unban, "kick": cmd_kick, "mute": cmd_mute, "unmute": cmd_unmute,
        "unmuteall": cmd_unmuteall, "tban": cmd_tban, "tmute": cmd_tmute,
        "warn": cmd_warn, "unwarn": cmd_unwarn, "warnings": cmd_warnings, "resetwarns": cmd_resetwarns,
        "warnlist": cmd_warnlist, "setwarnlimit": cmd_setwarnlimit, "warnaction": cmd_warnaction,
    }.items():
        application.add_handler(CommandHandler(name, handler))

    # Message moderation & admin management
    for name, handler in {
        "purge": cmd_purge, "del": cmd_del, "pin": cmd_pin, "unpin": cmd_unpin, "report": cmd_report,
        "promote": cmd_promote, "demote": cmd_demote,
    }.items():
        application.add_handler(CommandHandler(name, handler))

    # Protection settings
    for name, handler in {
        "captcha": cmd_captcha, "setcaptchatype": cmd_setcaptchatype, "setcaptchatimeout": cmd_setcaptchatimeout,
        "antispam": cmd_antispam, "antiflood": cmd_antiflood, "setfloodlimit": cmd_setfloodlimit,
        "setfloodaction": cmd_setfloodaction, "nightmode": cmd_nightmode, "setnighttime": cmd_setnighttime,
        "antiraid": cmd_antiraid, "raidmode": cmd_raidmode, "slowmode": cmd_slowmode, "slowmodeoff": cmd_slowmodeoff,
    }.items():
        application.add_handler(CommandHandler(name, handler))

    # Locks
    for name, handler in {
        "lock": cmd_lock, "unlock": cmd_unlock, "locks": cmd_locks, "lockdown": cmd_lockdown,
        "unlockall": cmd_unlockall, "antilink": cmd_antilink,
    }.items():
        application.add_handler(CommandHandler(name, handler))

    # Welcome / Goodbye / Rules
    for name, handler in {
        "welcome": cmd_welcome, "setwelcome": cmd_setwelcome, "resetwelcome": cmd_resetwelcome,
        "cleanwelcome": cmd_cleanwelcome, "goodbye": cmd_goodbye, "setgoodbye": cmd_setgoodbye,
        "resetgoodbye": cmd_resetgoodbye, "rules": cmd_rules, "setrules": cmd_setrules, "resetrules": cmd_resetrules,
    }.items():
        application.add_handler(CommandHandler(name, handler))

    # Filters, banned words, custom commands
    for name, handler in {
        "filters": cmd_filters, "addfilter": cmd_addfilter, "removefilter": cmd_removefilter,
        "stopallfilters": cmd_stopallfilters, "badwords": cmd_badwords, "addbadword": cmd_addbadword,
        "removebadword": cmd_removebadword, "clearbadwords": cmd_clearbadwords,
        "commands": cmd_commands, "addcommand": cmd_addcommand, "removecommand": cmd_removecommand,
    }.items():
        application.add_handler(CommandHandler(name, handler))

    # Blacklist / Approve
    for name, handler in {
        "blacklist": cmd_blacklist, "blacklistadd": cmd_blacklistadd, "blacklistremove": cmd_blacklistremove,
        "approve": cmd_approve, "unapprove": cmd_unapprove, "approved": cmd_approved,
    }.items():
        application.add_handler(CommandHandler(name, handler))

    # Logging
    for name, handler in {
        "setlog": cmd_setlog, "unsetlog": cmd_unsetlog, "logstatus": cmd_logstatus, 