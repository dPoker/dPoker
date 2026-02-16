from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional

from poker44.utils.env import _env_bool, _env_float, _env_int, _env_str


ProviderMode = Literal["platform", "local_generated"]


@dataclass(frozen=True)
class PlatformProviderConfig:
    base_url: str
    internal_eval_secret: str
    require_mixed: bool
    timeout_s: float
    autosimulate: bool
    simulate_humans: int
    simulate_bots: int
    simulate_hands: int
    simulate_timeout_s: float
    min_simulate_interval_s: int


@dataclass(frozen=True)
class DirectoryAnnounceConfig:
    directory_url: str
    validator_id: str
    validator_name: str
    region: str
    capacity_tables: int
    version_hash: str
    announce_interval_s: int
    platform_public_url: str
    indexer_public_url: Optional[str]
    room_code: Optional[str]


@dataclass(frozen=True)
class ReceiptsForwarderConfig:
    enabled: bool
    ledger_api_url: str
    poll_s: float
    limit: int


@dataclass(frozen=True)
class ValidatorEnvConfig:
    provider_mode: ProviderMode
    platform: Optional[PlatformProviderConfig]
    directory: Optional[DirectoryAnnounceConfig]
    receipts: Optional[ReceiptsForwarderConfig]


def _die(msg: str) -> None:
    raise SystemExit(f"[poker44] {msg}")


def load_validator_env(
    *,
    wallet_hotkey_ss58: Optional[str],
    version: str,
) -> ValidatorEnvConfig:
    """
    Load validator configuration from env/.env with strict validation.

    This centralizes all validator env parsing (mirrors the pattern used in
    autoppia subnets: `validator/config.py` + env helpers).
    """
    provider_raw = (_env_str("POKER44_PROVIDER", "local_generated") or "local_generated").lower()
    if provider_raw not in ("platform", "local_generated"):
        _die(f"Invalid POKER44_PROVIDER={provider_raw!r} (expected 'platform' or 'local_generated').")
    provider_mode: ProviderMode = "platform" if provider_raw == "platform" else "local_generated"

    platform_cfg: Optional[PlatformProviderConfig] = None
    if provider_mode == "platform":
        base_url = _env_str("POKER44_PLATFORM_BACKEND_URL", "")
        secret = _env_str("POKER44_INTERNAL_EVAL_SECRET", "")
        if not base_url:
            _die("Missing required env var: POKER44_PLATFORM_BACKEND_URL (required when POKER44_PROVIDER=platform).")
        if not secret:
            _die("Missing required env var: POKER44_INTERNAL_EVAL_SECRET (required when POKER44_PROVIDER=platform).")

        platform_cfg = PlatformProviderConfig(
            base_url=base_url.rstrip("/"),
            internal_eval_secret=secret,
            require_mixed=_env_bool("POKER44_REQUIRE_MIXED", True),
            timeout_s=_env_float("POKER44_PLATFORM_TIMEOUT_S", 5.0),
            autosimulate=_env_bool("POKER44_AUTOSIMULATE", False),
            simulate_humans=_env_int("POKER44_AUTOSIMULATE_HUMANS", 2),
            simulate_bots=_env_int("POKER44_AUTOSIMULATE_BOTS", 2),
            simulate_hands=_env_int("POKER44_AUTOSIMULATE_HANDS", 3),
            simulate_timeout_s=_env_float("POKER44_AUTOSIMULATE_TIMEOUT_S", 30.0),
            min_simulate_interval_s=_env_int("POKER44_AUTOSIMULATE_MIN_INTERVAL_S", 15),
        )

    # Directory announcements are optional.
    directory_url = _env_str("POKER44_DIRECTORY_URL", "").rstrip("/")
    directory_cfg: Optional[DirectoryAnnounceConfig] = None
    if directory_url:
        if provider_mode != "platform":
            _die("POKER44_DIRECTORY_URL is set but POKER44_PROVIDER != 'platform'. Only platform-backed validators can announce rooms.")
        if not directory_url.startswith("http"):
            _die(f"POKER44_DIRECTORY_URL must be http(s). Got: {directory_url!r}")
        if not wallet_hotkey_ss58:
            _die("wallet_hotkey_ss58 is required to validate directory announcements.")

        env_validator_id = _env_str("POKER44_VALIDATOR_ID", "")
        if env_validator_id and env_validator_id != wallet_hotkey_ss58:
            _die(
                "POKER44_VALIDATOR_ID must match the validator hotkey ss58 address. "
                f"Got {env_validator_id!r}, expected {wallet_hotkey_ss58!r}."
            )

        validator_name = _env_str("POKER44_VALIDATOR_NAME", "poker44-validator") or "poker44-validator"
        region = _env_str("POKER44_REGION", "unknown") or "unknown"
        capacity_tables = _env_int("POKER44_CAPACITY_TABLES", 1)
        version_hash = _env_str("POKER44_VERSION_HASH", f"poker44-validator-{version}") or f"poker44-validator-{version}"
        announce_interval_s = max(1, _env_int("POKER44_ANNOUNCE_INTERVAL_S", 10))

        if platform_cfg is None:
            _die("Internal error: platform config missing while directory announcements enabled.")
        platform_public_url = (_env_str("POKER44_PLATFORM_PUBLIC_URL", platform_cfg.base_url) or platform_cfg.base_url).rstrip("/")
        if platform_public_url and not platform_public_url.startswith("http"):
            _die(f"POKER44_PLATFORM_PUBLIC_URL must be http(s). Got: {platform_public_url!r}")

        indexer_public_url = (_env_str("POKER44_INDEXER_PUBLIC_URL", "") or "").rstrip("/") or None
        if indexer_public_url and not indexer_public_url.startswith("http"):
            _die(f"POKER44_INDEXER_PUBLIC_URL must be http(s). Got: {indexer_public_url!r}")

        room_code = (_env_str("POKER44_ROOM_CODE", "") or "").strip() or None

        directory_cfg = DirectoryAnnounceConfig(
            directory_url=directory_url,
            validator_id=wallet_hotkey_ss58,
            validator_name=validator_name,
            region=region,
            capacity_tables=int(capacity_tables),
            version_hash=version_hash,
            announce_interval_s=int(announce_interval_s),
            platform_public_url=platform_public_url,
            indexer_public_url=indexer_public_url,
            room_code=room_code,
        )

    # Receipts forwarding is optional.
    receipts_enabled = _env_bool("POKER44_RECEIPTS_ENABLED", False)
    receipts_cfg: Optional[ReceiptsForwarderConfig] = None
    if receipts_enabled:
        if provider_mode != "platform":
            _die("POKER44_RECEIPTS_ENABLED=true requires POKER44_PROVIDER=platform.")
        ledger_api_url = _env_str("POKER44_LEDGER_API_URL", "").rstrip("/")
        if not ledger_api_url:
            _die("Missing required env var: POKER44_LEDGER_API_URL (required when POKER44_RECEIPTS_ENABLED=true).")

        poll_s = _env_float("POKER44_RECEIPTS_POLL_S", 3.0)
        poll_s = max(0.5, min(60.0, poll_s))
        limit = _env_int("POKER44_RECEIPTS_LIMIT", 100)
        limit = max(1, min(500, limit))

        receipts_cfg = ReceiptsForwarderConfig(
            enabled=True,
            ledger_api_url=ledger_api_url,
            poll_s=float(poll_s),
            limit=int(limit),
        )

    return ValidatorEnvConfig(
        provider_mode=provider_mode,
        platform=platform_cfg,
        directory=directory_cfg,
        receipts=receipts_cfg,
    )

