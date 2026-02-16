import pytest

from poker44.validator.config import load_validator_env


def test_load_validator_env_defaults_to_local_generated(monkeypatch):
    monkeypatch.delenv("POKER44_PROVIDER", raising=False)
    monkeypatch.delenv("POKER44_PLATFORM_BACKEND_URL", raising=False)
    monkeypatch.delenv("POKER44_INTERNAL_EVAL_SECRET", raising=False)

    cfg = load_validator_env(wallet_hotkey_ss58=None, version="0.0.0")
    assert cfg.provider_mode == "local_generated"
    assert cfg.platform is None
    assert cfg.directory is None
    assert cfg.receipts is None


def test_load_validator_env_requires_platform_urls(monkeypatch):
    monkeypatch.setenv("POKER44_PROVIDER", "platform")
    monkeypatch.delenv("POKER44_PLATFORM_BACKEND_URL", raising=False)
    monkeypatch.delenv("POKER44_INTERNAL_EVAL_SECRET", raising=False)

    with pytest.raises(SystemExit):
        load_validator_env(wallet_hotkey_ss58="hk", version="0.0.0")


def test_load_validator_env_directory_requires_wallet_hotkey(monkeypatch):
    monkeypatch.setenv("POKER44_PROVIDER", "platform")
    monkeypatch.setenv("POKER44_PLATFORM_BACKEND_URL", "http://platform")
    monkeypatch.setenv("POKER44_INTERNAL_EVAL_SECRET", "secret")
    monkeypatch.setenv("POKER44_DIRECTORY_URL", "http://dir")

    with pytest.raises(SystemExit):
        load_validator_env(wallet_hotkey_ss58=None, version="0.0.0")


def test_load_validator_env_directory_validates_validator_id_match(monkeypatch):
    monkeypatch.setenv("POKER44_PROVIDER", "platform")
    monkeypatch.setenv("POKER44_PLATFORM_BACKEND_URL", "http://platform")
    monkeypatch.setenv("POKER44_INTERNAL_EVAL_SECRET", "secret")
    monkeypatch.setenv("POKER44_DIRECTORY_URL", "http://dir")
    monkeypatch.setenv("POKER44_VALIDATOR_ID", "other")

    with pytest.raises(SystemExit):
        load_validator_env(wallet_hotkey_ss58="hk", version="0.0.0")


def test_load_validator_env_receipts_requires_ledger_url(monkeypatch):
    monkeypatch.setenv("POKER44_PROVIDER", "platform")
    monkeypatch.setenv("POKER44_PLATFORM_BACKEND_URL", "http://platform")
    monkeypatch.setenv("POKER44_INTERNAL_EVAL_SECRET", "secret")
    monkeypatch.setenv("POKER44_RECEIPTS_ENABLED", "true")
    monkeypatch.delenv("POKER44_LEDGER_API_URL", raising=False)

    with pytest.raises(SystemExit):
        load_validator_env(wallet_hotkey_ss58="hk", version="0.0.0")

