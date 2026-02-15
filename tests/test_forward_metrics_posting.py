from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any, Dict, List, Tuple

import numpy as np


def test_forward_posts_cycle_metrics(monkeypatch):
    sent: List[Tuple[str, Dict[str, Any], Dict[str, str], float]] = []

    def fake_post(url: str, *, json: Dict[str, Any], headers: Dict[str, str], timeout: float):
        sent.append((url, json, headers, timeout))

        class _Resp:
            pass

        return _Resp()

    import poker44.validator.forward as fwd

    monkeypatch.setattr(fwd.requests, "post", fake_post)
    monkeypatch.setenv("POKER44_PLATFORM_BACKEND_URL", "http://platform")
    monkeypatch.setenv("POKER44_INTERNAL_EVAL_SECRET", "secret")
    monkeypatch.setenv("POKER44_VALIDATOR_ID", "vali-1")
    monkeypatch.setenv("POKER44_VALIDATOR_NAME", "poker44-validator")

    v = SimpleNamespace(
        metagraph=SimpleNamespace(hotkeys=["hk0", "hk1", "hk2"]),
        scores=np.asarray([0.0, 0.25, 0.5], dtype=float),
        forward_count=7,
        wallet=SimpleNamespace(hotkey=SimpleNamespace(ss58_address="addr")),
        config=SimpleNamespace(netuid=401, subtensor=SimpleNamespace(network="test")),
    )

    rewards = np.asarray([0.9, 0.1], dtype=np.float32)
    metrics = [
        {
            "f1_score": np.float64(0.5),
            "ap_score": np.float32(0.3),
            "fp_score": 0.8,
            "penalty": 1.0,
        },
        {"f1_score": 0.0, "ap_score": 0.0, "fp_score": 1.0, "penalty": 1.0},
    ]

    asyncio.run(
        fwd._post_cycle_metrics(  # type: ignore[attr-defined] - test private helper
            validator=v,
            miner_uids=[1, 2],
            rewards_array=rewards,
            metrics=metrics,
            batch_count=2,
            hand_count=2,
            resp_meta_by_uid={1: {"response_time_ms": 12, "status_code": 200}},
        )
    )

    assert len(sent) == 1
    url, body, headers, _timeout = sent[0]
    assert url == "http://platform/internal/metrics/ingest-cycle"
    assert headers["x-eval-secret"] == "secret"

    assert body["validator_id"] == "vali-1"
    assert body["validator_name"] == "poker44-validator"
    assert body["forward_count"] == 7
    assert body["batch_count"] == 2
    assert body["hand_count"] == 2

    miners = body["miners"]
    assert isinstance(miners, list)
    assert miners[0]["uid"] == 1
    assert miners[0]["hotkey"] == "hk1"
    assert isinstance(miners[0]["f1"], float)

