"""Synapse definitions for dpoker miners and validators."""

from __future__ import annotations

from typing import ClassVar, List, Optional

import bittensor as bt
from pydantic import ConfigDict, Field

from dpoker.core.models import HandHistory


class DetectionSynapse(bt.Synapse):
    """
    Carries multiple chunks (batches) of poker hands to a miner and returns bot-risk scores.
    Each chunk gets one risk score/prediction.
    """
    model_config = ConfigDict(arbitrary_types_allowed=True)

    # Tell Bittensor to send chunks in the body, not headers
    required_hash_fields: ClassVar[List[str]] = ["chunks"]

    # List of chunks, where each chunk is a list of hands
    chunks: List[List[dict]] = Field(default_factory=list)
    risk_scores: Optional[List[float]] = None  # One score per chunk
    predictions: Optional[List[bool]] = None   # One prediction per chunk

    def deserialize(self) -> "DetectionSynapse":
        """Deserialize chunks back into HandHistory objects if needed."""
        # Chunks arrive as list of lists of dicts
        # You can keep them as dicts or convert back to HandHistory
        return self