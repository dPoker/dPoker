from __future__ import annotations

import sys
from pathlib import Path

# Allow running as a script without requiring `PYTHONPATH=.`.
REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import asyncio
import os
import threading
import time
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import requests
import bittensor as bt

from poker44.validator.forward import forward as forward_cycle
from poker44.protocol import DetectionSynapse
from neurons.validator import PlatformBackendProvider

from poker44.p2p.directory_client import RoomDirectoryClient


def _getenv(key: str, default: Optional[str] = None) -> Optional[str]:
    """Read env var using the `POKER44_` prefix."""

    return os.getenv(f"POKER44_{key}") or default


def _make_keypair() -> bt.Keypair:
    mnemonic = (_getenv("VALIDATOR_MNEMONIC", "") or "").strip()
    if not mnemonic:
        mnemonic = bt.Keypair.generate_mnemonic()
    return bt.Keypair.create_from_mnemonic(mnemonic)


@dataclass
class MockAxon:
    hotkey: str


class MockDendrite:
    """
    Minimal stand-in for bt.Dendrite.

    It returns one response per axon, each containing `risk_scores` aligned with the
    number of chunks in the request.
    """

    def __init__(self, miner_behaviors: List[str]):
        self._behaviors = miner_behaviors

    async def __call__(self, *, axons: List[MockAxon], synapse: DetectionSynapse, timeout: float):
        chunks = synapse.chunks or []
        n = len(chunks)

        out = []
        for i, _ax in enumerate(axons):
            mode = self._behaviors[i % len(self._behaviors)] if self._behaviors else "random"
            if mode == "zeros":
                scores = [0.0] * n
            elif mode == "ones":
                scores = [1.0] * n
            else:
                # Random-ish but deterministic-ish per call
                base = (time.time_ns() % 10_000) / 10_000.0
                scores = [float((base + (j * 0.137)) % 1.0) for j in range(n)]

            resp = DetectionSynapse(chunks=chunks)
            resp.risk_scores = scores
            resp.predictions = [s >= 0.5 for s in scores]
            out.append(resp)
        return out


class MockValidator:
    def __init__(self, *, provider: PlatformBackendProvider, miners: int = 2):
        self.provider = provider
        self.forward_count = 0
        # forward loop uses this for sleep; keep configurable for daemon mode.
        self.poll_interval = int(_getenv("POLL_INTERVAL_S", "0") or "0")

        # Keep reward window tiny so one cycle produces rewards in mock mode.
        self.reward_window = int(_getenv("REWARD_WINDOW", "1") or "1")

        # Minimal "config" shape used by forward loop.
        self.config = SimpleNamespace(neuron=SimpleNamespace(timeout=float(_getenv("TIMEOUT_S", "5.0") or "5.0")))

        # Minimal metagraph shape: only axons are used in forward loop.
        self.metagraph = SimpleNamespace(axons=[MockAxon(hotkey=f"miner{i}") for i in range(miners)])

        # Dendrite mock
        behaviors = [x.strip() for x in (_getenv("MOCK_MINER_BEHAVIORS", "random,random") or "").split(",") if x.strip()]
        self.dendrite = MockDendrite(behaviors)

        # Buffers used by forward loop.
        self.prediction_buffer: Dict[int, List[float]] = {}
        self.label_buffer: Dict[int, List[int]] = {}

        # Captured latest rewards (for sanity checks).
        self.latest_rewards: Optional[List[float]] = None

    def update_scores(self, rewards_array, miner_uids):  # noqa: ANN001 - mimic bittensor base api
        self.latest_rewards = [float(x) for x in rewards_array.tolist()]


def _wait_http_ok(
    url: str,
    *,
    headers: Optional[dict] = None,
    timeout_s: float = 30.0,
    interval_s: float = 0.5,
) -> None:
    deadline = time.time() + timeout_s
    last_err: Optional[str] = None
    while time.time() < deadline:
        try:
            r = requests.get(url, headers=headers, timeout=2.0)
            if r.status_code == 200:
                return
            last_err = f"status={r.status_code}"
        except Exception as e:
            last_err = str(e)
        time.sleep(interval_s)
    raise RuntimeError(f"Timed out waiting for {url}: {last_err}")


def _ensure_room(platform_url: str, secret: str, *, validator_id: str) -> Optional[str]:
    try:
        r = requests.post(
            f"{platform_url.rstrip('/')}/internal/rooms/ensure",
            headers={"x-eval-secret": secret, "content-type": "application/json"},
            json={"validatorId": validator_id},
            timeout=5.0,
        )
        r.raise_for_status()
        payload = r.json()
        if isinstance(payload, dict) and payload.get("success") and isinstance(payload.get("data"), dict):
            return payload["data"].get("roomCode")
    except Exception:
        return None
    return None


def _seed_if_needed(platform_url: str, secret: str) -> None:
    # Best-effort seed: if /next returns empty, call simulate.
    try:
        r = requests.get(
            f"{platform_url.rstrip('/')}/internal/eval/next",
            params={"limit": 1, "requireMixed": "true"},
            headers={"x-eval-secret": secret},
            timeout=5.0,
        )
        r.raise_for_status()
        data = r.json()
        batches = (data.get("data") or {}).get("batches", []) if isinstance(data, dict) else []
        if batches:
            return
    except Exception:
        # If it fails, try seeding anyway.
        pass

    try:
        requests.post(
            f"{platform_url.rstrip('/')}/internal/eval/simulate",
            headers={"x-eval-secret": secret, "content-type": "application/json"},
            json={"humans": 2, "bots": 2, "hands": 3},
            timeout=30.0,
        ).raise_for_status()
    except Exception:
        pass


def _announce_loop(
    *,
    directory: RoomDirectoryClient,
    validator_id: str,
    validator_name: str,
    platform_url: str,
    secret: str,
    room_code: Optional[str],
    region: str,
    capacity_tables: int,
    version_hash: str,
    interval_s: int,
):
    while True:
        # Best-effort: start the room game as the validator host once enough players joined.
        # This mirrors the real validator's behavior (neurons/validator.py) but keeps the
        # local stack runnable without a full bittensor process.
        if room_code:
            try:
                requests.post(
                    f"{platform_url.rstrip('/')}/internal/rooms/{room_code}/start",
                    headers={"x-eval-secret": secret, "content-type": "application/json"},
                    timeout=5.0,
                )
            except Exception:
                pass

        try:
            directory.announce(
                validator_id=validator_id,
                validator_name=validator_name,
                platform_url=platform_url,
                room_code=room_code,
                region=region,
                capacity_tables=capacity_tables,
                version_hash=version_hash,
            )
        except Exception:
            pass
        time.sleep(max(1, interval_s))


async def main() -> int:
    provider_mode = (_getenv("PROVIDER", "platform") or "platform").strip().lower()
    if provider_mode != "platform":
        print("POKER44_PROVIDER must be 'platform' for this runner.")
        return 2

    platform_url = (_getenv("PLATFORM_BACKEND_URL", "http://localhost:3001") or "http://localhost:3001").rstrip("/")
    secret = _getenv("INTERNAL_EVAL_SECRET", "") or ""
    if not secret:
        print("Missing POKER44_INTERNAL_EVAL_SECRET")
        return 2

    keypair = _make_keypair()
    validator_id = keypair.ss58_address
    validator_name = _getenv("VALIDATOR_NAME", "poker44-validator") or "poker44-validator"
    region = _getenv("REGION", "unknown") or "unknown"
    version_hash = _getenv("VERSION_HASH", "poker44-validator-p2p-v0") or "poker44-validator-p2p-v0"
    capacity_tables = int(_getenv("CAPACITY_TABLES", "1") or "1")

    directory_url = (_getenv("DIRECTORY_URL", "http://localhost:8010") or "").rstrip("/")
    announce_interval_s = int(_getenv("ANNOUNCE_INTERVAL_S", "10") or "10")

    # Health checks
    _wait_http_ok(f"{platform_url}/health/live", timeout_s=60.0)
    _wait_http_ok(
        f"{platform_url}/internal/eval/health",
        headers={"x-eval-secret": secret},
        timeout_s=60.0,
    )
    _wait_http_ok(
        f"{platform_url}/internal/rooms/health",
        headers={"x-eval-secret": secret},
        timeout_s=60.0,
    )

    # Ensure there is a discoverable room code to announce.
    room_code = _ensure_room(platform_url, secret, validator_id=validator_id)
    if not room_code:
        print(
            "Failed to ensure advertised room. "
            "Check INTERNAL_EVAL_SECRET and platform backend logs."
        )
        return 2

    # Seed some hands so /internal/eval/next returns data for evaluation.
    if (_getenv("SEED_ON_START", "true") or "true").lower() != "false":
        _seed_if_needed(platform_url, secret)

    # Start directory announcer in background (best-effort).
    if directory_url:
        directory = RoomDirectoryClient(directory_url, keypair)
        t = threading.Thread(
            target=_announce_loop,
            kwargs={
                "directory": directory,
                "validator_id": validator_id,
                "validator_name": validator_name,
                "platform_url": platform_url,
                "secret": secret,
                "room_code": room_code,
                "region": region,
                "capacity_tables": capacity_tables,
                "version_hash": version_hash,
                "interval_s": announce_interval_s,
            },
            daemon=True,
        )
        t.start()

        # Quick sanity: try list rooms once.
        try:
            rooms = directory.list_rooms()
            has_self = any(r.get("validator_id") == validator_id for r in rooms if isinstance(r, dict))
            print(f"[directory] reachable. already_listed={has_self} rooms={len(rooms)}")
        except Exception as e:
            print(f"[directory] list failed: {e}")

    # Create provider and run ONE forward cycle using a mock bittensor layer.
    provider = PlatformBackendProvider(platform_url, secret, require_mixed=(_getenv("REQUIRE_MIXED", "true") or "true").lower() != "false")
    validator = MockValidator(provider=provider, miners=int(_getenv("MOCK_MINERS", "2") or "2"))

    run_forever = (_getenv("RUN_FOREVER", "false") or "false").lower() == "true"
    if not run_forever:
        await forward_cycle(validator)
        print(f"[mock] forward complete. latest_rewards={validator.latest_rewards}")
        print(f"[mock] announced_room_code={room_code!r} platform_url={platform_url}")
        return 0

    # Daemon mode (mock): keep running cycles to validate the full local stack.
    if validator.poll_interval <= 0:
        validator.poll_interval = 10
    while True:
        await forward_cycle(validator)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
