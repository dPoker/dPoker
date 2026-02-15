from __future__ import annotations

from pydantic import BaseModel, Field
from typing import Optional


class ValidatorAnnounce(BaseModel):
    # Validator identity (e.g., hotkey SS58 address, or stable host ID in mock mode)
    validator_id: str
    # Friendly name for UI/debug (does not need to be unique).
    validator_name: str = "poker44-validator"
    # Base URL where humans connect to play poker on this validator
    platform_url: str
    # Base URL where other peers/clients can query this validator's indexer/read API.
    # In local dev this will typically be http://127.0.0.1:<port>
    indexer_url: Optional[str] = None
    # A room code that is open for discovery (optional; depends on platform UX)
    room_code: Optional[str] = None

    region: str = "unknown"
    capacity_tables: int = 0
    version_hash: str
    timestamp: int

    # HMAC signature over all fields except signature.
    signature: str


class RoomListing(BaseModel):
    validator_id: str
    validator_name: str = "poker44-validator"
    platform_url: str
    indexer_url: Optional[str] = None
    room_code: Optional[str] = None
    region: str
    capacity_tables: int
    version_hash: str
    last_seen: int


class EnsureRoomResponse(BaseModel):
    roomCode: str = Field(alias="roomCode")
