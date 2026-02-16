import time

from fastapi.testclient import TestClient

import bittensor as bt

from poker44.p2p.indexer.signing import sign_payload
from poker44.p2p.room_directory.app import app


def test_directory_announce_and_list():
    client = TestClient(app)

    kp = bt.Keypair.create_from_mnemonic(
        "legal winner thank year wave sausage worth useful legal winner thank yellow"
    )
    payload = {
        "validator_id": kp.ss58_address,
        "validator_name": "poker44-validator",
        "platform_url": "http://localhost:3001",
        "indexer_url": None,
        "room_code": "ABC123",
        "region": "eu",
        "capacity_tables": 3,
        "version_hash": "v0",
        "timestamp": int(time.time()),
    }
    sig = sign_payload(payload, keypair=kp)

    r = client.post("/announce", json={**payload, "signature": sig})
    assert r.status_code == 200
    assert r.json()["ok"] is True

    r2 = client.get("/rooms")
    assert r2.status_code == 200
    rooms = r2.json()
    assert isinstance(rooms, list)
    assert len(rooms) >= 1
    assert rooms[0]["validator_id"] == kp.ss58_address
    assert rooms[0]["validator_name"] == "poker44-validator"
    assert rooms[0]["signature"] == sig


def test_directory_rejects_missing_signature():
    client = TestClient(app)
    payload = {
        "validator_id": "vali-bad",
        "validator_name": "poker44-validator",
        "platform_url": "http://localhost:3001",
        "indexer_url": None,
        "room_code": None,
        "region": "eu",
        "capacity_tables": 1,
        "version_hash": "v0",
        "timestamp": int(time.time()),
    }
    r = client.post("/announce", json=payload)
    # Signature is required by the request schema, so FastAPI rejects before hitting the handler.
    assert r.status_code == 422
