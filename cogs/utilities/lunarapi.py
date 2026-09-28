from __future__ import annotations
import logging
import os
import time
from typing import Any, Optional
from urllib.parse import quote
import aiohttp


log = logging.getLogger("lunar.api")


# ============================================================
# Configuration
# ============================================================

LUNAR_API_BASE = "https://api.lunarx.to"
LUNAR_WEBSITE = "https://lunarx.to"

LUNAR_TOKEN = os.getenv("lunar_token")
LUNAR_BYPASS_TOKEN = os.getenv("bypass_token")

# Known admin endpoints
GIVE_XP_ENDPOINT = "/api/admin/users/give-xp"
SET_COINS_ENDPOINT = "/api/admin/users/set-coins"
GACHA_ADMIN_CARDS_ENDPOINT = "/api/gacha/admin/cards"
GACHA_ADMIN_CARD_COVERS_ENDPOINT = "/api/gacha/admin/card-covers"
GACHA_SERIALS_ENDPOINT = "/api/gacha/serials/{template_id}"
GACHA_GIFT_ENDPOINT = "/api/gacha/admin/gift"


# ============================================================
# Shared session
# ============================================================
#
# One pooled aiohttp session for the whole bot process, instead
# of every cog opening/closing its own. Created lazily on first
# use; call close_session() from the bot's shutdown hook.

_session: Optional[aiohttp.ClientSession] = None


async def get_session() -> aiohttp.ClientSession:
    global _session

    if _session is None or _session.closed:
        timeout = aiohttp.ClientTimeout(
            total=15,
            connect=5,
            sock_read=12,
        )

        _session = aiohttp.ClientSession(
            timeout=timeout,
            headers={
                "Accept": "application/json",
                "User-Agent": "LunarDiscordBot/1.0",
            },
        )

    return _session


async def close_session() -> None:
    global _session

    if _session is not None and not _session.closed:
        await _session.close()

    _session = None


# ============================================================
# Errors
# ============================================================

class LunarAPIError(Exception):
    """
    Raised for any non-2xx response or transport failure talking
    to the Lunar API. `status` is 0 for connection/timeout errors
    that never got an HTTP response at all.
    """

    def __init__(
        self,
        status: int,
        message: str,
        *,
        body: Optional[str] = None,
    ):
        super().__init__(message)
        self.status = status
        self.body = body


# ============================================================
# Low-level request
# ============================================================

def _headers(
    *,
    authed: bool,
    extra: Optional[dict[str, str]],
) -> dict[str, str]:
    headers: dict[str, str] = {
        "Content-Type": "application/json",
    }

    if authed:
        if LUNAR_TOKEN:
            headers["Authorization"] = LUNAR_TOKEN
        else:
            log.warning(
                "lunar_token is not set — authenticated "
                "Lunar API calls will fail"
            )

    # The scraper-guard bypass is independent of auth — some
    # public endpoints (profile lookups, etc.) still need it to
    # avoid being blocked, even with no Authorization header.
    if LUNAR_BYPASS_TOKEN:
        headers["X-Scraper-Guard-Bypass"] = LUNAR_BYPASS_TOKEN

    if extra:
        headers.update(extra)

    return headers


async def request(
    method: str,
    path_or_url: str,
    *,
    authed: bool = True,
    params: Optional[dict[str, Any]] = None,
    json_body: Optional[dict[str, Any]] = None,
    headers: Optional[dict[str, str]] = None,
    base: str = LUNAR_API_BASE,
) -> Any:
    """
    Make a request through the shared session and return parsed
    JSON (or raw text if the response isn't JSON).

    Raises LunarAPIError on any non-2xx status or transport
    failure — callers decide whether to catch it or let it
    propagate.
    """

    session = await get_session()

    url = (
        path_or_url
        if path_or_url.startswith("http")
        else f"{base}{path_or_url}"
    )

    try:
        async with session.request(
            method,
            url,
            params=params,
            json=json_body,
            headers=_headers(
                authed=authed,
                extra=headers,
            ),
        ) as response:

            content_type = response.headers.get(
                "Content-Type", ""
            )

            if response.status >= 400:
                body = await response.text()

                log.error(
                    "Lunar API %s %s -> %s | %s",
                    method,
                    url,
                    response.status,
                    body[:500],
                )

                raise LunarAPIError(
                    response.status,
                    f"{method} {url} returned "
                    f"{response.status}",
                    body=body,
                )

            if "application/json" in content_type:
                return await response.json()

            return await response.text()

    except LunarAPIError:
        raise

    except (aiohttp.ClientError, TimeoutError) as error:
        log.exception(
            "Lunar API request failed: %s %s", method, url
        )
        raise LunarAPIError(
            0, f"{method} {url} failed: {error}"
        ) from error


async def get(
    path_or_url: str,
    **kwargs: Any,
) -> Any:
    return await request("GET", path_or_url, **kwargs)


async def post(
    path_or_url: str,
    **kwargs: Any,
) -> Any:
    return await request("POST", path_or_url, **kwargs)


# ============================================================
# Typed helpers — known admin endpoints
# ============================================================

async def give_xp(
    lunar_uuid: str,
    amount: int,
    *,
    action: str = "add",
) -> Optional[dict[str, Any]]:
    """
    POST /api/admin/users/give-xp

    Returns the parsed response dict, or None if the call failed
    (already logged by request()).
    """

    try:
        result = await post(
            GIVE_XP_ENDPOINT,
            json_body={
                "user_id": str(lunar_uuid),
                "amount": int(amount),
                "action": action,
            },
        )

    except LunarAPIError:
        return None

    return result if isinstance(result, dict) else None


async def set_coins(
    lunar_uuid: str,
    amount: int,
    *,
    action: str = "add",
) -> Optional[dict[str, Any]]:
    """
    POST /api/admin/users/set-coins

    Returns the parsed response dict, or None if the call failed
    (already logged by request()).
    """

    try:
        result = await post(
            SET_COINS_ENDPOINT,
            json_body={
                "user_identifier": str(lunar_uuid),
                "coins": int(amount),
                "action": action,
            },
        )

    except LunarAPIError:
        return None

    return result if isinstance(result, dict) else None


# ============================================================
# Typed helpers — gacha endpoints
# ============================================================

async def get_gacha_serials(
    template_id: str,
) -> Optional[dict[str, Any]]:
    """
    GET /api/gacha/serials/{template_id}

    Public endpoint — every minted copy of one card template,
    with mint numbers, owners, and totals (listed/max_copies).
    Returns None on failure (already logged by request()).
    """

    try:
        result = await get(
            GACHA_SERIALS_ENDPOINT.format(
                template_id=quote(
                    str(template_id),
                    safe="",
                )
            ),
            authed=False,
        )

    except LunarAPIError:
        return None

    return result if isinstance(result, dict) else None


async def get_gacha_cards() -> Optional[dict[str, Any]]:
    """
    GET /api/gacha/admin/cards

    Admin endpoint — the full card catalog (stats, skills,
    rarity, copy limits). Returns None on failure.
    """

    try:
        result = await get(
            GACHA_ADMIN_CARDS_ENDPOINT,
        )

    except LunarAPIError:
        return None

    return result if isinstance(result, dict) else None


async def get_gacha_card_covers() -> Optional[dict[str, Any]]:
    """
    GET /api/gacha/admin/card-covers

    Admin endpoint — lighter-weight card list (name, rarity,
    stars, cover image) without full stats/skills. Returns None
    on failure.
    """

    try:
        result = await get(
            GACHA_ADMIN_CARD_COVERS_ENDPOINT,
        )

    except LunarAPIError:
        return None

    return result if isinstance(result, dict) else None


async def gift_gacha_card(
    recipient: str,
    template_id: str,
) -> Optional[dict[str, Any]]:
    """
    POST /api/gacha/admin/gift

    Mints/gifts one copy of `template_id` to `recipient` (a Lunar
    username). Returns the parsed response dict (includes the
    minted `hero` details and a `success` flag) or None if the
    call failed outright (already logged by request()).

    NOTE: a 200 here does not always mean the gift landed — check
    result.get("success") too, since some failure modes may still
    return 200 with success: false. Callers should check both.
    """

    try:
        result = await post(
            GACHA_GIFT_ENDPOINT,
            json_body={
                "recipient": str(recipient),
                "template_id": str(template_id),
            },
        )

    except LunarAPIError:
        return None

    return result if isinstance(result, dict) else None


# ============================================================
# Status ping
# ============================================================

async def ping(
    url: str,
) -> tuple[Optional[int], Optional[float], Optional[str]]:
    """
    Raw status-code + round-trip-time check against any URL
    (website root, API root, etc.) using the shared session.

    Unlike request(), this never raises and never parses a body —
    a non-2xx status is meaningful data here, not a failure to
    hide. Returns (status, latency_ms, error) — error is None on
    success, and status/latency are None if the request never
    completed at all.
    """

    session = await get_session()
    started = time.monotonic()

    try:
        async with session.get(
            url,
            allow_redirects=True,
        ) as response:
            elapsed_ms = (
                (time.monotonic() - started) * 1000
            )

            return (response.status, round(elapsed_ms, 2), None)

    except (aiohttp.ClientError, TimeoutError) as error:
        elapsed_ms = (
            (time.monotonic() - started) * 1000
        )

        return (None, round(elapsed_ms, 2), str(error))
