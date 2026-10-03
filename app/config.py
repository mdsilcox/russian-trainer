"""App configuration, read from environment variables only.

The Anthropic and Azure Speech keys are never written to disk or logs: it lives in a field
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
    azure_speech_key: str | None = field(default=None, repr=False)
    azure_speech_region: str | None = None
    data_dir: Path = ROOT / "data"
    host: str = "127.0.0.1"
    port: int = 8000

    @property
    def has_api_key(self) -> bool:
        return bool(self.api_key)

    @property
    def has_tts(self) -> bool:
        return bool(self.azure_speech_key and self.azure_speech_region)

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
        azure_speech_key=os.environ.get("AZURE_SPEECH_KEY") or None,
        azure_speech_region=(os.environ.get("AZURE_SPEECH_REGION") or "").strip().lower() or None,
        data_dir=Path(os.environ.get("RT_DATA_DIR", ROOT / "data")),
        host=os.environ.get("RT_HOST", "127.0.0.1"),
        port=int(os.environ.get("RT_PORT", "8000")),
    )
