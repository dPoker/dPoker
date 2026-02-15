from fastapi.testclient import TestClient

from poker44.p2p.indexer.app import app


def test_indexer_bundle_can_be_disabled(monkeypatch):
    monkeypatch.setenv("INDEXER_DISABLE_BUNDLE", "true")
    client = TestClient(app)
    r = client.get("/attestation/bundle")
    assert r.status_code == 404

