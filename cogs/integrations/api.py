from __future__ import annotations

import asyncio
import hmac
import logging
import os
from typing import Any

import uvicorn
from fastapi import APIRouter, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse


log = logging.getLogger("Lunar.API")

API_HOST = os.getenv("LUNAR_API_HOST", "0.0.0.0")
API_PORT = int(os.getenv("LUNAR_API_PORT", "8080"))
API_KEY = os.getenv("LUNAR_API_KEY", "").strip()
API_PREFIX = os.getenv("LUNAR_API_PREFIX", "/api/v1").rstrip("/")
API_ORIGIN = os.getenv("LUNAR_API_ORIGIN", "https://lunarx.to").strip()
API_MAX_BODY = int(
    os.getenv(
        "LUNAR_API_MAX_BODY",
        str(2 * 1024 * 1024),
    )
)

app = FastAPI(
    title="Lunar API",
    version="1.0.0",
    docs_url=f"{API_PREFIX}/docs",
    redoc_url=f"{API_PREFIX}/redoc",
    openapi_url=f"{API_PREFIX}/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[API_ORIGIN] if API_ORIGIN else [],
    allow_credentials=False,
    allow_methods=[
        "GET",
        "POST",
        "PUT",
        "PATCH",
        "DELETE",
        "OPTIONS",
    ],
    allow_headers=["*"],
)


@app.middleware("http")
async def body_limit(
    request: Request,
    call_next,
):
    content_length = request.headers.get("content-length")

    if content_length:
        try:
            if int(content_length) > API_MAX_BODY:
                return JSONResponse(
                    status_code=413,
                    content={
                        "ok": False,
                        "error": "Request body is too large.",
                    },
                )
        except ValueError:
            return JSONResponse(
                status_code=400,
                content={
                    "ok": False,
                    "error": "Invalid Content-Length header.",
                },
            )

    return await call_next(request)


def _valid_key(
    supplied: str | None,
) -> bool:
    if not API_KEY or not supplied:
        return False

    return hmac.compare_digest(
        supplied.encode("utf-8"),
        API_KEY.encode("utf-8"),
    )


def _extract_key(
    x_lunar_api_key: str | None,
    authorization: str | None,
) -> str | None:
    if x_lunar_api_key:
        return x_lunar_api_key.strip()

    if authorization:
        scheme, _, value = authorization.partition(" ")

        if (
            scheme.lower() == "bearer"
            and value.strip()
        ):
            return value.strip()

    return None


def require_api_key(
    x_lunar_api_key: str | None,
    authorization: str | None,
) -> None:
    if not API_KEY:
        log.error(
            "LUNAR_API_KEY is not configured; "
            "protected API access is disabled."
        )
        raise HTTPException(
            status_code=503,
            detail="API authentication is not configured.",
        )

    supplied = _extract_key(
        x_lunar_api_key,
        authorization,
    )

    if not _valid_key(supplied):
        raise HTTPException(
            status_code=401,
            detail="Unauthorized.",
        )


def protected(
    x_lunar_api_key: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
) -> None:
    require_api_key(
        x_lunar_api_key,
        authorization,
    )


api_router = APIRouter(
    prefix=API_PREFIX,
)


@api_router.get("")
async def api_index() -> dict[str, Any]:
    return {
        "ok": True,
        "service": "Lunar API",
        "version": "1.0.0",
        "docs": f"{API_PREFIX}/docs",
    }


@api_router.get("/health")
async def api_health() -> dict[str, Any]:
    return {
        "ok": True,
        "status": "online",
    }


app.include_router(api_router)


_registered_routers: dict[str, APIRouter] = {}

_server: uvicorn.Server | None = None
_server_task: asyncio.Task[Any] | None = None


def register_router(
    router: APIRouter,
    key: str,
) -> None:
    unregister_router(key)

    app.include_router(router)
    _registered_routers[key] = router


def unregister_router(
    key: str,
) -> None:
    router = _registered_routers.pop(
        key,
        None,
    )

    if router is None:
        return

    router_routes = set(router.routes)

    app.router.routes[:] = [
        route
        for route in app.router.routes
        if route not in router_routes
    ]


def api_route_count() -> int:
    return len(app.router.routes)


async def start_api() -> None:
    global _server
    global _server_task

    if (
        _server_task is not None
        and not _server_task.done()
    ):
        return

    if not API_KEY:
        log.warning(
            "LUNAR_API_KEY is not configured. "
            "Protected endpoints will return 503."
        )

    config = uvicorn.Config(
        app,
        host=API_HOST,
        port=API_PORT,
        log_config=None,
        access_log=False,
        loop="asyncio",
        lifespan="on",
    )

    _server = uvicorn.Server(config)

    _server_task = asyncio.create_task(
        _server.serve(),
        name="lunar-api-server",
    )

    log.info(
        "Lunar FastAPI listening on %s:%s",
        API_HOST,
        API_PORT,
    )


async def stop_api() -> None:
    global _server
    global _server_task

    if _server is not None:
        _server.should_exit = True

    if _server_task is not None:
        try:
            await _server_task
        except Exception:
            log.exception(
                "Lunar API shutdown failed."
            )

    _server = None
    _server_task = None
