from __future__ import annotations

from typing import Literal, Optional, List, Dict

from pydantic import BaseModel, Field


class AttestationBundle(BaseModel):
    schema: Literal["poker44_attestation_bundle_v0"] = "poker44_attestation_bundle_v0"

    validator_id: str
    validator_name: str

    # MVP: mocked TEE mode. In a real implementation this would be derived from a TEE quote.
    tee_enabled: bool = True
    measurement: str = "mock-measurement"

    epoch: int
    timestamp: int

    # Signature over the canonicalized payload (all fields except signature).
    signature: str


class AttestationVote(BaseModel):
    schema: Literal["poker44_attestation_vote_v0"] = "poker44_attestation_vote_v0"

    voter_id: str
    subject_id: str
    epoch: int
    verdict: Literal["PASS", "FAIL"]
    reason: str = ""

    timestamp: int
    signature: str


class ValidatorStatus(BaseModel):
    validator_id: str
    validator_name: str

    platform_url: str
    indexer_url: Optional[str] = None
    room_code: Optional[str] = None

    last_seen: int = 0

    # Metagraph-derived info (best-effort).
    uid: Optional[int] = None
    stake_tao: Optional[float] = None
    validator_permit: Optional[bool] = None

    # Attestation-derived status.
    tee_enabled: Optional[bool] = None
    votes_pass: int = 0
    votes_fail: int = 0
    quorum: int = 0
    attested: bool = False
    danger_reason: str = ""


class DirectoryState(BaseModel):
    schema: Literal["poker44_directory_state_v0"] = "poker44_directory_state_v0"

    epoch: int
    validators: List[ValidatorStatus] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)

    # Small debug surface for clients.
    meta: Dict[str, str] = Field(default_factory=dict)
