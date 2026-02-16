"""Compatibility shim for the poker44 Synapse protocol.

The canonical protocol definitions live in `poker44.protocol`.
This file remains to avoid breaking external imports.
"""

from poker44.protocol import DetectionSynapse

__all__ = ["DetectionSynapse"]
