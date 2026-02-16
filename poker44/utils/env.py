from __future__ import annotations

import os
from typing import Optional

from dotenv import load_dotenv

# Load .env once on import (matches the pattern used in autoppia subnets).
load_dotenv()


def _env_str(name: str, default: str = "") -> str:
    """Read a string env var, stripping whitespace."""
    return (os.getenv(name, default) or "").strip()


def _env_bool(name: str, default: bool = False) -> bool:
    """Read a boolean env var with common truthy values."""
    raw = _env_str(name, str(default)).lower()
    return raw in {"y", "yes", "t", "true", "on", "1"}


def _env_int(name: str, default: int = 0, *, test_default: Optional[int] = None) -> int:
    """
    Read an int env var.

    If TESTING=true, allow `TEST_<NAME>` to override, mirroring autoppia's pattern.
    """
    if _env_bool("TESTING", False):
        test_key = f"TEST_{name}"
        v = _env_str(test_key, "")
        if v:
            return int(v)
        if test_default is not None:
            return int(test_default)
    v = _env_str(name, str(default))
    return int(v)


def _env_float(name: str, default: float = 0.0, *, test_default: Optional[float] = None) -> float:
    """
    Read a float env var.

    If TESTING=true, allow `TEST_<NAME>` to override, mirroring autoppia's pattern.
    """
    if _env_bool("TESTING", False):
        test_key = f"TEST_{name}"
        v = _env_str(test_key, "")
        if v:
            return float(v)
        if test_default is not None:
            return float(test_default)
    v = _env_str(name, str(default))
    return float(v)

