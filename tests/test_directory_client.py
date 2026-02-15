from __future__ import annotations

from typing import Any, Dict, List, Tuple

from poker44.p2p.crypto import hmac_verify
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

    client = RoomDirectoryClient("http://dir", "shh", timeout_s=3.0)
    client.announce(
        validator_id="vali-1",
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
    assert hmac_verify(payload, "shh", sig)

