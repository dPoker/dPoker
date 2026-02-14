from poker44.p2p.crypto import hmac_sign, hmac_verify


def test_hmac_roundtrip():
    payload = {"a": 1, "b": "x"}
    secret = "s3cr3t"
    sig = hmac_sign(payload, secret)
    assert hmac_verify(payload, secret, sig)
    assert not hmac_verify(payload, "wrong", sig)

