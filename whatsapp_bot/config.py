"""Application configuration handling."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ENV_PATH = Path(__file__).resolve().parent / ".env"
load_dotenv(ENV_PATH, encoding="utf-8-sig")


def _env(key: str, default: str | None = None) -> str:
    value = os.getenv(key, default)
    if value is None:
        raise RuntimeError(f"Missing required environment variable: {key}")
    return value


@dataclass(frozen=True)
class Settings:
    whatsapp_token: str
    phone_number_id: str
    verify_token: str
    database_path: Path

    @classmethod
    def from_env(cls) -> "Settings":
        base_dir = Path(__file__).resolve().parent
        db_path = Path(os.getenv("DATABASE_PATH", base_dir / "whatsapp.sqlite3"))
        return cls(
            whatsapp_token=_env("WHATSAPP_TOKEN"),
            phone_number_id=_env("WHATSAPP_PHONE_NUMBER_ID"),
            verify_token=_env("WHATSAPP_VERIFY_TOKEN", ""),
            database_path=db_path,
        )
