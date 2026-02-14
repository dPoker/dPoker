from __future__ import annotations

from typing import Any, Dict

import pytest

from neurons.validator import PlatformBackendProvider


class _Resp:
    def __init__(self, payload: Dict[str, Any], status_code: int = 200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"status {self.status_code}")

    def json(self) -> Dict[str, Any]:
        return self._payload


def test_platform_backend_provider_fetches_batches(monkeypatch):
    def fake_get(url: str, *, params: Dict[str, Any], headers: Dict[str, str], timeout: float):
        assert url == "http://platform/internal/eval/next"
        assert headers["x-eval-secret"] == "secret"
        assert params["limit"] == 2
        assert params["requireMixed"] == "true"
        assert timeout == pytest.approx(5.0)

        return _Resp(
            {
                "success": True,
                "data": {
                    "batches": [
                        {
                            "is_human": True,
                            "hands": [
                                {"schema": "poker44_eval_hand_v1", "focus_seat": "s1", "events": []}
                            ],
                        }
                    ]
                },
            }
        )

    import neurons.validator as validator_mod

    monkeypatch.setattr(validator_mod.requests, "get", fake_get)

    p = PlatformBackendProvider("http://platform", "secret", require_mixed=True, timeout_s=5.0)
    batches = p.fetch_hand_batch(limit=2)

    assert len(batches) == 1
    assert batches[0].is_human is True
    assert isinstance(batches[0].hands[0], dict)

