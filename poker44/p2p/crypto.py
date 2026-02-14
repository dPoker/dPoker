import hashlib
import hmac
import json
from typing import Any, Dict


def _canon(obj: Dict[str, Any]) -> bytes:
    # Stable canonical encoding for signing.
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def hmac_sign(payload: Dict[str, Any], secret: str) -> str:
    msg = _canon(payload)
    return hmac.new(secret.encode("utf-8"), msg, hashlib.sha256).hexdigest()


def hmac_verify(payload: Dict[str, Any], secret: str, signature: str) -> bool:
    expected = hmac_sign(payload, secret)
    return hmac.compare_digest(expected, signature)

