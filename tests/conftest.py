import sys
from pathlib import Path

# Ensure repo root is on sys.path so `import poker44` works under all pytest import modes.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Silence noisy atexit logging from torch (can emit after pytest closes capture streams).
import logging  # noqa: E402

logging.getLogger("torch._subclasses.fake_tensor").disabled = True

try:  # pragma: no cover - best-effort test hygiene
    import atexit  # noqa: E402
    import torch._subclasses.fake_tensor as _ft  # noqa: E402

    # Torch registers this via `@atexit.register`; remove it so pytest shutdown is clean.
    atexit.unregister(_ft.dump_cache_stats)
except Exception:
    pass
