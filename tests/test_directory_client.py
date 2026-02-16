from __future__ import annotations

from typing import Any, Dict, List, Tuple

import bittensor as bt

from poker44.p2p.indexer.signing import verify_payload
from poker44.p2p.directory_client import RoomDirectoryClient


def test_directory_client_signs_payload(monkeypatch):
    calls: List[Tuple[str, Dict[str, Any], float]] = []

    def fake_post(url: str, *, json: Dict[str, Any], timeout: float):  # noqa: A002 - match requests API
        calls.append((url, json, timeout))

        class _Resp:
            def raise_for_status(self) -> None:
                return None

        return _Resp()

    import poker44.p2p.directory_client as mod

    monkeypatch.setattr(mod.requests, "post", fake_post)

    kp = bt.Keypair.create_from_mnemonic(
        "legal winner thank year wave sausage worth useful legal winner thank yellow"
    )
    client = RoomDirectoryClient("http://dir", kp, timeout_s=3.0)
    client.announce(
        validator_id=kp.ss58_address,
        validator_name="poker44-validator",
        platform_url="http://platform",
        room_code="ABC123",
        region="eu",
        capacity_tables=2,
        version_hash="v0",
    )

    assert len(calls) == 1
    url, body, timeout = calls[0]
    assert url == "http://dir/announce"
    assert timeout == 3.0

    payload = dict(body)
    sig = payload.pop("signature")
    assert payload["validator_name"] == "poker44-validator"
    assert verify_payload(payload, ss58_address=kp.ss58_address, signature_hex=sig)
