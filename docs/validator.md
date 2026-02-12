# 🔐 dpoker Validator Guide

Welcome to dpoker – the poker anti-bot subnet with objective, evolving
evaluation. This guide covers the lean validator scaffold introduced in v0.

> **Goal for v0:** fetch labeled hands from dpoker97.com, query miners, score
> them with F1-centric rewards, and log results. On-chain publishing and
> attestations follow in the next milestone.

---

## ✅ Requirements

- Ubuntu 22.04+ (or any Linux with Python 3.10/3.11 available)
- Python 3.10+

---

## 🛠️ Install

```bash
git clone https://github.com/dPoker/dPoker
cd dPoker
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

___
Validators automatically ingest the labeled hands provided by the dpoker
adapter. Human hands are chosen randomly out of massive dataset whereas bot hands are created on the fly to generate near perfect poker hands. No manual player list is required; the dataset already contains ground truth labels for bots and humans.

---

### Register on Subnet 87

```bash
# Register your validator on dpoker subnet
btcli subnet register \
  --wallet.name ag_cold \
  --wallet.hotkey ag_validator \
  --netuid 87 \
  --subtensor.network finney

# Check registration status
btcli wallet overview \
   --wallet.name ag_cold \
   --subtensor.network finney
```
---

## ▶️ Run the loop


#### Run validator using pm2
```bash
pm2 start python --name dpoker_validator -- \
  ./neurons/validator.py \
  --netuid 87 \
  --wallet.name ag_cold \
  --wallet.hotkey ag_validator \
  --subtensor.network finney \
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
pm2 logs dpoker_validator
```

#### Stop / restart / delete:
```
pm2 stop dpoker_validator

pm2 restart dpoker_validator

pm2 delete dpoker_validator
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

- ✅ dpoker ingestion + heuristic scoring loop
- ⏳ Persist receipts + publish weights on-chain
- ⏳ Held-out bot families + early-detection challenges
- ⏳ Dashboarding and operator-facing APIs

Track progress in [docs/roadmap.md](roadmap.md).

---

## 🆘 Help

- Open an issue on GitHub for bugs or missing APIs.
- Reach us on Discord or X (@dpokersubnet) for any doubts.
