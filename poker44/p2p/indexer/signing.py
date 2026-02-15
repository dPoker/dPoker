from __future__ import annotations

import json
from typing import Any, Dict

import bittensor as bt


def canon_json(obj: Dict[str, Any]) -> bytes:
    # Stable canonical encoding for signing/verifying.
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def sign_payload(payload: Dict[str, Any], *, keypair: bt.Keypair) -> str:
    msg = canon_json(payload)
    sig = keypair.sign(msg)
    return sig.hex()


def verify_payload(payload: Dict[str, Any], *, ss58_address: str, signature_hex: str) -> bool:
    try:
        sig = bytes.fromhex(signature_hex)
    except Exception:
        return False
    msg = canon_json(payload)
    kp = bt.Keypair(ss58_address=ss58_address)
    try:
        return bool(kp.verify(msg, sig))
    except Exception:
        return False

