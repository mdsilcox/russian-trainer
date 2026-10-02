"""App configuration, read from environment variables only.

The Anthropic key is never written to disk or logs: it lives in a field
excluded from repr, and only `has_api_key` is exposed to templates.
"""

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Config:
    api_key: str | None = field(default=None, repr=False)
    data_dir: Path = ROOT / "data"
    host: str = "127.0.0.1"
    port: int = 8000

    @property
    def has_api_key(self) -> bool:
        return bool(self.api_key)

    @property
    def db_path(self) -> Path:
        return self.data_dir / "russian.db"

    @property
    def backup_dir(self) -> Path:
        return ROOT / "backups"


@lru_cache
def get_config() -> Config:
    return Config(
        api_key=os.environ.get("ANTHROPIC_API_KEY") or None,
        data_dir=Path(os.environ.get("RT_DATA_DIR", ROOT / "data")),
        host=os.environ.get("RT_HOST", "127.0.0.1"),
        port=int(os.environ.get("RT_PORT", "8000")),
    )
