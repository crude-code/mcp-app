"""Load .env file from the repo root into os.environ.

Call load_env() at module level in any file that needs environment variables.
Uses setdefault so existing env vars aren't overwritten.
"""

import os
from pathlib import Path

_loaded = False


def load_env() -> None:
    """Load .env from the repo root if it exists. No-op after first call."""
    global _loaded
    if _loaded:
        return
    _loaded = True

    env_path = Path(__file__).resolve().parent.parent / ".env"
    if not env_path.exists():
        return

    for line in env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())
