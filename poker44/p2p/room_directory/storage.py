import time
from typing import Dict, List

from poker44.p2p.schemas import RoomListing, ValidatorAnnounce


class InMemoryDirectory:
    def __init__(self, ttl_seconds: int = 60):
        self.ttl_seconds = ttl_seconds
        self._rooms: Dict[str, RoomListing] = {}

    def upsert(self, ann: ValidatorAnnounce) -> None:
        self._rooms[ann.validator_id] = RoomListing(
            validator_id=ann.validator_id,
            validator_name=ann.validator_name,
            platform_url=ann.platform_url,
            room_code=ann.room_code,
            region=ann.region,
            capacity_tables=ann.capacity_tables,
            version_hash=ann.version_hash,
            last_seen=int(time.time()),
        )

    def list_active(self) -> List[RoomListing]:
        now = int(time.time())
        active: List[RoomListing] = []
        for r in self._rooms.values():
            if now - r.last_seen <= self.ttl_seconds:
                active.append(r)
        # Prefer more capacity, then most recent.
        active.sort(key=lambda x: (x.capacity_tables, x.last_seen), reverse=True)
        return active
