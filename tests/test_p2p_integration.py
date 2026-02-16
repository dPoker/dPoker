import asyncio
import os
import socket
import threading
import time
from typing import Any, Dict, List

import requests
import pytest
import uvicorn
from fastapi import FastAPI

import bittensor as bt

from poker44.p2p.room_directory.app import app as directory_app


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _wait_ok(url: str, timeout_s: float = 10.0) -> None:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            r = requests.get(url, timeout=1.0)
            if r.status_code == 200:
                return
        except Exception:
            pass
        time.sleep(0.1)
    raise RuntimeError(f"timeout waiting for {url}")


def _run_uvicorn(app: FastAPI, port: int) -> uvicorn.Server:
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    t = threading.Thread(target=server.run, daemon=False)
    t.start()
    server._thread = t  # type: ignore[attr-defined]  # test-only convenience
    return server


@pytest.mark.integration
def test_p2p_runner_announces_room_and_runs_mock_cycle(monkeypatch):
    # Fake platform backend (subset needed by run_mock_validator)
    platform = FastAPI()

    eval_batches: List[Dict[str, Any]] = [
        {
            "is_human": True,
            "hands": [{"schema": "poker44_eval_hand_v1", "hand_id": "h1", "table_id": "t1", "focus_seat": "s1", "events": []}],
        },
        {
            "is_human": False,
            "hands": [{"schema": "poker44_eval_hand_v1", "hand_id": "h2", "table_id": "t1", "focus_seat": "s2", "events": []}],
        },
    ]

    @platform.get("/health/live")
    def live():
        return {"ok": True}

    @platform.get("/internal/eval/health")
    def eval_health():
        return {"ok": True}

    @platform.get("/internal/rooms/health")
    def rooms_health():
        return {"ok": True}

    @platform.post("/internal/rooms/ensure")
    def ensure_room():
        return {"success": True, "data": {"roomCode": "ROOM123"}}

    @platform.post("/internal/rooms/{code}/start")
    def start_room(code: str):
        # Best-effort endpoint used by the p2p runner to auto-start once enough players join.
        return {"success": True, "data": {"roomCode": code, "status": "WAITING", "started": False}}

    @platform.get("/internal/eval/next")
    def next_batches():
        return {"success": True, "data": {"batches": eval_batches}}

    # Start directory + platform servers
    dir_port = _free_port()
    plat_port = _free_port()
    dir_server = _run_uvicorn(directory_app, dir_port)
    plat_server = _run_uvicorn(platform, plat_port)
    _wait_ok(f"http://127.0.0.1:{dir_port}/healthz", timeout_s=10.0)
    _wait_ok(f"http://127.0.0.1:{plat_port}/health/live", timeout_s=10.0)

    # Run the mock validator runner once.
    from scripts.validator.p2p.run_mock_validator import main as runner_main

    mnemonic = "legal winner thank year wave sausage worth useful legal winner thank yellow"
    expected_validator_id = bt.Keypair.create_from_mnemonic(mnemonic).ss58_address

    monkeypatch.setenv("POKER44_PROVIDER", "platform")
    monkeypatch.setenv("POKER44_PLATFORM_BACKEND_URL", f"http://127.0.0.1:{plat_port}")
    monkeypatch.setenv("POKER44_INTERNAL_EVAL_SECRET", "dev-internal-eval-secret")
    monkeypatch.setenv("POKER44_DIRECTORY_URL", f"http://127.0.0.1:{dir_port}")
    monkeypatch.setenv("POKER44_VALIDATOR_MNEMONIC", mnemonic)
    monkeypatch.setenv("POKER44_ANNOUNCE_INTERVAL_S", "1")
    monkeypatch.setenv("POKER44_MOCK_MINERS", "2")

    code = asyncio.run(runner_main())
    assert code == 0

    # Directory should contain our validator announcement (best-effort; poll briefly).
    deadline = time.time() + 5.0
    while time.time() < deadline:
        rooms = requests.get(f"http://127.0.0.1:{dir_port}/rooms", timeout=2.0).json()
        if any(r.get("validator_id") == expected_validator_id for r in rooms):
            break
        time.sleep(0.1)
    else:
        assert False, "validator did not appear in directory"

    # Cleanup servers
    dir_server.should_exit = True
    plat_server.should_exit = True
    dir_server._thread.join(timeout=5.0)  # type: ignore[attr-defined]
    plat_server._thread.join(timeout=5.0)  # type: ignore[attr-defined]
