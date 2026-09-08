from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import os
import asyncio
try:
    import aioredis
except Exception:
    aioredis = None

app = FastAPI(title="Lunar Dashboard API")

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
FEATURES_CHANNEL = "lunar:features"
CONTROL_CHANNEL = "lunar:control"

# simple in-memory store fallback
_features = {}

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
    return {"status": "ok", "redis": bool(app.state.redis)}

@app.get("/api/features")
async def list_features():
    if app.state.redis:
        keys = await app.state.redis.hkeys("lunar:features")
        features = []
        for k in keys:
            v = await app.state.redis.hget("lunar:features", k)
            try:
                import json
                features.append(json.loads(v))
            except:
                features.append({"name": k.decode() if isinstance(k, bytes) else k, "raw": v})
        return features
    return list(_features.values())

@app.post("/api/features")
async def upsert_feature(feature: Feature):
    data = feature.dict()
    if app.state.redis:
        import json
        await app.state.redis.hset("lunar:features", feature.name, json.dumps(data))
        # publish change
        await app.state.redis.publish(FEATURES_CHANNEL, json.dumps({"action":"upsert","feature":data}))
        return {"ok": True}
    _features[feature.name] = data
    return {"ok": True}

class ControlAction(BaseModel):
    action: str  # shutdown, restart, reload

@app.post("/api/control")
async def control(action: ControlAction):
    if action.action not in ("shutdown","restart","reload"):
        raise HTTPException(status_code=400, detail="invalid action")
    payload = {"action": action.action}
    if app.state.redis:
        import json
        await app.state.redis.publish(CONTROL_CHANNEL, json.dumps(payload))
        return {"ok": True}
    # fallback: write to a file as a signal
    with open("/tmp/lunar_control_signal.json","w") as f:
        import json
        json.dump(payload,f)
    return {"ok": True}
