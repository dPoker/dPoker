import time

from fastapi.testclient import TestClient

from poker44.p2p.crypto import hmac_sign
from poker44.p2p.room_directory.app import app


def test_directory_announce_and_list():
    client = TestClient(app)

    payload = {
        "validator_id": "vali-1",
        "platform_url": "http://localhost:3001",
        "room_code": "ABC123",
        "region": "eu",
        "capacity_tables": 3,
        "version_hash": "v0",
        "timestamp": int(time.time()),
    }
    sig = hmac_sign(payload, "dev-secret")

    r = client.post("/announce", json={**payload, "signature": sig})
    assert r.status_code == 200
    assert r.json()["ok"] is True

    r2 = client.get("/rooms")
    assert r2.status_code == 200
    rooms = r2.json()
    assert isinstance(rooms, list)
    assert len(rooms) >= 1
    assert rooms[0]["validator_id"] == "vali-1"


def test_directory_rejects_bad_signature():
    client = TestClient(app)
    payload = {
        "validator_id": "vali-bad",
        "platform_url": "http://localhost:3001",
        "room_code": None,
        "region": "eu",
        "capacity_tables": 1,
        "version_hash": "v0",
        "timestamp": int(time.time()),
        "signature": "deadbeef",
    }
    r = client.post("/announce", json=payload)
    assert r.status_code == 401

