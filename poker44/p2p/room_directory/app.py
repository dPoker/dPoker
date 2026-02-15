import os
import time
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from poker44.p2p.crypto import hmac_verify
from poker44.p2p.schemas import RoomListing, ValidatorAnnounce
from poker44.p2p.room_directory.storage import InMemoryDirectory


DIRECTORY_SHARED_SECRET = os.getenv("DIRECTORY_SHARED_SECRET", "dev-secret")
TTL_SECONDS = int(os.getenv("DIRECTORY_TTL_SECONDS", "60"))
_CORS_ORIGINS_RAW = (os.getenv("DIRECTORY_CORS_ORIGINS") or "*").strip()
if _CORS_ORIGINS_RAW == "*":
    CORS_ORIGINS = ["*"]
else:
    CORS_ORIGINS = [x.strip() for x in _CORS_ORIGINS_RAW.split(",") if x.strip()]

app = FastAPI(title="poker44 Room Directory", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
store = InMemoryDirectory(ttl_seconds=TTL_SECONDS)


@app.get("/healthz")
def healthz():
    return {"ok": True, "ttl_seconds": TTL_SECONDS}


@app.post("/announce")
def announce(ann: ValidatorAnnounce):
    payload = ann.model_dump()
    sig = payload.pop("signature")

    if not DIRECTORY_SHARED_SECRET:
        raise HTTPException(status_code=500, detail="Directory misconfigured: missing secret")

    if not hmac_verify(payload, DIRECTORY_SHARED_SECRET, sig):
        raise HTTPException(status_code=401, detail="Invalid signature")

    now = int(time.time())
    if abs(now - ann.timestamp) > 120:
        raise HTTPException(status_code=400, detail="Bad timestamp")

    store.upsert(ann)
    return {"ok": True}


@app.get("/rooms", response_model=list[RoomListing])
def rooms():
    return store.list_active()
