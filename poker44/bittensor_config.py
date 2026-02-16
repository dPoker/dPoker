from __future__ import annotations

import argparse
import subprocess
from typing import Literal

import bittensor as bt

from poker44.utils.config import add_args as _add_base_args
from poker44.utils.config import add_miner_args as _add_miner_args
from poker44.utils.config import add_validator_args as _add_validator_args


def _is_cuda_available() -> str:
    """
    Best-effort device detection.
    Returns "cuda" if nvidia-smi/nvcc indicates CUDA is available, else "cpu".
    """
    try:
        out = subprocess.check_output(["nvidia-smi", "-L"], stderr=subprocess.STDOUT)
        if b"NVIDIA" in out:
            return "cuda"
    except Exception:
        pass
    try:
        out = subprocess.check_output(["nvcc", "--version"], stderr=subprocess.STDOUT)
        if b"release" in out:
            return "cuda"
    except Exception:
        pass
    return "cpu"


Role = Literal["auto", "validator", "miner"]


def config(*, role: Role = "auto") -> bt.config:
    """
    Build a bittensor config with explicit, layered arg addition:

    1) Core bittensor + shared subnet args (from `poker44.utils.config.add_args`)
    2) Role-specific args (validator | miner | both)

    This mirrors the pattern used in autoppia subnets: entrypoint scripts build a
    role-configured config and pass it into the neuron constructor.
    """
    parser = argparse.ArgumentParser(conflict_handler="resolve")

    # Base args (wallet/subtensor/logging/axon + shared subnet flags).
    _add_base_args(None, parser)

    # Role-specific defaults/flags.
    role = (role or "auto").lower()
    if role == "validator":
        _add_validator_args(None, parser)
        # Validator should not pick GPU by default.
        parser.set_defaults(**{"neuron.device": "cpu"})
    elif role == "miner":
        _add_miner_args(None, parser)
        parser.set_defaults(**{"neuron.device": _is_cuda_available()})
    else:
        _add_validator_args(None, parser)
        _add_miner_args(None, parser)

    # bittensor exposes `bt.config(parser)` in newer versions, and `bt.Config(parser=...)` in older.
    try:
        return bt.config(parser)
    except Exception:
        return bt.Config(parser=parser)

