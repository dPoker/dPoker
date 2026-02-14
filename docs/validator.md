# 🔐 poker44 Validator Guide

Welcome to poker44 – the poker anti-bot subnet with objective, evolving
evaluation. This guide covers the lean validator scaffold introduced in v0.

> **Goal for v0:** fetch fresh, consume-once hands from the **local platform backend**,
> query miners, score them (F1-centric rewards), and push weights on-chain.

---

## ✅ Requirements

- Ubuntu 22.04+ (or any Linux with Python 3.10/3.11 available)
- Python 3.10+

---

## 🛠️ Install

```bash
git clone <this-repo>
cd poker44-subnet
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

___
Validators automatically ingest the labeled hands provided by the poker44
adapter. Human hands are chosen randomly out of massive dataset whereas bot hands are created on the fly to generate near perfect poker hands. No manual player list is required; the dataset already contains ground truth labels for bots and humans.

---

## Local Platform Backend (P2P Mode)

For the decentralized setup, each validator runs its **own** poker platform backend (Postgres + Redis + gameplay)
and pulls **fresh, consume-once** labeled batches from it.

Set:

```bash
export POKER44_PROVIDER=platform
export POKER44_PLATFORM_BACKEND_URL=http://localhost:3001
export POKER44_INTERNAL_EVAL_SECRET=dev-internal-eval-secret
# Optional:
export POKER44_REQUIRE_MIXED=true   # require hands include both HUMAN and BOT seats
export POKER44_AUTOSIMULATE=true   # dev helper: generate hands when buffer is empty

# Optional: announce discoverable rooms (MVP directory)
export POKER44_DIRECTORY_URL=http://localhost:8010
export POKER44_DIRECTORY_SHARED_SECRET=dev-secret
export POKER44_PLATFORM_PUBLIC_URL=http://localhost:3001
```

The backend must expose:
- `GET /internal/eval/next?limit=10&requireMixed=true` (header `x-eval-secret`)
- `POST /internal/eval/simulate` (dev helper to generate mixed hands)
- `POST /internal/rooms/ensure` (ensure a discoverable room code exists)

### One-command local stack

From `poker44-subnet/`:

```bash
chmod +x scripts/validator/p2p/setup.sh
scripts/validator/p2p/setup.sh
```

To stop the local stack:

```bash
chmod +x scripts/validator/p2p/stop.sh
scripts/validator/p2p/stop.sh
```

---

### Register on Testnet (netuid 401)

```bash
# Register your validator on poker44 subnet
btcli subnet register \
  --wallet.name poker44-test \
  --wallet.hotkey default \
  --netuid 401 \
  --subtensor.network test

# Check registration status
btcli wallet overview \
   --wallet.name poker44-test \
   --subtensor.network test
```
---

## ▶️ Run the loop


#### Run validator using pm2
```bash
pm2 start python --name poker44_validator -- \
  ./neurons/validator.py \
  --netuid 401 \
  --wallet.name poker44-test \
  --wallet.hotkey default \
  --subtensor.network test \
  --logging.debug
```

#### Run validator using script
If you want to run it with the help of bash script;
Script for running the validator is at `scripts/validator/run/run_vali.sh`

- Update the hotkey, coldkey, name, network as needed
- Make the script executable: `chmod + x ./scripts/validator/run/run_vali.sh`
- Run the script: `./scripts/validator/run/run_vali.sh`



#### Logs:
```
pm2 logs poker44_validator
```

#### Stop / restart / delete:
```
pm2 stop poker44_validator

pm2 restart poker44_validator

pm2 delete poker44_validator
```


What happens each cycle:

1. Labeled hands (actions, timing, integrity signals) are fetched.
2. A batch is generated consisting of a single hand type & multiple batches are used to create a chunk. 
3. Chunks are dispatched to miners; responses are scored with F1-heavy rewards.
4. Rewards are logged and used to update weights; emissions are allocated with
   a burn bias when no eligible miners respond.

The script currently prints results and sleeps for `poll_interval` seconds before repeating.

---

## 🧭 Road to full validator

- ✅ poker44 ingestion + heuristic scoring loop
- ⏳ Persist receipts + publish weights on-chain
- ⏳ Held-out bot families + early-detection challenges
- ⏳ Dashboarding and operator-facing APIs

Track progress in [docs/roadmap.md](roadmap.md).

---

## 🆘 Help

- Open an issue on GitHub for bugs or missing APIs.
- Reach us on Discord (@sachhp) for any doubts.
