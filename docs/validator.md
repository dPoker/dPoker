# 🔐 poker44 Validator Guide (P2P Stack)

This subnet is evaluated on **fresh poker hands** generated inside **each validator's own room**. Validators must run their room isolated so miners and other validators cannot pre-see the hands used for evaluation.

This guide explains the **per-validator stack** we run in `p2p` mode:

- **Platform backend** (Node): poker gameplay + Postgres/Redis + internal eval endpoints
- **Indexer** (FastAPI): read API that verifies room announcements and serves a canonical directory view
- **Validator neuron** (Python): pulls fresh eval batches, queries miners via Bittensor, scores, and sets weights

The **Room Directory** is optional infrastructure (can be hosted centrally for MVP). It stores announcements; **signature verification happens in indexers/ledger**, not in the directory.

---

## Requirements

- Python 3.10/3.11
- Node 18+ and npm
- Docker (for Postgres/Redis)
- PM2 (`npm i -g pm2`)

---

## One-Command Setup (Validator Stack)

From `poker44-subnet/`:

```bash
NETWORK=test NETUID=401 \
VALIDATOR_WALLET=poker44-test VALIDATOR_HOTKEY=validator \
POKER44_DIRECTORY_URL=http://127.0.0.1:8010 \
bash scripts/validator/setup.sh
```

Notes:

- If `START_PORT` is not numeric (default is `rand`), the script picks a random free port range.
- The script starts 3 PM2 processes: platform backend, indexer, and the validator neuron.

To stop:

```bash
PM2_PREFIX=<printed-by-setup> bash scripts/deploy/pm2/down.sh
```

---

## Config (Environment Variables)

The validator process **fails fast** on missing critical env vars.

### Provider mode

- `POKER44_PROVIDER=platform`
  - Required:
    - `POKER44_PLATFORM_BACKEND_URL` (set by the setup script)
    - `POKER44_INTERNAL_EVAL_SECRET` (set by the setup script)

### Room announcements (optional, but required for discovery)

If you set `POKER44_DIRECTORY_URL`, the validator will announce a joinable room:

- Required:
  - `POKER44_DIRECTORY_URL`
- Optional:
  - `POKER44_VALIDATOR_NAME` (defaults to `poker44-validator`)
  - `POKER44_PLATFORM_PUBLIC_URL` (defaults to `POKER44_PLATFORM_BACKEND_URL`)
  - `POKER44_INDEXER_PUBLIC_URL` (used by UIs to choose a read API)
  - `POKER44_ROOM_CODE` (if not set, the validator asks the platform backend to mint/ensure one)

Announcements are **hotkey-signed**. If you set `POKER44_VALIDATOR_ID`, it must equal the hotkey SS58 address or the validator will exit.

### Receipts forwarding (optional)

If `POKER44_RECEIPTS_ENABLED=true`, the validator will forward signed hand receipts to a ledger/settlement API:

- Required:
  - `POKER44_LEDGER_API_URL`

---

## What The Validator Does Each Cycle

1. Reserve **fresh, consume-once** eval examples from the platform backend (`/internal/eval/next`).
2. Build protocol payloads and query miners using `DetectionSynapse` (`poker44/protocol.py`).
3. Score miner responses and set weights on-chain.
4. Mark reserved examples as evaluated (`/internal/eval/mark-evaluated`) so they can later be published (dataset gating).

---

## Debugging

PM2 logs:

```bash
pm2 ls
pm2 logs <process-name>
```

Health endpoints (ports depend on your `START_PORT` selection):

- Platform backend: `GET /health/live`
- Indexer: `GET /healthz`

