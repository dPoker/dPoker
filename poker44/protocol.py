"""Protocol (Synapse) definitions for poker44 miners and validators.

This module is the canonical home for the subnet wire protocol. Keep Synapse
types here so miners/validators can import them from a stable path:

  from poker44.protocol import DetectionSynapse
"""

from __future__ import annotations

from typing import ClassVar, List, Optional

import bittensor as bt
from pydantic import ConfigDict, Field


class DetectionSynapse(bt.Synapse):
    """Carry poker evaluation chunks to a miner and receive bot-risk outputs.

    - `chunks`: list of "chunks", where each chunk is a list of hands (dict payloads).
    - `risk_scores`: optional float score per chunk in [0, 1].
    - `predictions`: optional bool prediction per chunk (bot=True).
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    # List of chunks, where each chunk is a list of hands.
    # `required_hash_fields` forces this to be sent in the body (not headers).
    chunks: List[List[dict]] = Field(default_factory=list)
    risk_scores: Optional[List[float]] = None
    predictions: Optional[List[bool]] = None

    # Tell Bittensor to send chunks in the body, not headers.
    required_hash_fields: ClassVar[List[str]] = ["chunks"]

    def deserialize(self) -> "DetectionSynapse":
        # Chunks arrive as list[list[dict]]. Keep as-is; conversion is miner-specific.
        return self

