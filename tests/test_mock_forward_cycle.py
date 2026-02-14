import asyncio
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Dict, List

from Aceguard.core.models import LabeledHandBatch
from Aceguard.validator.forward import forward as forward_cycle
from Aceguard.validator.synapse import DetectionSynapse


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
        self.reward_window = 1
        self.config = SimpleNamespace(neuron=SimpleNamespace(timeout=1.0))
        self.metagraph = SimpleNamespace(axons=[MockAxon("m0"), MockAxon("m1")])
        self.dendrite = CapturingDendrite()
        self.prediction_buffer: Dict[int, List[float]] = {}
        self.label_buffer: Dict[int, List[int]] = {}
        self.latest_rewards = None

    def update_scores(self, rewards_array, miner_uids):  # noqa: ANN001
        self.latest_rewards = [float(x) for x in rewards_array.tolist()]


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

