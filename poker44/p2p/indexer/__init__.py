"""Validator indexer/read-API (MVP).

This package provides a lightweight FastAPI service intended to run on every
validator host. In the full design, it would:
- publish lobby snapshots and attestation bundles to IPFS
- anchor commitments on-chain
- verify peer attestations and expose a canonical directory view

For the current MVP we keep the same shapes, but:
- no IPFS
- no on-chain anchoring
- attestation is mocked via env flags and cross-votes over HTTP
"""

