import bittensor as bt

from poker44.p2p.indexer.signing import sign_payload, verify_payload


def test_indexer_signing_roundtrip():
    kp = bt.Keypair.create_from_seed("01" * 32)
    payload = {"a": 1, "b": "two", "nested": {"x": True}}

    sig = sign_payload(payload, keypair=kp)
    assert isinstance(sig, str) and len(sig) > 0

    assert verify_payload(payload, ss58_address=kp.ss58_address, signature_hex=sig) is True
    assert verify_payload({"a": 2, "b": "two", "nested": {"x": True}}, ss58_address=kp.ss58_address, signature_hex=sig) is False

