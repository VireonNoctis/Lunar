from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import os
import asyncio
import json

try:
    import aioredis
except Exception:
    aioredis = None

# Optional DB support
try:
    from sqlalchemy import (create_engine, Table, Column, Integer, String, MetaData, Text, JSON)
    from sqlalchemy.exc import OperationalError
except Exception:
    create_engine = None
    Table = None

app = FastAPI(title="Lunar Dashboard API")

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
FEATURES_CHANNEL = "lunar:features"
CONTROL_CHANNEL = "lunar:control"
DATABASE_URL = os.getenv("DATABASE_URL")

# simple in-memory store fallback
_features = {}

# DB setup (synchronous SQLAlchemy for simplicity, run in threadpool)
engine = None
metadata = None
feature_flags_table = None
audit_logs_table = None

if DATABASE_URL and create_engine is not None:
    try:
        engine = create_engine(DATABASE_URL, future=True)
        metadata = MetaData()

        feature_flags_table = Table(
            "feature_flags",
            metadata,
            Column("id", Integer, primary_key=True, autoincrement=True),
            Column("name", String(200), unique=True, nullable=False),
            Column("data", JSON),
        )

        audit_logs_table = Table(
            "audit_logs",
            metadata,
            Column("id", Integer, primary_key=True, autoincrement=True),
            Column("actor_id", String(100)),
            Column("action", String(100)),
            Column("target", String(200)),
            Column("details", JSON),
        )

        # create tables if they don't exist
        metadata.create_all(engine)
    except OperationalError as e:
        print("Failed to initialize DB:", e)
        engine = None

class Feature(BaseModel):
    name: str
    description: str = ""
    enabled_globally: bool = False
    enabled_per_guild: dict = {}

@app.on_event("startup")
async def startup():
    app.state.redis = None
    if aioredis:
        try:
            app.state.redis = await aioredis.from_url(REDIS_URL)
        except Exception as e:
            print("Failed to connect to Redis:", e)

@app.on_event("shutdown")
async def shutdown():
    if app.state.redis:
        await app.state.redis.close()

@app.get("/health")
async def health():
    return {"status": "ok", "redis": bool(app.state.redis), "db": bool(engine)}

@app.get("/api/features")
async def list_features():
    # Read from DB if available, otherwise Redis, otherwise in-memory
    if engine is not None:
        def _read():
            with engine.connect() as conn:
                rows = conn.execute(feature_flags_table.select()).all()
                return [dict(name=r.name, **(r.data or {})) for r in rows]
        return await asyncio.to_thread(_read)

    if app.state.redis:
        keys = await app.state.redis.hkeys("lunar:features")
        features = []
        for k in keys:
            v = await app.state.redis.hget("lunar:features", k)
            try:
                features.append(json.loads(v))
            except:
                features.append({"name": k.decode() if isinstance(k, bytes) else k, "raw": v})
        return features
    return list(_features.values())

@app.post("/api/features")
async def upsert_feature(feature: Feature, actor_id: str | None = None):
    data = feature.dict()
    # persist to DB if configured
    if engine is not None:
        def _write():
            with engine.begin() as conn:
                # upsert emulation
                existing = conn.execute(
                    feature_flags_table.select().where(feature_flags_table.c.name == feature.name)
                ).first()
                if existing:
                    conn.execute(
                        feature_flags_table.update()
                        .where(feature_flags_table.c.name == feature.name)
                        .values(data=data)
                    )
                else:
                    conn.execute(
                        feature_flags_table.insert().values(name=feature.name, data=data)
                    )
            # write audit
            with engine.begin() as conn:
                conn.execute(audit_logs_table.insert().values(
                    actor_id=str(actor_id) if actor_id else None,
                    action="feature_upsert",
                    target=feature.name,
                    details=data,
                ))
        await asyncio.to_thread(_write)
        # publish change
        if app.state.redis:
            await app.state.redis.publish(FEATURES_CHANNEL, json.dumps({"action":"upsert","feature":data}))
        return {"ok": True}

    if app.state.redis:
        await app.state.redis.hset("lunar:features", feature.name, json.dumps(data))
        # publish change
        await app.state.redis.publish(FEATURES_CHANNEL, json.dumps({"action":"upsert","feature":data}))
        # optional audit write to file for prototype
        if actor_id:
            with open("/tmp/lunar_audit.log","a") as f:
                f.write(json.dumps({"actor": actor_id, "action": "feature_upsert", "target": feature.name, "details": data}) + "\n")
        return {"ok": True}

    _features[feature.name] = data
    return {"ok": True}

class ControlAction(BaseModel):
    action: str  # shutdown, restart, reload
    actor_id: str | None = None

@app.post("/api/control")
async def control(action: ControlAction):
    if action.action not in ("shutdown","restart","reload"):
        raise HTTPException(status_code=400, detail="invalid action")
    payload = {"action": action.action, "actor_id": action.actor_id}
    if app.state.redis:
        await app.state.redis.publish(CONTROL_CHANNEL, json.dumps(payload))
        # audit
        if engine is not None:
            def _audit():
                with engine.begin() as conn:
                    conn.execute(audit_logs_table.insert().values(
                        actor_id=str(action.actor_id) if action.actor_id else None,
                        action=f"control_{action.action}",
                        target="bot",
                        details=payload,
                    ))
            await asyncio.to_thread(_audit)
        return {"ok": True}
    # fallback: write to a file as a signal
    with open("/tmp/lunar_control_signal.json","w") as f:
        json.dump(payload,f)
    # also write audit log to file
    with open("/tmp/lunar_audit.log","a") as f:
        f.write(json.dumps({"actor": action.actor_id, "action": f"control_{action.action}", "target": "bot", "details": payload}) + "\n")
    return {"ok": True}

@app.get("/api/logs")
async def get_logs(limit: int = 100):
    # Return recent audit logs if DB available
    if engine is not None:
        def _read():
            with engine.connect() as conn:
                rows = conn.execute(audit_logs_table.select().order_by(audit_logs_table.c.id.desc()).limit(limit)).all()
                return [dict(id=r.id, actor_id=r.actor_id, action=r.action, target=r.target, details=r.details) for r in rows]
        return await asyncio.to_thread(_read)
    # fallback: read file
    if os.path.exists("/tmp/lunar_audit.log"):
        with open("/tmp/lunar_audit.log","r") as f:
            lines = f.readlines()[-limit:]
            return [json.loads(l) for l in lines]
    return []
