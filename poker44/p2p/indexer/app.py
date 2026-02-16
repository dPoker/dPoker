from __future__ import annotations

import os
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

import bittensor as bt
import requests
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from poker44.p2p.schemas import RoomListing
from poker44.p2p.indexer.schemas import (
    AttestationBundle,
    AttestationVote,
    DirectoryState,
    ValidatorStatus,
)
from poker44.p2p.indexer.signing import sign_payload, verify_payload
from poker44.p2p.indexer.quorum import majority_quorum


def _bool_env(key: str, default: bool) -> bool:
    raw = (os.getenv(key) or "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "y", "on")


def _int_env(key: str, default: int) -> int:
    try:
        return int(os.getenv(key) or str(default))
    except Exception:
        return default


def _epoch(now_ts: int, epoch_seconds: int) -> int:
    s = max(5, int(epoch_seconds))
    return int(now_ts // s)

_METAGRAPH_CACHE: Dict[str, Any] = {"ts": 0.0, "network": "", "netuid": 0, "mg": None}
_STATE_CACHE: Dict[str, Any] = {"ts": 0.0, "epoch": None, "state": None}


def _metagraph_config() -> Tuple[str, int]:
    network = (os.getenv("INDEXER_SUBTENSOR_NETWORK") or os.getenv("SUBTENSOR_NETWORK") or "").strip()
    if not network:
        network = "test"
    netuid = _int_env("INDEXER_NETUID", _int_env("NETUID", 0))
    return network, int(netuid)


def _get_metagraph(*, ttl_s: int = 30, allow_fetch: bool = True) -> Optional[Any]:
    try:
        network, netuid = _metagraph_config()
        if netuid <= 0:
            return None
        now = time.time()
        if (
            _METAGRAPH_CACHE.get("mg") is not None
            and _METAGRAPH_CACHE.get("network") == network
            and int(_METAGRAPH_CACHE.get("netuid") or 0) == int(netuid)
            and (now - float(_METAGRAPH_CACHE.get("ts") or 0.0)) <= float(ttl_s)
        ):
            return _METAGRAPH_CACHE.get("mg")

        if not allow_fetch:
            return None

        # Bittensor SDK changed around v10: `bt.subtensor()` was replaced by `bt.Subtensor`.
        subtensor = bt.subtensor(network=network) if hasattr(bt, "subtensor") else bt.Subtensor(network=network)
        mg = subtensor.metagraph(netuid=netuid)
        _METAGRAPH_CACHE.update({"ts": now, "network": network, "netuid": int(netuid), "mg": mg})
        return mg
    except Exception:
        return None


def _metagraph_row(hotkey: str) -> Tuple[Optional[int], Optional[float], Optional[bool]]:
    # Never block request handlers on an on-chain fetch; metagraph is warmed in the background.
    mg = _get_metagraph(allow_fetch=False)
    if mg is None:
        return None, None, None
    try:
        uid = mg.hotkeys.index(hotkey)
    except Exception:
        return None, None, None

    stake = None
    try:
        stake = float(mg.S[uid])
    except Exception:
        stake = None

    permit = None
    try:
        permit = bool(mg.validator_permit[uid])
    except Exception:
        permit = None

    return int(uid), stake, permit


def _canon_bundle_payload(d: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(d)
    out.pop("signature", None)
    return out


def _canon_vote_payload(d: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(d)
    out.pop("signature", None)
    return out


def _fetch_json(url: str, timeout_s: float = 2.5) -> Optional[Any]:
    try:
        r = requests.get(url, timeout=timeout_s)
        r.raise_for_status()
        return r.json()
    except Exception:
        return None


def _list_directory_rooms(directory_url: str) -> List[RoomListing]:
    if not directory_url:
        return []
    data = _fetch_json(f"{directory_url.rstrip('/')}/rooms", timeout_s=2.5)
    if not isinstance(data, list):
        return []
    out: List[RoomListing] = []
    for item in data:
        try:
            r = RoomListing(**item)
        except Exception:
            continue

        # Verify that this room listing was announced by the validator hotkey.
        # The directory itself is a lightweight store; indexers are the trust gate.
        try:
            now = int(time.time())
            if abs(now - int(r.timestamp)) > 300:
                continue

            payload = {
                "validator_id": r.validator_id,
                "validator_name": r.validator_name,
                "platform_url": r.platform_url,
                "indexer_url": r.indexer_url,
                "room_code": r.room_code,
                "region": r.region,
                "capacity_tables": int(r.capacity_tables),
                "version_hash": r.version_hash,
                "timestamp": int(r.timestamp),
            }
            if not verify_payload(payload, ss58_address=r.validator_id, signature_hex=r.signature):
                continue
        except Exception:
            continue

        out.append(r)
    return out


def _get_keypair() -> bt.Keypair:
    wallet_name = (os.getenv("INDEXER_WALLET_NAME") or os.getenv("VALIDATOR_WALLET") or "").strip()
    hotkey_name = (os.getenv("INDEXER_WALLET_HOTKEY") or os.getenv("VALIDATOR_HOTKEY") or "").strip()
    if not wallet_name or not hotkey_name:
        raise RuntimeError("Missing INDEXER_WALLET_NAME/INDEXER_WALLET_HOTKEY (or VALIDATOR_WALLET/VALIDATOR_HOTKEY)")
    w = bt.Wallet(name=wallet_name, hotkey=hotkey_name)
    return w.hotkey


def _self_identity() -> Tuple[str, str]:
    # Allow overriding validator_id for dev/mocked setups.
    validator_id = (os.getenv("INDEXER_VALIDATOR_ID") or "").strip()
    validator_name = (os.getenv("INDEXER_VALIDATOR_NAME") or os.getenv("POKER44_VALIDATOR_NAME") or "poker44-validator").strip() or "poker44-validator"

    if validator_id:
        return validator_id, validator_name

    kp = _get_keypair()
    return kp.ss58_address, validator_name


def _build_bundle(now: int, epoch_seconds: int) -> AttestationBundle:
    validator_id, validator_name = _self_identity()
    e = _epoch(now, epoch_seconds)

    tee_enabled = _bool_env("INDEXER_TEE_ENABLED", True)
    measurement = (os.getenv("INDEXER_MEASUREMENT") or "mock-measurement").strip() or "mock-measurement"

    payload = {
        "schema": "poker44_attestation_bundle_v0",
        "validator_id": validator_id,
        "validator_name": validator_name,
        "tee_enabled": bool(tee_enabled),
        "measurement": measurement,
        "epoch": int(e),
        "timestamp": int(now),
    }

    kp = _get_keypair()
    sig = sign_payload(_canon_bundle_payload(payload), keypair=kp)
    return AttestationBundle(**payload, signature=sig)


def _fetch_peer_bundle(indexer_url: str, *, expected_validator_id: Optional[str] = None) -> Optional[AttestationBundle]:
    if not indexer_url:
        return None
    data = _fetch_json(f"{indexer_url.rstrip('/')}/attestation/bundle", timeout_s=2.5)
    if not isinstance(data, dict):
        return None
    try:
        b = AttestationBundle(**data)
    except Exception:
        return None

    if expected_validator_id and b.validator_id != expected_validator_id:
        return None

    payload = _canon_bundle_payload(b.model_dump())
    if not verify_payload(payload, ss58_address=b.validator_id, signature_hex=b.signature):
        return None
    return b


def _vote_on_subject(*, voter_id: str, subject: RoomListing, epoch: int) -> AttestationVote:
    now = int(time.time())
    subject_id = subject.validator_id

    verdict: str = "FAIL"
    reason = ""

    if not subject.indexer_url:
        verdict = "FAIL"
        reason = "missing_indexer_url"
    else:
        bundle = _fetch_peer_bundle(subject.indexer_url, expected_validator_id=subject_id)
        if not bundle:
            verdict = "FAIL"
            reason = "bundle_unreachable_or_invalid"
        elif not bundle.tee_enabled:
            verdict = "FAIL"
            reason = "tee_disabled"
        else:
            verdict = "PASS"
            reason = ""

    payload = {
        "schema": "poker44_attestation_vote_v0",
        "voter_id": voter_id,
        "subject_id": subject_id,
        "epoch": int(epoch),
        "verdict": verdict,
        "reason": reason,
        "timestamp": int(now),
    }
    kp = _get_keypair()
    sig = sign_payload(_canon_vote_payload(payload), keypair=kp)
    return AttestationVote(**payload, signature=sig)


def _fetch_votes_from_voter(
    voter_indexer_url: str,
    *,
    expected_voter_id: str,
    epoch: int,
) -> List[AttestationVote]:
    data = _fetch_json(f"{voter_indexer_url.rstrip('/')}/attestation/votes?epoch={int(epoch)}", timeout_s=2.5)
    if not isinstance(data, list):
        return []
    out: List[AttestationVote] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        try:
            v = AttestationVote(**item)
        except Exception:
            continue
        if v.voter_id != expected_voter_id:
            continue
        if v.epoch != int(epoch):
            continue
        # Verify voter signature.
        payload = _canon_vote_payload(v.model_dump())
        if not verify_payload(payload, ss58_address=v.voter_id, signature_hex=v.signature):
            continue
        out.append(v)
    return out


def _compute_directory_state(directory_url: str, *, epoch_seconds: int) -> DirectoryState:
    now = int(time.time())
    e = _epoch(now, epoch_seconds)

    rooms = _list_directory_rooms(directory_url)
    warnings: List[str] = []

    # Best-effort metagraph snapshot (stake/permit). We never block request handlers
    # on an on-chain fetch; a background worker warms the cache.
    mg = _get_metagraph(allow_fetch=False)
    if mg is None:
        # Fallback: if the background warmer hasn't populated the cache (or startup events are disabled),
        # do a best-effort on-demand fetch. This happens at most once per metagraph TTL.
        mg = _get_metagraph(allow_fetch=True)

    # Voter set: validators with an indexer_url (from directory).
    voter_rooms = [r for r in rooms if r.indexer_url]
    voter_indexers = [r.indexer_url for r in voter_rooms if r.indexer_url]
    n_validators = len(voter_rooms) if voter_rooms else len(rooms)
    q = majority_quorum(n_validators)

    # Collect votes from each voter indexer (best-effort).
    votes_by_voter: Dict[str, List[AttestationVote]] = {}
    for r in voter_rooms:
        if not r.indexer_url:
            continue
        votes = _fetch_votes_from_voter(r.indexer_url, expected_voter_id=r.validator_id, epoch=e)
        votes_by_voter[r.validator_id] = votes

    # Build status per validator.
    statuses: List[ValidatorStatus] = []
    for r in rooms:
        uid: Optional[int] = None
        stake_tao: Optional[float] = None
        permit: Optional[bool] = None
        if mg is not None:
            uid, stake_tao, permit = _metagraph_row(r.validator_id)

        votes_pass = 0
        votes_fail = 0

        # Derive tee_enabled from subject bundle (best-effort).
        tee_enabled: Optional[bool] = None
        if r.indexer_url:
            b = _fetch_peer_bundle(r.indexer_url, expected_validator_id=r.validator_id)
            tee_enabled = b.tee_enabled if b else None

        # Count votes from other validators.
        for voter_id, votes in votes_by_voter.items():
            if voter_id == r.validator_id:
                continue
            for v in votes:
                if v.subject_id != r.validator_id:
                    continue
                if v.verdict == "PASS":
                    votes_pass += 1
                else:
                    votes_fail += 1

        attested = False
        danger_reason = ""

        if tee_enabled is False:
            danger_reason = "tee_disabled"
        elif tee_enabled is None:
            danger_reason = "missing_or_invalid_bundle"
        elif q <= 0:
            danger_reason = "insufficient_validator_set"
        elif votes_pass >= q:
            attested = True
        else:
            danger_reason = f"quorum_not_met(pass={votes_pass}, need={q})"

        statuses.append(
            ValidatorStatus(
                validator_id=r.validator_id,
                validator_name=r.validator_name,
                platform_url=r.platform_url,
                indexer_url=r.indexer_url,
                room_code=r.room_code,
                last_seen=r.last_seen,
                uid=uid,
                stake_tao=stake_tao,
                validator_permit=permit,
                tee_enabled=tee_enabled,
                votes_pass=votes_pass,
                votes_fail=votes_fail,
                quorum=q,
                attested=attested,
                danger_reason=danger_reason,
            )
        )

    # Stable ordering for client comparisons.
    statuses.sort(key=lambda s: (s.attested, s.last_seen), reverse=True)

    return DirectoryState(
        epoch=e,
        validators=statuses,
        warnings=warnings,
        meta={
            "directory_url": directory_url,
            "validators_seen": str(len(rooms)),
            "voters_seen": str(len(voter_rooms)),
        },
    )


def _state_cache_ttl_s() -> int:
    return max(0, _int_env("INDEXER_STATE_CACHE_TTL_S", 5))


def _compute_directory_state_cached(directory_url: str, *, epoch_seconds: int) -> DirectoryState:
    """
    Cache the full directory state for a short TTL to keep /attestation/status responsive.
    """
    ttl_s = float(_state_cache_ttl_s())
    now_ts = int(time.time())
    e = _epoch(now_ts, epoch_seconds)

    if ttl_s > 0:
        cached = _STATE_CACHE.get("state")
        cached_epoch = _STATE_CACHE.get("epoch")
        cached_ts = float(_STATE_CACHE.get("ts") or 0.0)
        if cached is not None and int(cached_epoch or -1) == int(e) and (time.time() - cached_ts) <= ttl_s:
            return cached

    state = _compute_directory_state(directory_url, epoch_seconds=epoch_seconds)
    if ttl_s > 0:
        _STATE_CACHE.update({"ts": time.time(), "epoch": e, "state": state})
    return state


app = FastAPI(title="poker44 Validator Indexer", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def _startup_background_tasks() -> None:
    # Warm on-chain metagraph data in the background so read APIs stay fast.
    network, netuid = _metagraph_config()
    if netuid <= 0:
        return
    if not _bool_env("INDEXER_ENABLE_METAGRAPH_WARM", True):
        return

    poll_s = max(5, _int_env("INDEXER_METAGRAPH_POLL_S", 10))
    ttl_s = max(5, _int_env("INDEXER_METAGRAPH_TTL_S", 30))

    def _loop() -> None:
        while True:
            _get_metagraph(ttl_s=ttl_s, allow_fetch=True)
            time.sleep(poll_s)

    threading.Thread(target=_loop, daemon=True).start()


@app.get("/healthz")
def healthz():
    now = int(time.time())
    epoch_seconds = _int_env("INDEXER_EPOCH_SECONDS", 60)
    vid, vname = _self_identity()
    return {
        "ok": True,
        "validator_id": vid,
        "validator_name": vname,
        "tee_enabled": _bool_env("INDEXER_TEE_ENABLED", True),
        "bundle_enabled": not _bool_env("INDEXER_DISABLE_BUNDLE", False),
        "epoch": _epoch(now, epoch_seconds),
    }


@app.get("/attestation/bundle", response_model=AttestationBundle)
def attestation_bundle():
    if _bool_env("INDEXER_DISABLE_BUNDLE", False):
        # Simulate a validator that is not publishing attestations at all.
        raise HTTPException(status_code=404, detail="Attestation bundle disabled")
    now = int(time.time())
    epoch_seconds = _int_env("INDEXER_EPOCH_SECONDS", 60)
    return _build_bundle(now, epoch_seconds)


@app.get("/attestation/votes", response_model=list[AttestationVote])
def attestation_votes(epoch: Optional[int] = None):
    directory_url = (os.getenv("INDEXER_DIRECTORY_URL") or os.getenv("POKER44_DIRECTORY_URL") or "").strip().rstrip("/")
    epoch_seconds = _int_env("INDEXER_EPOCH_SECONDS", 60)
    now = int(time.time())
    e = int(epoch) if epoch is not None else _epoch(now, epoch_seconds)

    voter_id, _ = _self_identity()
    rooms = _list_directory_rooms(directory_url)
    out: List[AttestationVote] = []
    for r in rooms:
        # Do not vote on ourselves; in the design, attestations are cross-validated.
        if r.validator_id == voter_id:
            continue
        out.append(_vote_on_subject(voter_id=voter_id, subject=r, epoch=e))
    return out


@app.get("/directory/state", response_model=DirectoryState)
def directory_state():
    directory_url = (os.getenv("INDEXER_DIRECTORY_URL") or os.getenv("POKER44_DIRECTORY_URL") or "").strip().rstrip("/")
    epoch_seconds = _int_env("INDEXER_EPOCH_SECONDS", 60)
    return _compute_directory_state_cached(directory_url, epoch_seconds=epoch_seconds)


@app.get("/attestation/status/{validator_id}", response_model=ValidatorStatus)
def attestation_status(validator_id: str):
    directory_url = (os.getenv("INDEXER_DIRECTORY_URL") or os.getenv("POKER44_DIRECTORY_URL") or "").strip().rstrip("/")
    epoch_seconds = _int_env("INDEXER_EPOCH_SECONDS", 60)
    state = _compute_directory_state_cached(directory_url, epoch_seconds=epoch_seconds)
    for v in state.validators:
        if v.validator_id == validator_id:
            return v
    # Return a synthetic "missing" status rather than 404 to keep clients simple.
    return ValidatorStatus(
        validator_id=validator_id,
        validator_name="unknown",
        platform_url="",
        indexer_url=None,
        room_code=None,
        last_seen=0,
        tee_enabled=None,
        votes_pass=0,
        votes_fail=0,
        quorum=majority_quorum(len(state.validators)),
        attested=False,
        danger_reason="not_in_directory",
    )
