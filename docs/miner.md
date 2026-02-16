# 🛠️ poker44 Miner Guide

Miners are bot-detection models. Validators send you **fresh, never-before-seen** poker behavior windows (grouped into chunks). You return a **bot risk score per chunk**.

The wire protocol is defined in `poker44/protocol.py`.

---

## Requirements

- Python 3.10/3.11
- Bittensor installed (see `requirements.txt`)

---

## Install

```bash
git clone <this-repo>
cd poker44-subnet
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

---

## Run (Testnet Example)

```bash
pm2 start python --name poker44_miner -- \
  ./neurons/miner.py \
  --netuid 401 \
  --wallet.name owner \
  --wallet.hotkey miner1 \
  --subtensor.network test \
  --logging.debug
```

Or use the helper script: `scripts/miner/run/run_miner.sh`.

---

## Protocol: What You Receive / Return

Validators call your axon with `DetectionSynapse`:

- `synapse.chunks`: `list[list[dict]]`
  - Each chunk is a list of hands.
  - Each hand is a sanitized dict payload (no hidden cards).

You must respond with:

- `synapse.risk_scores`: `list[float]` (same length as `chunks`)
- `synapse.predictions`: `list[bool]` (same length as `chunks`)

Minimal stub:

```python
from poker44.protocol import DetectionSynapse

async def forward(self, synapse: DetectionSynapse) -> DetectionSynapse:
    n = len(synapse.chunks or [])
    synapse.risk_scores = [0.5] * n
    synapse.predictions = [False] * n
    return synapse
```

---

## Scoring (High Level)

Validators score miners on detection quality (rewarding strong signal, penalizing false positives). The exact metric evolves; your goal is consistent: maximize generalization to unseen bots without flagging humans.

