"""Asynchronous forward loop for the poker44 validator."""
## poker44/validator/forward.py

from __future__ import annotations

import asyncio
import traceback
import time
import os
import random
from typing import Dict, List, Sequence

import bittensor as bt
import numpy as np
import requests

from poker44.score.scoring import reward
from poker44.protocol import DetectionSynapse

from poker44.validator.constants import BURN_EMISSIONS, BURN_FRACTION, KEEP_FRACTION, UID_ZERO


def _parse_csv_env(name: str) -> list[str]:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return []
    return [x.strip() for x in raw.split(",") if x.strip()]


def _unique_ints(items: list[int]) -> list[int]:
    out: list[int] = []
    seen: set[int] = set()
    for x in items:
        if x in seen:
            continue
        seen.add(x)
        out.append(x)
    return out


def _axon_is_serving(axon) -> bool:  # noqa: ANN001 - depends on bittensor version
    """
    Best-effort axon liveness check.

    On real networks, the metagraph can contain validators (axon_off) or stale
    registrations. Querying non-serving axons creates noisy connection errors.
    """
    try:
        v = getattr(axon, "is_serving", None)
        if v is not None:
            return bool(v)
    except Exception:
        pass

    try:
        ip = str(getattr(axon, "ip", "") or "").strip()
        port = int(getattr(axon, "port", 0) or 0)
        if not ip or ip in ("0.0.0.0",) or port <= 0:
            return False
        return True
    except Exception:
        return False


def _select_miner_uids(validator) -> list[int]:
    """
    Select which miners to query for this forward cycle.

    By default we avoid querying the full metagraph on public networks to keep
    cycles bounded and make testnet/dev easier.

    Overrides:
      - POKER44_QUERY_UIDS="1,2,3"
      - POKER44_QUERY_HOTKEYS="<ss58>,<ss58>"
      - POKER44_QUERY_SAMPLE_SIZE="20"
      - POKER44_QUERY_INCLUDE_SELF="true" (default: false)
    """
    n = int(getattr(validator.metagraph, "n", len(getattr(validator.metagraph, "axons", []))))
    all_uids = list(range(n))

    # Filter to serving axons by default (avoid validators/disabled peers).
    # If we cannot determine serving status (e.g. mocked metagraph in tests),
    # keep the original uid set.
    try:
        axons = getattr(validator.metagraph, "axons", [])
        if axons and len(axons) >= n:
            serving = [u for u in all_uids if _axon_is_serving(axons[u])]
            if serving:
                all_uids = serving
    except Exception:
        pass

    include_self = (os.getenv("POKER44_QUERY_INCLUDE_SELF") or "false").strip().lower() == "true"
    self_uid = getattr(validator, "uid", None)
    if not include_self and isinstance(self_uid, int):
        all_uids = [u for u in all_uids if u != self_uid]

    explicit_uids = _parse_csv_env("POKER44_QUERY_UIDS")
    if explicit_uids:
        picked: list[int] = []
        for raw in explicit_uids:
            try:
                uid = int(raw)
            except Exception:
                continue
            if 0 <= uid < n:
                if not include_self and isinstance(self_uid, int) and uid == self_uid:
                    continue
                picked.append(uid)
        picked = _unique_ints(picked)
        if picked:
            return picked

    explicit_hotkeys = _parse_csv_env("POKER44_QUERY_HOTKEYS")
    if explicit_hotkeys:
        picked = []
        hotkeys = getattr(validator.metagraph, "hotkeys", [])
        for hk in explicit_hotkeys:
            try:
                uid = hotkeys.index(hk)
            except ValueError:
                continue
            if not include_self and isinstance(self_uid, int) and uid == self_uid:
                continue
            if 0 <= uid < n:
                picked.append(uid)
        picked = _unique_ints(picked)
        if picked:
            return picked

    # Default: sample a bounded subset.
    try:
        sample_size = int(os.getenv("POKER44_QUERY_SAMPLE_SIZE") or "20")
    except Exception:
        sample_size = 20
    sample_size = max(1, min(200, sample_size))

    if not all_uids:
        # Edge case: only self exists and include_self=false. Fall back to self if present.
        if include_self and isinstance(self_uid, int):
            return [self_uid]
        return []

    if len(all_uids) <= sample_size:
        return all_uids
    return random.sample(all_uids, sample_size)


async def forward(validator) -> None:
    """Entry point invoked by :class:`neurons.validator.Validator`."""
    try:
        await _run_forward_cycle(validator)
    except Exception:
        bt.logging.error(f"Unexpected error in forward cycle:\n{traceback.format_exc()}")


async def _run_forward_cycle(validator) -> None:
    validator.forward_count = getattr(validator, "forward_count", 0) + 1
    bt.logging.info(f"[Forward #{validator.forward_count}] start")
    
    # Accumulate fresh batches until we reach the requested chunk count (N),
    # then evaluate miners on exactly those N chunks and wait for the next N.
    raw_n = getattr(validator, "task_batch_size", None)
    try:
        n = int(raw_n) if raw_n is not None else int(os.getenv("POKER44_TASK_BATCH_SIZE", "10"))
    except Exception:
        n = 10
    n = max(1, min(200, n))

    # NOTE: forward() may run concurrently (configurable). We only lock around
    # buffer operations to avoid double-consuming tasks.
    lock = getattr(validator, "lock", None)
    batches = None
    buffered = 0
    if lock is not None:
        async with lock:
            pending: List = getattr(validator, "_pending_batches", [])
            if not isinstance(pending, list):
                pending = []

            # Fill the buffer up to N (avoid over-consuming hands from the provider).
            need = max(0, n - len(pending))
            if need > 0:
                new_batches = validator.provider.fetch_hand_batch(limit=need)
                if new_batches:
                    pending.extend(new_batches)
                validator._pending_batches = pending

            buffered = len(pending)
            if buffered >= n:
                batches = pending[:n]
                validator._pending_batches = pending[n:]
    else:
        pending: List = getattr(validator, "_pending_batches", [])
        if not isinstance(pending, list):
            pending = []

        need = max(0, n - len(pending))
        if need > 0:
            new_batches = validator.provider.fetch_hand_batch(limit=need)
            if new_batches:
                pending.extend(new_batches)
            validator._pending_batches = pending

        buffered = len(pending)
        if buffered >= n:
            batches = pending[:n]
            validator._pending_batches = pending[n:]

    if not batches:
        bt.logging.info(f"Buffered {buffered}/{n} eval batches; sleeping.")
        await asyncio.sleep(validator.poll_interval)
        return
    
    axons = validator.metagraph.axons
    miner_uids = _select_miner_uids(validator)
    if not miner_uids:
        bt.logging.info("No miner uids selected; sleeping.")
        await asyncio.sleep(validator.poll_interval)
        return

    pairs = [(int(uid), axons[int(uid)]) for uid in miner_uids if 0 <= int(uid) < len(axons)]
    miner_uids = [uid for uid, _ in pairs]
    axons_to_query = [axon for _, axon in pairs]
    if not miner_uids:
        bt.logging.info("No valid miner uids selected; sleeping.")
        await asyncio.sleep(validator.poll_interval)
        return

    responses: Dict[int, List[float]] = {uid: [] for uid in miner_uids}
    
    # Prepare chunks and labels
    chunks = []  # List of batches (each batch is a list of hand dicts)
    batch_labels = []  # One label per batch
    eval_hand_ids: List[str] = []
    
    for batch in batches:
        # Convert HandHistory objects to dicts
        chunk_dicts = []
        for hand in batch.hands:
            if isinstance(hand, dict):
                chunk_dicts.append(hand)
            else:
                # Assume hand has a to_payload() or to_dict() method
                try:
                    chunk_dicts.append(hand.to_payload())
                except AttributeError:
                    # Fallback: convert dataclass to dict
                    import dataclasses
                    if dataclasses.is_dataclass(hand):
                        chunk_dicts.append(dataclasses.asdict(hand))
                    else:
                        chunk_dicts.append(hand.__dict__)

        # Track eval hand tokens so we can mark them evaluated after scoring.
        for h in chunk_dicts:
            if isinstance(h, dict):
                hid = str(h.get("hand_id") or "").strip()
                if hid:
                    eval_hand_ids.append(hid)
        
        chunks.append(chunk_dicts)
        
        # batch.is_human is False for bots, True for humans
        # We need: 1=bot, 0=human
        batch_label = 0 if batch.is_human else 1
        batch_labels.append(batch_label)

    # Deduplicate to keep the internal call small and idempotent.
    if eval_hand_ids:
        eval_hand_ids = sorted(set(eval_hand_ids))
    
    bt.logging.info(f"Processing {len(chunks)} chunks with labels: {batch_labels} (1=bot, 0=human)")
    bt.logging.info(f"Chunk sizes: {[len(chunk) for chunk in chunks]}")
    
    # Create synapse with all chunks (now as list of dicts)
    synapse = DetectionSynapse(chunks=chunks)
    
    # Get timeout from config
    timeout = 20
    if hasattr(validator.config, "neuron") and hasattr(validator.config.neuron, "timeout"):
        try:
            timeout = float(validator.config.neuron.timeout)
        except (ValueError, TypeError):
            timeout = 20
    
    total_hands = sum(len(chunk) for chunk in chunks)
    bt.logging.info(
        f"Querying {len(axons_to_query)} miners with {len(chunks)} chunks ({total_hands} total hands)..."
    )

    # Collect per-miner transport metadata (best-effort; depends on bittensor version).
    resp_meta_by_uid: Dict[int, Dict[str, float | int | None]] = {}
    
    synapse_responses = await _dendrite_with_retries(
        validator.dendrite,
        axons=axons_to_query,
        synapse=synapse,
        timeout=timeout,
        attempts=3,
    )
    bt.logging.info(f"Received {len(synapse_responses)} responses from miners")
    
    for uid, resp in zip(miner_uids, synapse_responses):
        if resp is None:
            bt.logging.debug(f"Miner {uid} returned None response")
            resp_meta_by_uid[uid] = {"response_time_ms": None, "status_code": None}
            continue

        # Dendrite metadata is optional. Try a few known fields.
        try:
            d = getattr(resp, "dendrite", None)
            status_code = getattr(d, "status_code", None) if d is not None else None
            response_time_ms = getattr(d, "process_time_ms", None) if d is not None else None
            if response_time_ms is None and d is not None:
                pt = getattr(d, "process_time", None)
                if pt is not None:
                    try:
                        response_time_ms = float(pt) * 1000.0
                    except Exception:
                        response_time_ms = None

            rt_ms_int = None
            if response_time_ms is not None:
                try:
                    rt_ms_int = int(round(float(response_time_ms)))
                except Exception:
                    rt_ms_int = None
            resp_meta_by_uid[uid] = {
                "response_time_ms": rt_ms_int,
                "status_code": None if status_code is None else int(status_code),
            }
        except Exception:
            resp_meta_by_uid[uid] = {"response_time_ms": None, "status_code": None}
            
        scores = getattr(resp, "risk_scores", None)
        if scores is None:
            bt.logging.debug(f"Miner {uid} returned no risk_scores")
            continue
            
        try:
            scores_f = [float(s) for s in scores]
            
            # Miners should return one score per chunk
            if len(scores_f) != len(chunks):
                bt.logging.warning(
                    f"Miner {uid} returned {len(scores_f)} scores but expected {len(chunks)} (one per chunk)"
                )
                # Continue anyway, use what we have
                min_len = min(len(scores_f), len(chunks))
                scores_f = scores_f[:min_len]
                effective_labels = batch_labels[:min_len]
            else:
                effective_labels = batch_labels
            
            responses[uid].extend(scores_f)
            
            # Store predictions and labels (one per chunk)
            if not hasattr(validator, "prediction_buffer"):
                validator.prediction_buffer = {}
            if not hasattr(validator, "label_buffer"):
                validator.label_buffer = {}
            
            validator.prediction_buffer.setdefault(uid, []).extend(scores_f)
            validator.label_buffer.setdefault(uid, []).extend(effective_labels)
            
            bt.logging.info(f"Miner {uid} scored {len(scores_f)} chunks successfully")
        except Exception as e:
            bt.logging.warning(f"Error processing response from miner {uid}: {e}")
            import traceback
            bt.logging.debug(traceback.format_exc())
            continue
    
    if not any(responses.values()):
        bt.logging.info("No miner responses this cycle.")
        await asyncio.sleep(validator.poll_interval)
        return
    
    rewards_array, metrics = _compute_windowed_rewards(validator, miner_uids)

    # ---------------------------------------------------------------------
    # Emission burn (optional)
    # ---------------------------------------------------------------------
    #
    # NOTE: `miner_uids` is a *subset* of global metagraph UIDs. If we want to
    # burn emissions to a dedicated UID (commonly UID 0), we must target that
    # UID on the metagraph, not the 0th index of this subset array.
    update_uids = list(miner_uids)
    update_rewards = rewards_array
    metric_rewards = rewards_array

    if BURN_EMISSIONS:
        # Convert queried-miner rewards into a KEEP_FRACTION distribution.
        if metric_rewards.size > 0:
            total_reward = float(np.sum(metric_rewards))
            if total_reward > 0:
                normalized = metric_rewards / total_reward
            else:
                normalized = np.ones_like(metric_rewards) / float(len(metric_rewards))
            metric_rewards = normalized.astype(np.float32) * float(KEEP_FRACTION)

        # Also update the global burn UID with BURN_FRACTION (if it exists on this metagraph).
        metagraph_n = int(
            getattr(validator.metagraph, "n", len(getattr(validator.metagraph, "axons", [])))
        )
        burn_uid = int(UID_ZERO)
        if 0 <= burn_uid < metagraph_n:
            if burn_uid in update_uids:
                # Edge case: burn UID is in the queried set. Allocate BURN_FRACTION
                # to it and re-normalize KEEP_FRACTION across the remaining uids.
                if len(update_uids) == 1:
                    update_rewards = np.asarray([1.0], dtype=np.float32)
                    metric_rewards = update_rewards
                else:
                    burn_idx = update_uids.index(burn_uid)
                    keep_idxs = [i for i, uid in enumerate(update_uids) if uid != burn_uid]
                    keep_raw = rewards_array[keep_idxs]
                    keep_total = float(np.sum(keep_raw))
                    if keep_total > 0:
                        keep_norm = keep_raw / keep_total
                    else:
                        keep_norm = np.ones_like(keep_raw) / float(len(keep_raw))

                    new_rewards = np.zeros_like(rewards_array, dtype=np.float32)
                    new_rewards[keep_idxs] = keep_norm.astype(np.float32) * float(KEEP_FRACTION)
                    new_rewards[burn_idx] = float(BURN_FRACTION)
                    update_rewards = new_rewards
                    metric_rewards = new_rewards
            else:
                update_uids.append(burn_uid)
                update_rewards = np.concatenate(
                    [metric_rewards, np.asarray([float(BURN_FRACTION)], dtype=np.float32)]
                )

            bt.logging.info(
                f"95% burn applied: burn_uid={burn_uid} gets {float(BURN_FRACTION):.4f}, "
                f"queried_miners_share={float(KEEP_FRACTION):.4f}"
            )
        else:
            # Burn UID not present on metagraph; just use the queried-miner distribution.
            update_rewards = metric_rewards

    validator.update_scores(update_rewards, update_uids)

    # Best-effort: persist cycle metrics in the validator-local platform backend for the admin dashboard.
    await _post_cycle_metrics(
        validator=validator,
        miner_uids=miner_uids,
        rewards_array=metric_rewards,
        metrics=metrics,
        batch_count=len(chunks),
        hand_count=total_hands,
        resp_meta_by_uid=resp_meta_by_uid,
    )

    # Best-effort: mark these eval hand_ids as evaluated (post-miner scoring).
    await _mark_eval_hand_ids_evaluated(hand_ids=eval_hand_ids)

    bt.logging.info(f"Rewards issued for {len(miner_uids)} queried miners.")
    bt.logging.info(
        f"[Forward #{validator.forward_count}] complete. Sleeping {validator.poll_interval}s before next tick.",
    )
    await asyncio.sleep(validator.poll_interval)


def _compute_windowed_rewards(validator, miner_uids: List[int]) -> tuple[np.ndarray, list]:
    window = getattr(validator, "reward_window", 20)
    rewards: List[float] = []
    metrics: List[dict] = []

    for uid in miner_uids:
        pred_buf = validator.prediction_buffer.get(uid, [])
        label_buf = validator.label_buffer.get(uid, [])

        if len(pred_buf) < window or len(label_buf) < window:
            rewards.append(0.0)
            metrics.append({"fp_score": 0, "f1_score": 0, "ap_score": 0, "penalty": 0})
            continue

        preds_window = np.asarray(pred_buf[-window:], dtype=float)
        labels_window = np.asarray(label_buf[-window:], dtype=bool)
        rew, metric = reward(preds_window, labels_window)
        metric["penalty"] = 1.0
        rewards.append(rew)
        metrics.append(metric)

    rewards_array = np.asarray(rewards, dtype=np.float32)
    return rewards_array, metrics


async def _post_cycle_metrics(
    *,
    validator,
    miner_uids: List[int],
    rewards_array: np.ndarray,
    metrics: List[dict],
    batch_count: int,
    hand_count: int,
    resp_meta_by_uid: Dict[int, Dict[str, float | int | None]],
) -> None:
    platform_url = (os.getenv("POKER44_PLATFORM_BACKEND_URL") or "").strip().rstrip("/")
    secret = (os.getenv("POKER44_INTERNAL_EVAL_SECRET") or "").strip()
    if not platform_url or not secret:
        return

    validator_id = (os.getenv("POKER44_VALIDATOR_ID") or "").strip() or None
    validator_name = (os.getenv("POKER44_VALIDATOR_NAME") or "poker44-validator").strip() or "poker44-validator"

    # Best-effort net context (nice for dashboards).
    netuid = getattr(getattr(validator, "config", None), "netuid", None)
    network = getattr(getattr(getattr(validator, "config", None), "subtensor", None), "network", None)

    if validator_id is None:
        # Fallback: some validator objects have wallet.hotkey.ss58_address.
        try:
            validator_id = validator.wallet.hotkey.ss58_address
        except Exception:
            validator_id = "unknown"

    miners_payload: list[dict] = []
    hotkeys = getattr(getattr(validator, "metagraph", None), "hotkeys", None)
    scores = getattr(validator, "scores", None)

    def _to_float(v):  # noqa: ANN001 - local helper for JSON-safe casting
        if v is None:
            return None
        try:
            return float(v)
        except Exception:
            return None

    for idx, uid in enumerate(miner_uids):
        hotkey = None
        if isinstance(hotkeys, list) and 0 <= uid < len(hotkeys):
            hotkey = hotkeys[uid]

        moving_score = None
        try:
            if scores is not None and 0 <= uid < len(scores):
                moving_score = float(scores[uid])
        except Exception:
            moving_score = None

        reward_v = float(rewards_array[idx]) if idx < len(rewards_array) else 0.0
        m = metrics[idx] if idx < len(metrics) else {}
        meta = resp_meta_by_uid.get(uid, {})

        miners_payload.append(
            {
                "uid": int(uid),
                "hotkey": hotkey,
                "reward": float(reward_v),
                "moving_score": moving_score,
                "response_time_ms": meta.get("response_time_ms"),
                "f1": _to_float(m.get("f1_score")),
                "ap": _to_float(m.get("ap_score")),
                "fp": _to_float(m.get("fp_score")),
                "penalty": _to_float(m.get("penalty")),
            }
        )

    payload = {
        "validator_id": validator_id,
        "validator_name": validator_name,
        "network": network,
        "netuid": netuid,
        "forward_count": int(getattr(validator, "forward_count", 0)),
        "batch_count": int(batch_count),
        "hand_count": int(hand_count),
        "created_ts": int(time.time()),
        "miners": miners_payload,
    }

    url = f"{platform_url}/internal/metrics/ingest-cycle"

    def _do_post() -> None:
        try:
            requests.post(url, json=payload, headers={"x-eval-secret": secret}, timeout=2.5)
        except Exception:
            # best-effort; ignore
            pass

    try:
        await asyncio.to_thread(_do_post)
    except Exception:
        return


async def _mark_eval_hand_ids_evaluated(*, hand_ids: List[str]) -> None:
    """
    Notify the platform backend that these eval hand tokens were evaluated.

    The platform backend stores sanitized examples when they are reserved; we only
    mark them evaluated after the validator has completed miner scoring for this cycle.
    """
    if not hand_ids:
        return

    platform_url = (os.getenv("POKER44_PLATFORM_BACKEND_URL") or "").strip().rstrip("/")
    secret = (os.getenv("POKER44_INTERNAL_EVAL_SECRET") or "").strip()
    if not platform_url or not secret:
        return

    url = f"{platform_url}/internal/eval/mark-evaluated"

    def _do_post() -> None:
        try:
            requests.post(
                url,
                json={"hand_ids": hand_ids[:500]},
                headers={"x-eval-secret": secret},
                timeout=2.5,
            )
        except Exception:
            # best-effort; ignore
            pass

    try:
        await asyncio.to_thread(_do_post)
    except Exception:
        return


async def _dendrite_with_retries(
    dendrite: bt.dendrite,
    *,
    axons: Sequence,
    synapse: DetectionSynapse,
    timeout: float,
    attempts: int = 3,
):
    """
    Simple retry loop around dendrite calls to avoid transient failures.
    """
    last_exc = None
    for attempt in range(1, attempts + 1):
        try:
            return await dendrite(
                axons=axons,
                synapse=synapse,
                timeout=timeout,
            )
        except Exception as exc:
            last_exc = exc
            bt.logging.warning(f"dendrite attempt {attempt}/{attempts} failed: {exc}")
            await asyncio.sleep(0.5)
    bt.logging.error(f"dendrite retries exhausted: {last_exc}")
    return [None] * len(axons)
