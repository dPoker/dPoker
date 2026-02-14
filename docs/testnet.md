# poker44 Testnet Smoke Test (netuid 401)

This document is a practical checklist to validate the full MVP loop on **Bittensor testnet**:

- A validator runs its **own** platform backend (Postgres + Redis + gameplay engine).
- The validator generates **fresh** hands (simulated tables) and consumes them once for miner evaluation.
- The validator queries miners via **Synapse**, scores them, and eventually sets weights on-chain.
- (Optional) The validator announces a discoverable room to a **Room Directory** service.

## Prereqs

- `btcli` installed and configured
- Node.js + npm, Docker
- Python 3.10+
- (Optional) `pm2` for daemon processes

## 1) Wallets + Registration

Validator wallet (as requested):
- coldkey: `poker44-test`
- hotkey: `default`

Miner wallets (as requested):
- coldkey: `owner`
- hotkeys: `miner1`, `miner2`, `miner3`

Register validator on testnet netuid `401`:

```bash
btcli subnet register \
  --wallet.name poker44-test \
  --wallet.hotkey default \
  --netuid 401 \
  --subtensor.network test
```

## 2) Start Room Directory (Optional)

Run this anywhere reachable from your validator (same host is fine for smoke testing):

```bash
export DIRECTORY_SHARED_SECRET=dev-secret
export DIRECTORY_TTL_SECONDS=60

cd poker44-subnet
python -m uvicorn poker44.p2p.room_directory.app:app \
  --host 0.0.0.0 --port 8010
```

Verify:

```bash
curl -s http://127.0.0.1:8010/healthz
```

## 3) Start Platform Backend (Validator-Local)

```bash
cd platform/backend
cp -n .env.example .env

# Required for internal validator endpoints:
echo "INTERNAL_EVAL_SECRET=dev-internal-eval-secret" >> .env

npm install
npm run docker:up
npm run migration:run:dev
npm run dev
```

Verify:

```bash
curl -s http://127.0.0.1:3001/health/live
curl -s -H 'x-eval-secret: dev-internal-eval-secret' http://127.0.0.1:3001/internal/eval/health
```

## 4) Start Validator (On-Chain) + P2P Announce

Environment variables used by `poker44-subnet/neurons/validator.py`:

```bash
export POKER44_PROVIDER=platform
export POKER44_PLATFORM_BACKEND_URL=http://127.0.0.1:3001
export POKER44_INTERNAL_EVAL_SECRET=dev-internal-eval-secret

# Dev helper: generates hands when /internal/eval/next is empty.
export POKER44_AUTOSIMULATE=true

# Optional room directory announce:
export POKER44_DIRECTORY_URL=http://127.0.0.1:8010
export POKER44_DIRECTORY_SHARED_SECRET=dev-secret
export POKER44_PLATFORM_PUBLIC_URL=http://127.0.0.1:3001
```

Run:

```bash
cd poker44-subnet
pm2 start python --name poker44_validator -- \
  ./neurons/validator.py \
  --netuid 401 \
  --wallet.name poker44-test \
  --wallet.hotkey default \
  --subtensor.network test \
  --logging.debug
```

Look for logs like:
- `[p2p] announced room ...`
- `Processing N chunks ...`

## 5) Start Miner(s) (On-Chain)

Example for one miner:

```bash
cd poker44-subnet
pm2 start python --name poker44_miner1 -- \
  ./neurons/miner.py \
  --netuid 401 \
  --wallet.name owner \
  --wallet.hotkey miner1 \
  --subtensor.network test \
  --logging.debug
```

## 6) Verify End-to-End

1. Directory lists your validator room:

```bash
curl -s http://127.0.0.1:8010/rooms
```

2. Platform can generate hands (internal-only):

```bash
curl -s -X POST \
  -H 'content-type: application/json' \
  -H 'x-eval-secret: dev-internal-eval-secret' \
  -d '{"humans":2,"bots":2,"hands":3}' \
  http://127.0.0.1:3001/internal/eval/simulate
```

3. Platform returns consume-once eval batches:

```bash
curl -s -H 'x-eval-secret: dev-internal-eval-secret' \
  'http://127.0.0.1:3001/internal/eval/next?limit=3&requireMixed=true'
```

4. Validator queries miners and produces rewards (check validator logs).

## Notes

- Validators are isolated because each validator runs its own platform backend + DB.
- Hands used for miner evaluation are never shared and are consumed once.
- Weight-setting on-chain occurs on epoch boundaries (configurable via `--neuron.epoch_length`).

