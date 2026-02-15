from __future__ import annotations

import time
from typing import Optional

import requests

from poker44.p2p.crypto import hmac_sign
from poker44.p2p.schemas import ValidatorAnnounce


class RoomDirectoryClient:
    def __init__(
        self,
        directory_url: str,
        shared_secret: str,
        *,
        timeout_s: float = 5.0,
    ) -> None:
        self.directory_url = directory_url.rstrip("/")
        self.shared_secret = shared_secret
        self.timeout_s = timeout_s

    def announce(
        self,
        *,
        validator_id: str,
        validator_name: str,
        platform_url: str,
        room_code: Optional[str],
        region: str,
        capacity_tables: int,
        version_hash: str,
    ) -> None:
        payload = {
            "validator_id": validator_id,
            "validator_name": validator_name,
            "platform_url": platform_url,
            "room_code": room_code,
            "region": region,
            "capacity_tables": int(capacity_tables),
            "version_hash": version_hash,
            "timestamp": int(time.time()),
        }
        sig = hmac_sign(payload, self.shared_secret)
        ann = ValidatorAnnounce(**payload, signature=sig)
        requests.post(
            f"{self.directory_url}/announce",
            json=ann.model_dump(),
            timeout=self.timeout_s,
        ).raise_for_status()

    def list_rooms(self) -> list[dict]:
        r = requests.get(f"{self.directory_url}/rooms", timeout=self.timeout_s)
        r.raise_for_status()
        data = r.json()
        return data if isinstance(data, list) else []
