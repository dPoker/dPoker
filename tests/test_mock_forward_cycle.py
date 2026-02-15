import asyncio
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Dict, List

import pytest

from poker44.core.models import LabeledHandBatch
from poker44.validator.forward import forward as forward_cycle
from poker44.validator.synapse import DetectionSynapse


class StaticProvider:
    def __init__(self, batches: List[LabeledHandBatch]):
        self._batches = batches

    def fetch_hand_batch(self, *, limit: int = 10, include_integrity: bool = True):  # noqa: ARG002
        return self._batches[:limit]


@dataclass
class MockAxon:
    hotkey: str


class CapturingDendrite:
    def __init__(self):
        self.last_synapse: DetectionSynapse | None = None

    async def __call__(self, *, axons, synapse: DetectionSynapse, timeout: float):  # noqa: ANN001, ARG002
        self.last_synapse = synapse
        out = []
        for _ in axons:
            resp = DetectionSynapse(chunks=synapse.chunks)
            resp.risk_scores = [0.2 for _ in (synapse.chunks or [])]
            out.append(resp)
        return out


class MockValidator:
    def __init__(self, provider):
        self.provider = provider
        self.forward_count = 0
        self.poll_interval = 0
        self.task_batch_size = 2
        self.reward_window = 1
        self.config = SimpleNamespace(neuron=SimpleNamespace(timeout=1.0))
        self.metagraph = SimpleNamespace(axons=[MockAxon("m0"), MockAxon("m1")])
        self.dendrite = CapturingDendrite()
        self.prediction_buffer: Dict[int, List[float]] = {}
        self.label_buffer: Dict[int, List[int]] = {}
        self.latest_rewards = None
        self.latest_uids = None

    def update_scores(self, rewards_array, miner_uids):  # noqa: ANN001
        self.latest_rewards = [float(x) for x in rewards_array.tolist()]
        self.latest_uids = [int(x) for x in miner_uids]


def test_forward_cycle_builds_chunks_and_scores():
    batches = [
        LabeledHandBatch(hands=[{"schema": "poker44_eval_hand_v1", "focus_seat": "s_1", "events": []}], is_human=True),
        LabeledHandBatch(hands=[{"schema": "poker44_eval_hand_v1", "focus_seat": "s_2", "events": []}], is_human=False),
    ]
    v = MockValidator(StaticProvider(batches))

    asyncio.run(forward_cycle(v))

    # Synapse chunks were built as list[list[dict]]
    syn = v.dendrite.last_synapse
    assert syn is not None
    assert isinstance(syn.chunks, list)
    assert len(syn.chunks) == 2
    assert isinstance(syn.chunks[0], list)
    assert isinstance(syn.chunks[0][0], dict)

    # Rewards computed (window=1)
    assert v.latest_rewards is not None
    assert len(v.latest_rewards) == 2


def test_forward_cycle_burn_targets_global_uid0_not_subset_index(monkeypatch):
    # Repro for the real p2p setup:
    # - validator is UID 0 (self), and we query only miner UID 1
    # - burn should allocate 95% to global UID 0, not to the first queried miner
    monkeypatch.setenv("POKER44_QUERY_UIDS", "1")
    monkeypatch.setenv("POKER44_QUERY_INCLUDE_SELF", "false")

    batches = [
        LabeledHandBatch(hands=[{"schema": "poker44_eval_hand_v1", "focus_seat": "s_1", "events": []}], is_human=True),
        LabeledHandBatch(hands=[{"schema": "poker44_eval_hand_v1", "focus_seat": "s_2", "events": []}], is_human=False),
    ]
    v = MockValidator(StaticProvider(batches))
    v.uid = 0
    v.metagraph = SimpleNamespace(axons=[MockAxon("m0"), MockAxon("m1"), MockAxon("m2")], n=3)

    asyncio.run(forward_cycle(v))

    assert v.latest_rewards is not None
    assert v.latest_uids is not None
    got = {uid: rew for uid, rew in zip(v.latest_uids, v.latest_rewards)}

    assert got[0] == pytest.approx(0.95, rel=1e-6)
    assert got[1] == pytest.approx(0.05, rel=1e-6)
