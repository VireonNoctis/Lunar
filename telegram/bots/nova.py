#!/usr/bin/env python3
# ==============================================================================
#  Nova  —  Website XP, leaderboard, account linking & search bridge
#  Part of the Lunar family  — Developer: @TheSlopKing
# ==============================================================================
#
#    Requirements:
#      pip install "python-telegram-bot[job-queue]" httpx pillow
#
#  Run:
#      python3 nova.py
#
# ==============================================================================

from __future__ import annotations

import copy
import html
import io
import json
import logging
import os
import secrets
import string
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx
from PIL import Image, ImageDraw, ImageFont, ImageOps
from telegram import ChatMember, ChatMemberUpdated, Update
from telegram.constants import ChatType, ParseMode
from telegram.error import TelegramError
from telegram.ext import (
    Application,
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
    # --- Telegram side ---
    token: str = "PUT_YOUR_BOT_TOKEN_HERE"
    owner_id: int = 0
    developer_handle: str = "@TheSlopKing"
    website: str = "lunarx.to"
    bot_name: str = "Nova"
    data_file: str = "nova_data.json"

    # --- Lunar API ---
    lunar_api_base: str = "https://api.lunarx.to/api"
    lunar_base: str = "https://lunarx.to"
    lunar_xp_endpoint: str = "https://api.lunarx.to/api/admin/users/give-xp"
    lunar_profile_endpoint: str = "https://api.lunarx.to/api/animes/profile"
    lunar_leaderboard_endpoint: str = "https://api.lunarx.to/api/animes/leaderboard"
    lunar_notification_endpoint: str = "https://api.lunarx.to/api/notification/admin-send"

    # --- Lunar API credentials  ---
    lunar_token: str = "PUT_YOUR_LUNAR_TOKEN_HERE" 
    lunar_bypass_token: str = ""        # optional X-Scraper-Guard-Bypass
    lunar_union_header: str = "lnr"                           

   # --- Optional: where to post level-up announcements (0 = same chat) ---
    level_up_announce_chat_id: int = 0
    xp_log_chat_id: int = 0


CFG = Config()
START_TIME = time.time()

logging.basicConfig(
    format="[%(asctime)s] [%(levelname)s] [Nova] %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("Nova")


# ==============================================================================
#  PERSISTENCE
# ==============================================================================
#
#  account_links[str(telegram_user_id)] = {
#      "lunar_uuid": str | None,
#      "lunar_username": str,
#      "verified": bool,
#      "last_message_time": iso str | None,   # global XP cooldown anchor
#  }
#  pending_links[str(telegram_user_id)] = {"code": str, "lunar_username": str, "expires_at": epoch}
#  first_seen["<chat_id>:<user_id>"] = iso str   # join-bonus anchor
# ==============================================================================

DATA: dict[str, Any] = {"account_links": {}, "pending_links": {}, "first_seen": {}}
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
        DATA = {"account_links": {}, "pending_links": {}, "first_seen": {}}
    DATA.setdefault("account_links", {})
    DATA.setdefault("pending_links", {})
    DATA.setdefault("first_seen", {})


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


def get_account(user_id: int) -> dict | None:
    return DATA["account_links"].get(str(user_id))


def record_first_seen(chat_id: int, user_id: int) -> None:
    key = f"{chat_id}:{user_id}"
    if key not in DATA["first_seen"]:
        DATA["first_seen"][key] = datetime.now(timezone.utc).isoformat()
        mark_dirty()


def get_first_seen(chat_id: int, user_id: int) -> datetime | None:
    raw = DATA["first_seen"].get(f"{chat_id}:{user_id}")
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


# ==============================================================================
#  LUNAR API
# ==============================================================================

_REQUEST_TIMEOUT = httpx.Timeout(15.0, connect=5.0)


def generate_link_code(lunar_username: str) -> str:
    """Same shape as the original GenerateCode.generate_code: NAME-XXXX-XXXX-XXXX-XXXX."""
    if not lunar_username:
        raise ValueError("username cannot be empty")
    chars = string.ascii_uppercase + string.digits
    token = "".join(secrets.choice(chars) for _ in range(24))
    return f"{lunar_username}-{token[0:6]}-{token[6:12]}-{token[12:18]}-{token[18:24]}"


def normalize_code(code: str) -> str:
    return code.strip().upper()


async def send_link_notification(username: str, code: str) -> bool:
    """POST to LUNAR_NOTIFICATION_ENDPOINT — headers/payload match linkaccount.py's send_notification."""
    headers = {
        "Content-Type": "application/json",
        "union": CFG.lunar_union_header,
    }
    if CFG.lunar_bypass_token:
        headers["X-Scraper-Guard-Bypass"] = CFG.lunar_bypass_token
    if CFG.lunar_token:
        headers["Authorization"] = CFG.lunar_token

    payload = {
        "user_identifier": username,
        "type_": "custom",
        "content": f"Please send this back !link-code {code}",
    }

    try:
        async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT) as client:
            resp = await client.post(CFG.lunar_notification_endpoint, json=payload, headers=headers)
        return 200 <= resp.status_code < 300
    except httpx.HTTPError as exc:
        log.warning("Link notification failed for %s: %s", username, exc)
        return False


async def fetch_lunar_profile(lunar_username: str) -> dict | None:
    """GET LUNAR_PROFILE_API?username=... — matches xp.py's get_lunar_profile (public, no auth)."""
    if not lunar_username:
        return None
    url = f"{CFG.lunar_profile_endpoint}?username={quote(lunar_username, safe='')}"
    try:
        async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT) as client:
            resp = await client.get(url, headers={"Accept": "application/json"})
        if resp.status_code != 200:
            return None
        payload = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        log.warning("Lunar profile lookup failed for %s: %s", lunar_username, exc)
        return None

    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        return None

    try:
        level = int(data.get("level", 0))
        xp = int(data.get("xp", 0))
        xp_required = int(data.get("xp_required_for_next_level", 0))
    except (TypeError, ValueError):
        return None

    return {
        "username": data.get("username", lunar_username),
        "lunar_uuid": data.get("user_id"),
        "level": level,
        "xp": xp,
        "required_xp": xp_required,
        "avatar_url": data.get("avatar_url"),
        "title": data.get("title"),
    }


async def grant_lunar_xp(lunar_uuid: str, amount: int) -> dict | None:
    """POST LUNAR_XP_API give-xp — matches xp.py's grant_xp exactly."""
    if amount < 0 or not CFG.lunar_token:
        return None

    headers = {"Authorization": CFG.lunar_token, "Content-Type": "application/json"}
    if CFG.lunar_bypass_token:
        headers["X-Scraper-Guard-Bypass"] = CFG.lunar_bypass_token

    payload = {"user_id": str(lunar_uuid), "xp": int(amount)}

    try:
        async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT) as client:
            resp = await client.post(CFG.lunar_xp_endpoint, json=payload, headers=headers)
        if resp.status_code != 200:
            log.error("XP API failed: %s | %s", resp.status_code, resp.text[:500])
            return None
        data = resp.json()
        return data if isinstance(data, dict) else None
    except (httpx.HTTPError, ValueError) as exc:
        log.exception("XP API request failed: %s", exc)
        return None


_LEADERBOARD_CACHE: dict[str, Any] = {"data": None, "time": 0.0}
_LEADERBOARD_TTL = 60


async def fetch_leaderboard() -> list[dict]:
    """GET LUNAR_LEADERBOARD_URL — matches leaderboard.py's cached fetch."""
    now = time.monotonic()
    if _LEADERBOARD_CACHE["data"] is not None and now - _LEADERBOARD_CACHE["time"] < _LEADERBOARD_TTL:
        return _LEADERBOARD_CACHE["data"]
    try:
        async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT) as client:
            resp = await client.get(CFG.lunar_leaderboard_endpoint, headers={"Accept": "application/json"})
        if resp.status_code != 200:
            return _LEADERBOARD_CACHE["data"] or []
        data = resp.json()
        leaderboard = data.get("leaderboard", []) if isinstance(data, dict) else []
        if not isinstance(leaderboard, list):
            return _LEADERBOARD_CACHE["data"] or []
        leaderboard = leaderboard[:25]
        _LEADERBOARD_CACHE["data"] = leaderboard
        _LEADERBOARD_CACHE["time"] = now
        return leaderboard
    except (httpx.HTTPError, ValueError) as exc:
        log.warning("Leaderboard fetch failed: %s", exc)
        return _LEADERBOARD_CACHE["data"] or []


_SEARCH_CACHE: dict[str, tuple[float, list[dict]]] = {}
_SEARCH_CACHE_TTL = 300


async def search_manga(query: str) -> list[dict]:
    """GET {API_BASE}/manga/search?q=... — matches search.py's search_manga."""
    key = query.strip().lower()
    cached = _SEARCH_CACHE.get(key)
    if cached and time.monotonic() - cached[0] < _SEARCH_CACHE_TTL:
        return cached[1]

    url = f"{CFG.lunar_api_base}/manga/search?q={quote(query)}"
    try:
        async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT) as client:
            resp = await client.get(url, headers={"Accept": "application/json", "User-Agent": "Nova-Bot/1.0"})
        if resp.status_code != 200:
            return []
        data = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        log.warning("Manga search failed for '%s': %s", query, exc)
        return []

    results = data.get("manga", []) if isinstance(data, dict) else []
    if not isinstance(results, list):
        return []
    results = results[:50]
    _SEARCH_CACHE[key] = (time.monotonic(), results)
    return results


# ==============================================================================
#  LEVEL CARD — drawn locally with Pillow; colors lifted from the original
#  level_card.py so it reads as the same design language without depending
#  on that file's remote CDN assets.
# ==============================================================================

CARD_WIDTH, CARD_HEIGHT = 1000, 360
BACKGROUND_TOP = (13, 10, 28)
BACKGROUND_BOTTOM = (9, 16, 31)
CYAN = (6, 182, 212)          # LUNAR_ACCENT in the original
WHITE = (245, 247, 255)
MUTED = (163, 170, 194)
TRACK = (35, 33, 54)

_FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
)


def _load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    path = _FONT_CANDIDATES[0] if bold else _FONT_CANDIDATES[1]
    try:
        return ImageFont.truetype(path, size)
    except OSError:
        try:
            return ImageFont.truetype(_FONT_CANDIDATES[0], size)
        except OSError:
            return ImageFont.load_default()


def _vertical_gradient(width: int, height: int, top: tuple, bottom: tuple) -> Image.Image:
    base = Image.new("RGB", (width, height), top)
    draw = ImageDraw.Draw(base)
    for y in range(height):
        t = y / max(1, height - 1)
        color = tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3))
        draw.line([(0, y), (width, y)], fill=color)
    return base


async def _download_avatar(url: str | None) -> Image.Image | None:
    if not url:
        return None
    try:
        async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT) as client:
            resp = await client.get(url)
        if resp.status_code != 200:
            return None
        return Image.open(io.BytesIO(resp.content)).convert("RGBA")
    except (httpx.HTTPError, OSError):
        return None


def _paste_circular_avatar(base: Image.Image, avatar: Image.Image | None, center: tuple[int, int], radius: int) -> None:
    size = radius * 2
    if avatar is None:
        placeholder = Image.new("RGBA", (size, size), (*CYAN, 255))
        draw = ImageDraw.Draw(placeholder)
        draw.ellipse([0, 0, size, size], fill=(*CYAN, 255))
        avatar = placeholder
    else:
        avatar = ImageOps.fit(avatar, (size, size))

    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse([0, 0, size, size], fill=255)

    base.paste(avatar, (center[0] - radius, center[1] - radius), mask)


async def build_level_card(profile: dict) -> bytes | None:
    try:
        card = _vertical_gradient(CARD_WIDTH, CARD_HEIGHT, BACKGROUND_TOP, BACKGROUND_BOTTOM).convert("RGBA")
        draw = ImageDraw.Draw(card)

        avatar_img = await _download_avatar(profile.get("avatar_url"))
        _paste_circular_avatar(card, avatar_img, center=(150, CARD_HEIGHT // 2), radius=90)
        draw.ellipse([60, 90, 240, 270], outline=(*CYAN, 255), width=4)

        username = str(profile.get("username", "Unknown"))
        level = profile.get("level", 0)
        xp = profile.get("xp", 0)
        required = profile.get("required_xp", 0) or 1
        title = profile.get("title")

        name_font = _load_font(46, bold=True)
        sub_font = _load_font(26)
        badge_font = _load_font(30, bold=True)

        draw.text((300, 60), username, font=name_font, fill=WHITE)
        if title:
            draw.text((300, 118), str(title), font=sub_font, fill=CYAN)

        badge_text = f"LEVEL {level}"
        draw.text((300, 170), badge_text, font=badge_font, fill=CYAN)

        bar_x, bar_y, bar_w, bar_h = 300, 230, 620, 34
        draw.rounded_rectangle([bar_x, bar_y, bar_x + bar_w, bar_y + bar_h], radius=17, fill=TRACK)
        fraction = max(0.0, min(1.0, xp / required)) if required else 0.0
        fill_w = int(bar_w * fraction)
        if fill_w > 0:
            draw.rounded_rectangle([bar_x, bar_y, bar_x + max(fill_w, bar_h), bar_y + bar_h], radius=17, fill=CYAN)

        xp_label = f"{xp} / {required} XP"
        draw.text((bar_x, bar_y + bar_h + 10), xp_label, font=sub_font, fill=MUTED)
        draw.text(
            (CARD_WIDTH - 220, CARD_HEIGHT - 44),
            f"🌙 {CFG.website}", font=sub_font, fill=MUTED,
        )

        buffer = io.BytesIO()
        card.convert("RGB").save(buffer, format="PNG")
        return buffer.getvalue()
    except Exception as exc:  # noqa: BLE001 — card rendering must never crash the command
        log.warning("Level card rendering failed: %s", exc)
        return None


# ==============================================================================
#  WEBSITE XP FORMULA — ported verbatim from cogs/integrations/xp.py
# ==============================================================================

_LAST_SEEN_MESSAGE: dict[int, tuple[int, str]] = {}  # chat_id -> (author_id, text)


def compute_xp_gain(
    content: str,
    previous: tuple[int, str] | None,
    author_id: int,
    last_message_time: datetime | None,
    first_seen: datetime | None,
) -> int:
    now = datetime.now(timezone.utc)
    content_length = len(content)
    chance = secrets.randbelow(10_000) / 100  # 0.00-99.99, matches random.random()*100 range
    penalty = 1.0

    if previous:
        prev_author_id, prev_content = previous
        if content == prev_content:
            penalty -= 0.9
        if prev_content and content.startswith(prev_content):
            penalty -= 0.3
        if author_id == prev_author_id:
            penalty -= 0.1

    if content_length > 1000:
        penalty -= 0.4
    elif content_length > 500:
        penalty -= 0.2

    if last_message_time is None:
        last_message_time = now - timedelta(seconds=10)
    time_since = (now - last_message_time).total_seconds()

    if time_since < 1:
        penalty -= 0.3
    elif time_since < 5:
        penalty -= 0.2
    elif time_since < 10:
        penalty -= 0.1
    elif time_since > 30:
        penalty += 0.1

    if first_seen and (now - first_seen) < timedelta(days=7):
        penalty += 0.2

    if penalty <= 0:
        return 0

    if chance > 75:
        multiplier = 1.50
    elif chance > 50:
        multiplier = 1.25
    else:
        return 0

    amount = int((content_length / 10) * multiplier * penalty)
    return max(0, amount)


async def handle_xp_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    chat = update.effective_chat
    user = update.effective_user
    if message is None or chat is None or user is None or not message.text:
        return
    if chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        return

    account = get_account(user.id)
    if not account or not account.get("verified") or not account.get("lunar_uuid"):
        return

    previous = _LAST_SEEN_MESSAGE.get(chat.id)
    last_message_time = None
    if account.get("last_message_time"):
        try:
            last_message_time = datetime.fromisoformat(account["last_message_time"])
        except ValueError:
            last_message_time = None

    first_seen = get_first_seen(chat.id, user.id)
    amount = compute_xp_gain(message.text, previous, user.id, last_message_time, first_seen)

    _LAST_SEEN_MESSAGE[chat.id] = (user.id, message.text)
    account["last_message_time"] = datetime.now(timezone.utc).isoformat()
    mark_dirty()

    if amount <= 0:
        return

    result = await grant_lunar_xp(account["lunar_uuid"], amount)
    if not result:
        return

    if CFG.xp_log_chat_id:
        try:
            await context.bot.send_message(
                CFG.xp_log_chat_id,
                f"Gave XP to `{account['lunar_uuid']}` aka `{result.get('username', account['lunar_uuid'])}` — +{result.get('xp_granted', amount)} XP",
                parse_mode=ParseMode.HTML,
            )
        except TelegramError:
            pass

    if result.get("leveled_up"):
        target_chat = CFG.level_up_announce_chat_id or chat.id
        try:
            await context.bot.send_message(
                target_chat,
                f"🌙 <b>{html.escape(result.get('username', account.get('lunar_username', 'Someone')))}</b> "
                f"leveled up to <b>Level {result.get('new_level', '?')}</b>!",
                parse_mode=ParseMode.HTML,
            )
        except TelegramError:
            pass


async def track_first_seen(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    result: ChatMemberUpdated | None = update.chat_member
    if result is None:
        return
    chat = result.chat
    if chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        return
    new_status = result.new_chat_member.status
    old_status = result.old_chat_member.status
    if old_status in (ChatMember.LEFT, ChatMember.BANNED) and new_status in (ChatMember.MEMBER, ChatMember.RESTRICTED):
        record_first_seen(chat.id, result.new_chat_member.user.id)


# ==============================================================================
#  COMMANDS — Utility
# ==============================================================================

HELP_TEXT = (
    "🌙 <b>Nova — Command Directory</b>\n\n"
    "<b>Utility</b>\n"
    "/help /about /ping /id /version /uptime\n\n"
    "<b>Lunar account</b>\n"
    "/link &lt;lunar_username&gt; — start linking your lunarx.to account\n"
    "/linkverify &lt;code&gt; — finish linking with the code sent to your Lunar notifications\n"
    "/unlink — unlink your account\n\n"
    "<b>Website XP</b>\n"
    "/level [username] — view a Lunar level card\n"
    "/leaderboard — top Lunar users by XP\n\n"
    "<b>Search</b>\n"
    "/search &lt;query&gt; — search the Lunar manga catalog\n\n"
    f"🌙 <i>{CFG.bot_name} — built by {CFG.developer_handle} — {CFG.website}</i>"
)


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(HELP_TEXT, parse_mode=ParseMode.HTML)


async def cmd_about(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(
        f"🌙 <b>{CFG.bot_name}</b>\nWebsite XP, leaderboard, linking &amp; search bridge for {CFG.website}.\n\n"
        f"Developer: {CFG.developer_handle}\nWebsite: {CFG.website}",
        parse_mode=ParseMode.HTML,
    )


async def cmd_ping(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    start = time.perf_counter()
    sent = await update.effective_message.reply_text("🌙 Pinging…")
    elapsed_ms = (time.perf_counter() - start) * 1000
    await sent.edit_text(f"🌙 Pong — {elapsed_ms:.0f} ms")


async def cmd_version(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(f"🌙 {CFG.bot_name}")


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


# ==============================================================================
#  COMMANDS — Account linking
# ==============================================================================

LINK_CODE_TTL = 600  # seconds, matches LINK_SESSION_TIMEOUT intent


async def cmd_link(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if not context.args:
        await message.reply_text("🌙 Usage: /link <your_lunar_username>")
        return
    username = context.args[0]
    user_id = update.effective_user.id

    existing = get_account(user_id)
    if existing and existing.get("verified"):
        await message.reply_text(
            f"🌙 Already linked to <b>{html.escape(existing.get('lunar_username', username))}</b>. Use /unlink first to relink.",
            parse_mode=ParseMode.HTML,
        )
        return

    profile = await fetch_lunar_profile(username)
    if not profile or not profile.get("lunar_uuid"):
        await message.reply_text(f"🌙 Couldn't find a Lunar account named '{username}'.")
        return

    code = generate_link_code(username)
    sent_ok = await send_link_notification(username, code)
    if not sent_ok:
        await message.reply_text("🌙 Couldn't send the verification code to your Lunar notifications — try again shortly.")
        return

    DATA["pending_links"][str(user_id)] = {
        "code": normalize_code(code),
        "lunar_username": username,
        "expires_at": time.time() + LINK_CODE_TTL,
    }
    save_data()

    await message.reply_text(
        f"🌙 A verification code was sent to your Lunar notifications on {CFG.website}.\n"
        f"Copy it from there and run:\n<code>/linkverify &lt;code&gt;</code>",
        parse_mode=ParseMode.HTML,
    )


async def cmd_linkverify(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if not context.args:
        await message.reply_text("🌙 Usage: /linkverify <code>")
        return
    user_id = update.effective_user.id
    pending = DATA["pending_links"].get(str(user_id))
    if not pending:
        await message.reply_text("🌙 No pending link request — start with /link <username> first.")
        return
    if time.time() > pending["expires_at"]:
        DATA["pending_links"].pop(str(user_id), None)
        save_data()
        await message.reply_text("🌙 That verification code expired — start again with /link <username>.")
        return

    submitted = normalize_code(" ".join(context.args))
    if submitted != pending["code"]:
        await message.reply_text("🌙 That code doesn't match — double check and try again.")
        return

    profile = await fetch_lunar_profile(pending["lunar_username"])
    if not profile or not profile.get("lunar_uuid"):
        await message.reply_text("🌙 Couldn't re-confirm your Lunar profile — try /link again in a moment.")
        return

    DATA["account_links"][str(user_id)] = {
        "lunar_uuid": profile["lunar_uuid"],
        "lunar_username": profile["username"],
        "verified": True,
        "last_message_time": None,
    }
    DATA["pending_links"].pop(str(user_id), None)
    save_data()

    await message.reply_text(
        f"🌙 Linked! Welcome, <b>{html.escape(profile['username'])}</b>.", parse_mode=ParseMode.HTML
    )


async def cmd_unlink(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    if DATA["account_links"].pop(str(user_id), None) is not None:
        save_data()
        await update.effective_message.reply_text("🌙 Unlinked.")
    else:
        await update.effective_message.reply_text("🌙 You don't have a linked account.")


# ==============================================================================
#  COMMANDS — Website XP / leaderboard / search
# ==============================================================================


async def cmd_level(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    username = context.args[0] if context.args else None

    if not username:
        account = get_account(update.effective_user.id)
        if not account or not account.get("verified"):
            await message.reply_text("🌙 Link your account first with /link <username>, or give a username: /level <username>")
            return
        username = account["lunar_username"]

    profile = await fetch_lunar_profile(username)
    if not profile:
        await message.reply_text(f"🌙 Couldn't find a Lunar profile for '{username}'.")
        return

    card_bytes = await build_level_card(profile)
    if card_bytes:
        await message.reply_photo(
            photo=io.BytesIO(card_bytes),
            caption=f"🌙 Level {profile['level']} — {profile['xp']}/{profile['required_xp']} XP",
        )
    else:
        await message.reply_text(
            f"🌙 <b>{html.escape(profile['username'])}</b>\n"
            f"Level {profile['level']} — {profile['xp']}/{profile['required_xp']} XP",
            parse_mode=ParseMode.HTML,
        )


async def cmd_leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    entries = await fetch_leaderboard()
    if not entries:
        await update.effective_message.reply_text("🌙 Couldn't fetch the leaderboard right now.")
        return
    lines = []
    for i, entry in enumerate(entries[:10], start=1):
        name = entry.get("username") or entry.get("name") or "Unknown"
        level = entry.get("level", 0)
        xp = entry.get("xp", 0)
        lines.append(f"{i}. {html.escape(str(name))} — Lv.{level} ({xp} XP)")
    await update.effective_message.reply_text(
        "🌙 <b>Lunar Leaderboard</b>\n" + "\n".join(lines), parse_mode=ParseMode.HTML
    )


async def cmd_search(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = " ".join(context.args) if context.args else ""
    if not query:
        await update.effective_message.reply_text("🌙 Usage: /search <query>")
        return
    results = await search_manga(query)
    if not results:
        await update.effective_message.reply_text(f"🌙 No results for '{query}'.")
        return
    lines = []
    for item in results[:10]:
        title = item.get("title") or item.get("name") or "Untitled"
        slug = item.get("slug") or item.get("id") or ""
        url = f"{CFG.lunar_base}/manga/{slug}" if slug else CFG.lunar_base
        lines.append(f'• <a href="{html.escape(url)}">{html.escape(str(title))}</a>')
    await update.effective_message.reply_text(
        f"🌙 <b>Results for '{html.escape(query)}'</b>\n" + "\n".join(lines),
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )


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

    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_xp_message), group=1)
    application.add_handler(ChatMemberHandler(track_first_seen, ChatMemberHandler.CHAT_MEMBER), group=1)

    for name, handler in {
        "help": cmd_help, "about": cmd_about, "ping": cmd_ping, "version": cmd_version,
        "uptime": cmd_uptime, "id": cmd_id,
        "link": cmd_link, "linkverify": cmd_linkverify, "unlink": cmd_unlink,
        "level": cmd_level, "leaderboard": cmd_leaderboard, "search": cmd_search,
    }.items():
        application.add_handler(CommandHandler(name, handler))

    application.add_error_handler(on_error)
    return application


def main() -> None:
    if CFG.token == "PUT_YOUR_BOT_TOKEN_HERE" or not CFG.token:
        raise SystemExit("🌙 Set CFG.token in nova.py before running.")
    if CFG.lunar_token == "PUT_YOUR_LUNAR_TOKEN_HERE":
        log.warning("CFG.lunar_token is a placeholder — XP granting and linking will fail until it's set.")

    load_data()
    application = build_application()

    if application.job_queue:
        application.job_queue.run_repeating(periodic_flush, interval=30, first=30)
    else:
        log.warning('Job queue unavailable — install "python-telegram-bot[job-queue]" for batched saves.')

    log.info("Nova is online — polling for updates.")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
