from __future__ import annotations

import asyncio
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, Dict, List, Tuple

import numpy as np

from poker44.core.models import LabeledHandBatch
from poker44.validator.forward import forward as forward_cycle


class StaticProvider:
    def __init__(self, batches: List[LabeledHandBatch]):
        self._batches = batches

    def fetch_hand_batch(self, *, limit: int = 10, include_integrity: bool = True):  # noqa: ARG002
        return self._batches[:limit]


@dataclass
class MockAxon:
    hotkey: str
    is_serving: bool = True
    ip: str = "127.0.0.1"
    port: int = 1234


class DummyDendrite:
    async def __call__(self, *, axons, synapse, timeout: float):  # noqa: ANN001, ARG002
        out = []
        for _ in axons:
            # Mirror the synapse chunk count.
            scores = [0.2 for _ in (synapse.chunks or [])]
            resp = SimpleNamespace(
                risk_scores=scores,
                dendrite=SimpleNamespace(status_code=200, process_time_ms=12),
            )
            out.append(resp)
        return out


def test_forward_marks_eval_hand_ids_evaluated(monkeypatch):
    sent: List[Tuple[str, Dict[str, Any], Dict[str, str] | None]] = []

    def fake_post(url: str, *, json: Dict[str, Any], headers: Dict[str, str], timeout: float):  # noqa: ARG002
        sent.append((url, json, headers))

        class _Resp:
            pass

        return _Resp()

    import poker44.validator.forward as fwd

    monkeypatch.setattr(fwd.requests, "post", fake_post)
    monkeypatch.setenv("POKER44_PLATFORM_BACKEND_URL", "http://platform")
    monkeypatch.setenv("POKER44_INTERNAL_EVAL_SECRET", "secret")
    monkeypatch.setenv("POKER44_VALIDATOR_ID", "vali-1")
    monkeypatch.setenv("POKER44_VALIDATOR_NAME", "poker44-validator")
    monkeypatch.setenv("POKER44_QUERY_UIDS", "0,1")
    monkeypatch.setenv("POKER44_QUERY_INCLUDE_SELF", "true")

    batches = [
        LabeledHandBatch(
            hands=[{"schema": "poker44_eval_hand_v1", "hand_id": "h_a", "focus_seat": "s_1", "events": []}],
            is_human=True,
        ),
        LabeledHandBatch(
            hands=[{"schema": "poker44_eval_hand_v1", "hand_id": "h_b", "focus_seat": "s_2", "events": []}],
            is_human=False,
        ),
    ]

    v = SimpleNamespace(
        provider=StaticProvider(batches),
        forward_count=0,
        poll_interval=0,
        task_batch_size=2,
        reward_window=1,
        lock=None,
        config=SimpleNamespace(neuron=SimpleNamespace(timeout=1.0), netuid=401, subtensor=SimpleNamespace(network="test")),
        uid=0,
        metagraph=SimpleNamespace(axons=[MockAxon("m0"), MockAxon("m1")], n=2, hotkeys=["hk0", "hk1"]),
        dendrite=DummyDendrite(),
        prediction_buffer={},
        label_buffer={},
        scores=np.asarray([0.0, 0.0], dtype=float),
        update_scores=lambda rewards, uids: None,
    )

    asyncio.run(forward_cycle(v))

    urls = [u for u, _json, _hdrs in sent]
    assert "http://platform/internal/metrics/ingest-cycle" in urls
    assert "http://platform/internal/eval/mark-evaluated" in urls

    # Verify the mark-evaluated payload includes our deduped tokens.
    mark_calls = [(u, j) for (u, j, _h) in sent if u.endswith("/internal/eval/mark-evaluated")]
    assert len(mark_calls) == 1
    _u, body = mark_calls[0]
    assert body == {"hand_ids": ["h_a", "h_b"]}

