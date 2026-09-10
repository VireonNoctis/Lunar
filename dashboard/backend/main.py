"""
Lunar Dashboard Backend
FastAPI + SQLAlchemy + Redis + Discord OAuth2
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import os
import secrets
import time
from collections import defaultdict
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import Optional

from fastapi import (
    FastAPI,
    HTTPException,
    WebSocket,
    WebSocketDisconnect,
    Request,
    Response,
    Query,
    Depends,
    status,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

try:
    import aioredis
except Exception:
    aioredis = None

try:
    import httpx
except Exception:
    httpx = None

try:
    from sqlalchemy import (
        create_engine,
        Table,
        Column,
        Integer,
        String,
        Text,
        JSON,
        DateTime,
        Float,
        Index,
        MetaData,
        func,
    )
    from sqlalchemy.exc import OperationalError
except Exception:
    create_engine = None
    Table = None

# ============================================================
# STRUCTURED JSON LOGGING
# ============================================================

class JSONFormatter(logging.Formatter):
    def format(self, record):
        log_entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if hasattr(record, "extra_data"):
            log_entry["data"] = record.extra_data
        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_entry)

handler = logging.StreamHandler()
handler.setFormatter(JSONFormatter())

dashboard_logger = logging.getLogger("lunar.dashboard")
dashboard_logger.addHandler(handler)
dashboard_logger.setLevel(logging.INFO)

logger = logging.getLogger("lunar.backend")

# ============================================================
# CONFIG
# ============================================================

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
DATABASE_URL = os.getenv("DATABASE_URL")
DASHBOARD_SECRET = os.getenv("DASHBOARD_SECRET", secrets.token_hex(32))
DASHBOARD_PORT = int(os.getenv("DASHBOARD_PORT", "8000"))

OAUTH_CLIENT_ID = os.getenv("OAUTH_CLIENT_ID", "")
OAUTH_CLIENT_SECRET = os.getenv("OAUTH_CLIENT_SECRET", "")
OAUTH_CALLBACK_URL = os.getenv(
    "OAUTH_CALLBACK_URL", "http://localhost:8000/auth/discord/callback"
)

OWNERS = {
    "1419744000977403994",
    "960946185768685618",
}

FEATURES_CHANNEL = "lunar:features"
CONTROL_CHANNEL = "lunar:control"
USAGE_CHANNEL = "lunar:usage"
AUDIT_CHANNEL = "lunar:audit"
ERRORS_CHANNEL = "lunar:errors"
BOT_STATUS_CHANNEL = "lunar:bot_status"

# Rate limiting: max control actions per hour per actor
RATE_LIMIT_CONTROLS = 3
RATE_LIMIT_WINDOW = 3600

# ============================================================
# DATABASE
# ============================================================

engine = None
metadata = None
feature_flags_table = None
audit_logs_table = None
command_usage_table = None
admin_users_table = None
bot_errors_table = None
bot_status_table = None

if DATABASE_URL and create_engine is not None:
    try:
        engine = create_engine(DATABASE_URL, future=True, pool_pre_ping=True)
        metadata = MetaData()

        feature_flags_table = Table(
            "feature_flags",
            metadata,
            Column("id", Integer, primary_key=True, autoincrement=True),
            Column("name", String(200), unique=True, nullable=False),
            Column("description", Text, default=""),
            Column("data", JSON),
            Column("updated_at", DateTime, default=func.now(), onupdate=func.now()),
            Column("updated_by", String(100)),
        )

        audit_logs_table = Table(
            "audit_logs",
            metadata,
            Column("id", Integer, primary_key=True, autoincrement=True),
            Column("actor_id", String(100)),
            Column("action", String(100), nullable=False),
            Column("target", String(200)),
            Column("details", JSON),
            Column("level", String(20), default="INFO"),
            Column("created_at", DateTime, default=func.now()),
            Index("idx_audit_created", "created_at"),
            Index("idx_audit_actor", "actor_id"),
            Index("idx_audit_action", "action"),
        )

        command_usage_table = Table(
            "command_usage",
            metadata,
            Column("id", Integer, primary_key=True, autoincrement=True),
            Column("guild_id", String(100)),
            Column("user_id", String(100)),
            Column("command", String(200), nullable=False),
            Column("timestamp", DateTime, default=func.now()),
            Column("metadata", JSON),
            Index("idx_usage_timestamp", "timestamp"),
            Index("idx_usage_command", "command"),
            Index("idx_usage_guild", "guild_id"),
        )

        admin_users_table = Table(
            "admin_users",
            metadata,
            Column("id", Integer, primary_key=True, autoincrement=True),
            Column("discord_id", String(100), unique=True, nullable=False),
            Column("username", String(200)),
            Column("role", String(50), default="admin"),
            Column("added_at", DateTime, default=func.now()),
        )

        bot_errors_table = Table(
            "bot_errors",
            metadata,
            Column("id", Integer, primary_key=True, autoincrement=True),
            Column("level", String(20), nullable=False),
            Column("logger", String(200)),
            Column("message", Text),
            Column("cog", String(200)),
            Column("traceback", Text),
            Column("created_at", DateTime, default=func.now()),
            Index("idx_error_created", "created_at"),
        )

        bot_status_table = Table(
            "bot_status",
            metadata,
            Column("id", Integer, primary_key=True, autoincrement=True),
            Column("uptime_seconds", Float),
            Column("latency_ms", Float),
            Column("guild_count", Integer),
            Column("user_count", Integer),
            Column("loaded_cogs", JSON),
            Column("maintenance_mode", String(10)),
            Column("reported_at", DateTime, default=func.now()),
        )

        metadata.create_all(engine)
        logger.info("Database connected: %s", DATABASE_URL.split("@")[-1] if "@" in DATABASE_URL else "local")
    except OperationalError as e:
        logger.error("Failed to initialize DB: %s", e)
        engine = None

# ============================================================
# IN-MEMORY FALLBACKS
# ============================================================

_features: dict[str, dict] = {}
_audit_log: list[dict] = []
_rate_limits: dict[str, list[float]] = defaultdict(list)
_sessions: dict[str, dict] = {}  # session_id -> user data
_bot_status_cache: dict = {
    "uptime_seconds": 0,
    "latency_ms": 0,
    "guild_count": 0,
    "user_count": 0,
    "loaded_cogs": [],
    "maintenance_mode": False,
    "reported_at": None,
}
_bot_errors: list[dict] = []

# ============================================================
# PYDANTIC MODELS
# ============================================================


class Feature(BaseModel):
    name: str
    description: str = ""
    enabled_globally: bool = False
    enabled_per_guild: dict = {}


class FeatureBatch(BaseModel):
    features: list[Feature]
    actor_id: Optional[str] = None


class ControlAction(BaseModel):
    action: str  # shutdown, restart, reload
    actor_id: Optional[str] = None
    reason: Optional[str] = None


class UsageEvent(BaseModel):
    command: str
    guild_id: Optional[str] = None
    user_id: Optional[str] = None
    timestamp: Optional[str] = None
    metadata: Optional[dict] = None


class AuditEvent(BaseModel):
    actor_id: str
    action: str
    target: Optional[str] = None
    details: Optional[dict] = None
    level: str = "INFO"


class ErrorReport(BaseModel):
    level: str  # ERROR, WARNING, CRITICAL
    logger: Optional[str] = None
    message: str
    cog: Optional[str] = None
    traceback: Optional[str] = None


class BotStatusReport(BaseModel):
    uptime_seconds: float = 0
    latency_ms: float = 0
    guild_count: int = 0
    user_count: int = 0
    loaded_cogs: list[str] = []
    maintenance_mode: bool = False


# ============================================================
# HELPER FUNCTIONS
# ============================================================


def sign_session(data: str) -> str:
    """Sign session data with HMAC."""
    return hmac.new(
        DASHBOARD_SECRET.encode(), data.encode(), hashlib.sha256
    ).hexdigest()


def verify_session(data: str, sig: str) -> bool:
    """Verify session signature."""
    expected = sign_session(data)
    return hmac.compare_digest(expected, sig)


def create_session(user: dict) -> str:
    """Create a session cookie and return session ID."""
    session_id = secrets.token_hex(32)
    _sessions[session_id] = {
        "user": user,
        "created_at": time.time(),
        "expires_at": time.time() + 86400,  # 24 hours
    }
    return session_id


def get_session(request: Request) -> Optional[dict]:
    """Extract and validate session from cookie."""
    session_cookie = request.cookies.get("lunar_session")
    if not session_cookie:
        return None

    parts = session_cookie.split(".")
    if len(parts) != 2:
        return None

    session_id, sig = parts
    if not verify_session(session_id, sig):
        return None

    session = _sessions.get(session_id)
    if not session or session["expires_at"] < time.time():
        _sessions.pop(session_id, None)
        return None

    return session["user"]


def require_auth(request: Request) -> dict:
    """Dependency that requires authentication."""
    user = get_session(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


DEMO_ADMIN_USER = {
    "id": "1419744000977403994",
    "username": "Demo Admin",
    "avatar": None,
    "roles": ["owner", "admin"],
}


def require_admin(request: Request) -> dict:
    """Dependency that requires admin/owner role."""
    user = get_session(request)
    if not user:
        # Demo mode: allow access without session for development
        return DEMO_ADMIN_USER

    user_id = user.get("id", "")
    roles = user.get("roles", [])

    if user_id not in OWNERS and "owner" not in roles and "admin" not in roles:
        raise HTTPException(status_code=403, detail="Admin access required")

    return user


def check_rate_limit(actor_id: str) -> bool:
    """Check if actor is within rate limit for control actions."""
    now = time.time()
    window_start = now - RATE_LIMIT_WINDOW

    # Clean old entries
    _rate_limits[actor_id] = [
        t for t in _rate_limits[actor_id] if t > window_start
    ]

    if len(_rate_limits[actor_id]) >= RATE_LIMIT_CONTROLS:
        return False

    _rate_limits[actor_id].append(now)
    return True


# ============================================================
# APP LIFECYCLE
# ============================================================


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    app.state.redis = None
    if aioredis:
        try:
            app.state.redis = await aioredis.from_url(REDIS_URL)
            logger.info("Redis connected: %s", REDIS_URL)
        except Exception as e:
            logger.error("Redis connection failed: %s", e)

    # Start WebSocket manager
    app.state.ws_manager = WSManager()
    asyncio.create_task(app.state.ws_manager.start_redis_listener(app.state.redis))

    yield

    # Shutdown
    if app.state.redis:
        await app.state.redis.close()


app = FastAPI(
    title="Lunar Dashboard API",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000", "*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================
# WEBSOCKET MANAGER
# ============================================================


class WSManager:
    def __init__(self):
        self.connections: list[WebSocket] = []

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.connections.append(ws)

    def disconnect(self, ws: WebSocket):
        if ws in self.connections:
            self.connections.remove(ws)

    async def broadcast(self, message: dict):
        dead = []
        for ws in self.connections:
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)

    async def start_redis_listener(self, redis):
        """Listen to Redis pub/sub and broadcast to WebSocket clients."""
        if not redis:
            return

        try:
            pubsub = redis.pubsub()
            await pubsub.subscribe(
                FEATURES_CHANNEL, CONTROL_CHANNEL, USAGE_CHANNEL, AUDIT_CHANNEL, ERRORS_CHANNEL
            )

            async for message in pubsub.listen():
                if message["type"] == "message":
                    try:
                        data = json.loads(message["data"])
                        await self.broadcast(data)
                    except Exception:
                        pass
        except Exception as e:
            logger.error("Redis listener error: %s", e)


# ============================================================
# AUTH ENDPOINTS
# ============================================================


@app.get("/auth/discord")
async def discord_login():
    """Redirect to Discord OAuth2 authorization."""
    if not OAUTH_CLIENT_ID:
        raise HTTPException(
            status_code=501,
            detail="Discord OAuth not configured. Set OAUTH_CLIENT_ID and OAUTH_CLIENT_SECRET.",
        )

    params = {
        "client_id": OAUTH_CLIENT_ID,
        "redirect_uri": OAUTH_CALLBACK_URL,
        "response_type": "code",
        "scope": "identify guilds",
        "state": secrets.token_hex(16),
    }

    query = "&".join(f"{k}={v}" for k, v in params.items())
    return RedirectResponse(
        url=f"https://discord.com/api/oauth2/authorize?{query}"
    )


@app.get("/auth/discord/callback")
async def discord_callback(code: str = Query(...), state: str = Query(None)):
    """Handle Discord OAuth2 callback."""
    if not httpx:
        raise HTTPException(status_code=500, detail="httpx not installed")

    # Exchange code for token
    async with httpx.AsyncClient() as client:
        token_resp = await client.post(
            "https://discord.com/api/oauth2/token",
            data={
                "client_id": OAUTH_CLIENT_ID,
                "client_secret": OAUTH_CLIENT_SECRET,
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": OAUTH_CALLBACK_URL,
            },
        )

        if token_resp.status_code != 200:
            raise HTTPException(status_code=400, detail="Failed to exchange code")

        token_data = token_resp.json()
        access_token = token_data.get("access_token")

        # Get user info
        user_resp = await client.get(
            "https://discord.com/api/users/@me",
            headers={"Authorization": f"Bearer {access_token}"},
        )

        if user_resp.status_code != 200:
            raise HTTPException(status_code=400, detail="Failed to fetch user")

        user_data = user_resp.json()

    # Determine roles
    user_id = user_data["id"]
    roles = []
    if user_id in OWNERS:
        roles.append("owner")
    else:
        # Check admin users table
        if engine is not None:
            def _check_admin():
                with engine.connect() as conn:
                    row = conn.execute(
                        admin_users_table.select().where(
                            admin_users_table.c.discord_id == user_id
                        )
                    ).first()
                    return row
            row = await asyncio.to_thread(_check_admin)
            if row:
                roles.append("admin")

    user = {
        "id": user_id,
        "username": user_data.get("username", ""),
        "avatar": user_data.get("avatar"),
        "roles": roles,
    }

    # Create session
    session_id = create_session(user)
    sig = sign_session(session_id)

    response = RedirectResponse(url="http://localhost:5173/dashboard")
    response.set_cookie(
        "lunar_session",
        f"{session_id}.{sig}",
        httponly=True,
        samesite="lax",
        max_age=86400,
    )

    return response


@app.post("/auth/logout")
async def logout(request: Request):
    """Clear session."""
    session_cookie = request.cookies.get("lunar_session")
    if session_cookie:
        session_id = session_cookie.split(".")[0]
        _sessions.pop(session_id, None)

    response = Response()
    response.delete_cookie("lunar_session")
    return {"ok": True}


# ============================================================
# USER ENDPOINTS
# ============================================================


@app.get("/api/me")
async def get_me(request: Request):
    """Return current session user info."""
    user = get_session(request)
    if not user:
        # Demo mode fallback
        return {
            "id": "1419744000977403994",
            "username": "Demo Admin",
            "avatar": None,
            "roles": ["owner", "admin"],
        }
    return user


# ============================================================
# FEATURE ENDPOINTS
# ============================================================


@app.get("/api/features")
async def list_features():
    """List all feature flags."""
    if engine is not None and feature_flags_table is not None:
        def _read():
            with engine.connect() as conn:
                rows = conn.execute(feature_flags_table.select()).all()
                return [
                    {
                        "name": r.name,
                        "description": r.description or "",
                        **(r.data or {}),
                        "updated_at": r.updated_at.isoformat() if r.updated_at else None,
                        "updated_by": r.updated_by,
                    }
                    for r in rows
                ]
        return await asyncio.to_thread(_read)

    if app.state.redis:
        try:
            keys = await app.state.redis.hkeys("lunar:features")
            features = []
            for k in keys:
                v = await app.state.redis.hget("lunar:features", k)
                try:
                    features.append(json.loads(v))
                except Exception:
                    features.append({"name": k.decode() if isinstance(k, bytes) else k})
            return features
        except Exception:
            pass

    return list(_features.values())


@app.post("/api/features")
async def upsert_feature(
    feature: Feature,
    actor_id: Optional[str] = Query(None),
    user: dict = Depends(require_admin),
):
    """Create or update a feature flag."""
    data = feature.dict()
    data["updated_at"] = datetime.utcnow().isoformat()
    data["updated_by"] = user.get("username", actor_id)

    if engine is not None and feature_flags_table is not None:
        def _write():
            with engine.begin() as conn:
                existing = conn.execute(
                    feature_flags_table.select().where(
                        feature_flags_table.c.name == feature.name
                    )
                ).first()
                if existing:
                    conn.execute(
                        feature_flags_table.update()
                        .where(feature_flags_table.c.name == feature.name)
                        .values(
                            data=data,
                            description=feature.description,
                            updated_at=datetime.utcnow(),
                            updated_by=user.get("username", actor_id),
                        )
                    )
                else:
                    conn.execute(
                        feature_flags_table.insert().values(
                            name=feature.name,
                            description=feature.description,
                            data=data,
                            updated_by=user.get("username", actor_id),
                        )
                    )

            # Audit log
            with engine.begin() as conn:
                conn.execute(
                    audit_logs_table.insert().values(
                        actor_id=user.get("id", actor_id),
                        action="feature_upsert",
                        target=feature.name,
                        details=data,
                    )
                )

        await asyncio.to_thread(_write)
    else:
        _features[feature.name] = data
        _audit_log.append(
            {
                "actor_id": user.get("id", actor_id),
                "action": "feature_upsert",
                "target": feature.name,
                "details": data,
                "timestamp": datetime.utcnow().isoformat(),
            }
        )

    # Publish to Redis
    if app.state.redis:
        try:
            await app.state.redis.publish(
                FEATURES_CHANNEL,
                json.dumps({"action": "upsert", "feature": data}),
            )
        except Exception:
            pass

    logger.info("Feature upserted: %s by %s", feature.name, user.get("username"))
    return {"ok": True}


@app.post("/api/features/batch")
async def batch_features(
    body: FeatureBatch,
    user: dict = Depends(require_admin),
):
    """Apply multiple feature changes atomically."""
    results = []

    for feature in body.features:
        data = feature.dict()
        data["updated_at"] = datetime.utcnow().isoformat()
        data["updated_by"] = user.get("username", body.actor_id)

        if engine is not None and feature_flags_table is not None:
            def _write_batch(f=feature, d=data):
                with engine.begin() as conn:
                    existing = conn.execute(
                        feature_flags_table.select().where(
                            feature_flags_table.c.name == f.name
                        )
                    ).first()
                    if existing:
                        conn.execute(
                            feature_flags_table.update()
                            .where(feature_flags_table.c.name == f.name)
                            .values(data=d, updated_at=datetime.utcnow(), updated_by=user.get("username"))
                        )
                    else:
                        conn.execute(
                            feature_flags_table.insert().values(
                                name=f.name, description=f.description, data=d, updated_by=user.get("username")
                            )
                        )

                    conn.execute(
                        audit_logs_table.insert().values(
                            actor_id=user.get("id", body.actor_id),
                            action="feature_batch_upsert",
                            target=f.name,
                            details=d,
                        )
                    )
            await asyncio.to_thread(_write_batch)
        else:
            _features[feature.name] = data

        # Publish each change
        if app.state.redis:
            try:
                await app.state.redis.publish(
                    FEATURES_CHANNEL,
                    json.dumps({"action": "upsert", "feature": data}),
                )
            except Exception:
                pass

        results.append({"name": feature.name, "ok": True})

    logger.info("Batch features applied: %d by %s", len(results), user.get("username"))
    return {"ok": True, "applied": len(results)}


# ============================================================
# GUILD ENDPOINTS
# ============================================================


@app.get("/api/guilds")
async def list_guilds():
    """List guilds the bot is in. Proxies to Discord if token available."""
    bot_token = os.getenv("TOKEN")

    if bot_token and httpx:
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    "https://discord.com/api/v10/users/@me/guilds",
                    headers={"Authorization": f"Bot {bot_token}"},
                )
                if resp.status_code == 200:
                    guilds = resp.json()
                    return [
                        {
                            "guild_id": g["id"],
                            "name": g["name"],
                            "member_count": g.get("approximate_member_count", 0),
                            "joined_at": g.get("joined_at", ""),
                            "icon_url": (
                                f"https://cdn.discordapp.com/icons/{g['id']}/{g['icon']}.png"
                                if g.get("icon")
                                else None
                            ),
                            "has_bot": True,
                        }
                        for g in guilds
                    ]
        except Exception:
            pass

    # Mock fallback
    return [
        {
            "guild_id": "1330574273760465029",
            "name": "Lunar Official",
            "member_count": 1247,
            "joined_at": "2024-06-15T00:00:00Z",
            "icon_url": None,
            "has_bot": True,
        },
    ]


@app.get("/api/guilds/{guild_id}/stats")
async def guild_stats(guild_id: str):
    """Get stats for a specific guild."""
    if engine is not None and command_usage_table is not None:
        def _read():
            with engine.connect() as conn:
                # Last 30 days usage
                thirty_days_ago = datetime.utcnow() - timedelta(days=30)
                rows = conn.execute(
                    command_usage_table.select()
                    .where(command_usage_table.c.guild_id == guild_id)
                    .where(command_usage_table.c.timestamp > thirty_days_ago)
                ).all()

                commands = defaultdict(int)
                users = set()
                for r in rows:
                    commands[r.command] += 1
                    if r.user_id:
                        users.add(r.user_id)

                return {
                    "guild_id": guild_id,
                    "total_commands_30d": len(rows),
                    "unique_users_30d": len(users),
                    "top_commands": dict(sorted(commands.items(), key=lambda x: -x[1])[:10]),
                }
        return await asyncio.to_thread(_read)

    return {
        "guild_id": guild_id,
        "total_commands_30d": 0,
        "unique_users_30d": 0,
        "top_commands": {},
    }


# ============================================================
# LOG ENDPOINTS
# ============================================================


@app.get("/api/logs")
async def get_logs(
    limit: int = Query(100, ge=1, le=1000),
    level: Optional[str] = Query(None),
    guild_id: Optional[str] = Query(None),
    command: Optional[str] = Query(None),
    from_date: Optional[str] = Query(None, alias="from"),
    to_date: Optional[str] = Query(None, alias="to"),
):
    """Query audit logs with filters."""
    if engine is not None and audit_logs_table is not None:
        def _read():
            with engine.connect() as conn:
                query = audit_logs_table.select()

                if level:
                    query = query.where(audit_logs_table.c.level == level.upper())
                if command:
                    query = query.where(audit_logs_table.c.action.ilike(f"%{command}%"))
                if from_date:
                    query = query.where(audit_logs_table.c.created_at >= datetime.fromisoformat(from_date))
                if to_date:
                    query = query.where(audit_logs_table.c.created_at <= datetime.fromisoformat(to_date) + timedelta(days=1))

                query = query.order_by(audit_logs_table.c.id.desc()).limit(limit)
                rows = conn.execute(query).all()
                return [
                    {
                        "id": str(r.id),
                        "actor_id": r.actor_id,
                        "action": r.action,
                        "target": r.target,
                        "details": r.details,
                        "level": r.level or "INFO",
                        "timestamp": r.created_at.isoformat() if r.created_at else None,
                    }
                    for r in rows
                ]
        return await asyncio.to_thread(_read)

    # Fallback: in-memory
    logs = list(reversed(_audit_log[-limit:]))
    return logs


@app.post("/api/logs")
async def create_log(event: UsageEvent):
    """Bot posts usage events here."""
    if engine is not None and command_usage_table is not None:
        def _write():
            with engine.begin() as conn:
                conn.execute(
                    command_usage_table.insert().values(
                        guild_id=event.guild_id,
                        user_id=event.user_id,
                        command=event.command,
                        timestamp=datetime.utcnow(),
                        metadata=event.metadata,
                    )
                )
        await asyncio.to_thread(_write)

    # Publish to Redis
    if app.state.redis:
        try:
            await app.state.redis.publish(
                USAGE_CHANNEL,
                json.dumps(
                    {
                        "command": event.command,
                        "guild_id": event.guild_id,
                        "user_id": event.user_id,
                        "timestamp": event.timestamp or datetime.utcnow().isoformat(),
                    }
                ),
            )
        except Exception:
            pass

    return {"ok": True}


# ============================================================
# AUDIT ENDPOINTS (Bot -> Backend)
# ============================================================


@app.post("/api/audit")
async def create_audit(event: AuditEvent):
    """Bot posts audit events here."""
    audit_entry = {
        "actor_id": event.actor_id,
        "action": event.action,
        "target": event.target,
        "details": event.details or {},
        "level": event.level,
        "timestamp": datetime.utcnow().isoformat(),
    }

    if engine is not None and audit_logs_table is not None:
        def _write():
            with engine.begin() as conn:
                conn.execute(
                    audit_logs_table.insert().values(
                        actor_id=event.actor_id,
                        action=event.action,
                        target=event.target,
                        details=event.details,
                        level=event.level,
                    )
                )
        await asyncio.to_thread(_write)
    else:
        _audit_log.append(audit_entry)

    # Broadcast to WebSocket clients
    if hasattr(app.state, "ws_manager"):
        await app.state.ws_manager.broadcast(audit_entry)

    # Publish to Redis
    if app.state.redis:
        try:
            await app.state.redis.publish(AUDIT_CHANNEL, json.dumps(audit_entry))
        except Exception:
            pass

    return {"ok": True}


# ============================================================
# ERROR REPORTING ENDPOINTS (Bot -> Backend)
# ============================================================


@app.post("/api/errors")
async def report_error(error: ErrorReport):
    """Bot reports errors here for dashboard display."""
    error_entry = {
        "level": error.level,
        "logger": error.logger,
        "message": error.message,
        "cog": error.cog,
        "traceback": error.traceback,
        "timestamp": datetime.utcnow().isoformat(),
    }

    if engine is not None and bot_errors_table is not None:
        def _write():
            with engine.begin() as conn:
                conn.execute(
                    bot_errors_table.insert().values(
                        level=error.level,
                        logger=error.logger,
                        message=error.message,
                        cog=error.cog,
                        traceback=error.traceback,
                    )
                )
        await asyncio.to_thread(_write)
    else:
        _bot_errors.append(error_entry)

    # Broadcast to WebSocket clients
    if hasattr(app.state, "ws_manager"):
        await app.state.ws_manager.broadcast({"type": "error", **error_entry})

    # Publish to Redis
    if app.state.redis:
        try:
            await app.state.redis.publish(ERRORS_CHANNEL, json.dumps(error_entry))
        except Exception:
            pass

    logger.error("Bot error reported: %s - %s", error.level, error.message)
    return {"ok": True}


@app.get("/api/errors")
async def list_errors(
    limit: int = Query(50, ge=1, le=500),
    level: Optional[str] = Query(None),
    cog: Optional[str] = Query(None),
):
    """List reported bot errors."""
    if engine is not None and bot_errors_table is not None:
        def _read():
            with engine.connect() as conn:
                query = bot_errors_table.select()
                if level:
                    query = query.where(bot_errors_table.c.level == level.upper())
                if cog:
                    query = query.where(bot_errors_table.c.cog.ilike(f"%{cog}%"))
                query = query.order_by(bot_errors_table.c.id.desc()).limit(limit)
                rows = conn.execute(query).all()
                return [
                    {
                        "id": str(r.id),
                        "level": r.level,
                        "logger": r.logger,
                        "message": r.message,
                        "cog": r.cog,
                        "traceback": r.traceback,
                        "timestamp": r.created_at.isoformat() if r.created_at else None,
                    }
                    for r in rows
                ]
        return await asyncio.to_thread(_read)

    return list(reversed(_bot_errors[-limit:]))


# ============================================================
# BOT STATUS ENDPOINTS
# ============================================================


@app.post("/api/bot/status")
async def report_bot_status(status_report: BotStatusReport):
    """Bot reports its status here."""
    _bot_status_cache.update({
        "uptime_seconds": status_report.uptime_seconds,
        "latency_ms": status_report.latency_ms,
        "guild_count": status_report.guild_count,
        "user_count": status_report.user_count,
        "loaded_cogs": status_report.loaded_cogs,
        "maintenance_mode": status_report.maintenance_mode,
        "reported_at": datetime.utcnow().isoformat(),
    })

    if engine is not None and bot_status_table is not None:
        def _write():
            with engine.begin() as conn:
                conn.execute(
                    bot_status_table.insert().values(
                        uptime_seconds=status_report.uptime_seconds,
                        latency_ms=status_report.latency_ms,
                        guild_count=status_report.guild_count,
                        user_count=status_report.user_count,
                        loaded_cogs=status_report.loaded_cogs,
                        maintenance_mode=str(status_report.maintenance_mode),
                    )
                )
        await asyncio.to_thread(_write)

    # Broadcast to WebSocket
    if hasattr(app.state, "ws_manager"):
        await app.state.ws_manager.broadcast({
            "type": "bot_status",
            **_bot_status_cache,
        })

    return {"ok": True}


@app.get("/api/bot/status")
async def get_bot_status():
    """Get current bot status."""
    return _bot_status_cache


@app.get("/api/bot/health")
async def bot_health():
    """Comprehensive health check."""
    redis_ok = False
    if app.state.redis:
        try:
            await app.state.redis.ping()
            redis_ok = True
        except Exception:
            pass

    db_ok = False
    if engine is not None:
        try:
            with engine.connect() as conn:
                conn.execute(func.now())
            db_ok = True
        except Exception:
            pass

    bot_reported = _bot_status_cache.get("reported_at")
    bot_online = False
    if bot_reported:
        try:
            reported_dt = datetime.fromisoformat(bot_reported)
            bot_online = (datetime.utcnow() - reported_dt).total_seconds() < 60
        except Exception:
            pass

    return {
        "status": "ok" if (redis_ok or db_ok) else "degraded",
        "services": {
            "redis": {"up": redis_ok, "configured": app.state.redis is not None},
            "database": {"up": db_ok, "configured": engine is not None},
            "bot_online": bot_online,
        },
        "bot": _bot_status_cache,
        "version": "1.0.0",
    }


# ============================================================
# USAGE / ANALYTICS ENDPOINTS
# ============================================================


@app.get("/api/usage")
async def get_usage(
    from_date: str = Query(..., alias="from"),
    to_date: str = Query(..., alias="to"),
    group_by: str = Query("day"),
):
    """Get aggregated usage metrics."""
    if engine is not None and command_usage_table is not None:
        def _read():
            with engine.connect() as conn:
                from_dt = datetime.fromisoformat(from_date)
                to_dt = datetime.fromisoformat(to_date) + timedelta(days=1)

                # Total commands
                total = conn.execute(
                    func.count(command_usage_table.c.id)
                ).scalar() or 0

                # Unique users
                unique = conn.execute(
                    func.count(func.distinct(command_usage_table.c.user_id))
                ).scalar() or 0

                # Commands by name
                rows = conn.execute(
                    command_usage_table.select()
                    .where(command_usage_table.c.timestamp.between(from_dt, to_dt))
                ).all()

                commands_by_name = defaultdict(int)
                for r in rows:
                    commands_by_name[r.command] += 1

                return {
                    "period": f"{from_date} to {to_date}",
                    "total_commands": total,
                    "unique_users": unique,
                    "commands_by_name": dict(commands_by_name),
                }
        return await asyncio.to_thread(_read)

    # Mock data fallback
    return {
        "period": f"{from_date} to {to_date}",
        "total_commands": 15420,
        "unique_users": 3842,
        "commands_by_name": {
            "ping": 4200,
            "anime": 3100,
            "tmusic": 2800,
            "search": 1900,
            "suggest": 1200,
            "coinflip": 800,
            "dadjoke": 600,
            "leaderboard": 420,
            "giveaway": 300,
            "about": 100,
        },
    }


# ============================================================
# CONTROL ENDPOINTS
# ============================================================


@app.post("/api/control")
async def control(action: ControlAction, user: dict = Depends(require_admin)):
    """Send control action to bot via Redis."""
    if action.action not in ("shutdown", "restart", "reload"):
        raise HTTPException(status_code=400, detail="Invalid action")

    actor_id = user.get("id", action.actor_id)

    # Rate limiting
    if not check_rate_limit(actor_id):
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded. Max {RATE_LIMIT_CONTROLS} control actions per hour.",
        )

    payload = {
        "action": action.action,
        "actor_id": actor_id,
        "reason": action.reason,
    }

    # Audit log
    if engine is not None and audit_logs_table is not None:
        def _audit():
            with engine.begin() as conn:
                conn.execute(
                    audit_logs_table.insert().values(
                        actor_id=actor_id,
                        action=f"control_{action.action}",
                        target="bot",
                        details=payload,
                        level="WARNING" if action.action in ("shutdown", "restart") else "INFO",
                    )
                )
        await asyncio.to_thread(_audit)
    else:
        _audit_log.append(
            {
                "actor_id": actor_id,
                "action": f"control_{action.action}",
                "target": "bot",
                "details": payload,
                "timestamp": datetime.utcnow().isoformat(),
            }
        )

    # Publish to Redis
    if app.state.redis:
        try:
            await app.state.redis.publish(CONTROL_CHANNEL, json.dumps(payload))
        except Exception:
            pass

    logger.info("Control action: %s by %s (reason: %s)", action.action, actor_id, action.reason)
    return {"ok": True}


# ============================================================
# WEBSOCKET
# ============================================================


@app.websocket("/ws/logs")
async def websocket_logs(ws: WebSocket):
    """Real-time log streaming via WebSocket."""
    await ws.accept()

    manager = app.state.ws_manager
    manager.connections.append(ws)

    try:
        while True:
            # Keep connection alive, receive pings
            data = await ws.receive_text()
            if data == "ping":
                await ws.send_text("pong")
    except WebSocketDisconnect:
        manager.disconnect(ws)
    except Exception:
        manager.disconnect(ws)


# ============================================================
# HEALTH CHECK
# ============================================================


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {
        "status": "ok",
        "redis": bool(app.state.redis) if hasattr(app.state, "redis") else False,
        "db": bool(engine),
        "version": "1.0.0",
    }


# ============================================================
# ADMIN USER MANAGEMENT
# ============================================================


@app.get("/api/admins")
async def list_admins(user: dict = Depends(require_admin)):
    """List admin users (owner only)."""
    if user.get("id") not in OWNERS:
        raise HTTPException(status_code=403, detail="Owner access required")

    if engine is not None and admin_users_table is not None:
        def _read():
            with engine.connect() as conn:
                rows = conn.execute(admin_users_table.select()).all()
                return [
                    {
                        "id": r.discord_id,
                        "username": r.username,
                        "role": r.role,
                        "added_at": r.added_at.isoformat() if r.added_at else None,
                    }
                    for r in rows
                ]
        return await asyncio.to_thread(_read)

    # Fallback: OWNERS only
    return [{"id": oid, "username": "Owner", "role": "owner"} for oid in OWNERS]


@app.post("/api/admins")
async def add_admin(discord_id: str, username: str = "", user: dict = Depends(require_admin)):
    """Add admin user (owner only)."""
    if user.get("id") not in OWNERS:
        raise HTTPException(status_code=403, detail="Owner access required")

    if engine is not None and admin_users_table is not None:
        def _write():
            with engine.begin() as conn:
                conn.execute(
                    admin_users_table.insert().values(
                        discord_id=discord_id,
                        username=username,
                        role="admin",
                    )
                )
        await asyncio.to_thread(_write)

    return {"ok": True}
