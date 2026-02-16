import os
import time
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from poker44.p2p.schemas import RoomListing, ValidatorAnnounce
from poker44.p2p.room_directory.storage import InMemoryDirectory


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
    # NOTE: The directory is intentionally a lightweight registry.
    # Signature verification is performed by indexers (and the ledger),
    # which gate settlement and UI selection.
    if not isinstance(ann.signature, str) or not ann.signature.strip():
        raise HTTPException(status_code=401, detail="Missing signature")

    now = int(time.time())
    if abs(now - ann.timestamp) > 120:
        raise HTTPException(status_code=400, detail="Bad timestamp")

    store.upsert(ann)
    return {"ok": True}


@app.get("/rooms", response_model=list[RoomListing])
def rooms():
    return store.list_active()
