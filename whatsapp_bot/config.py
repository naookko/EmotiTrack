"""Application configuration handling."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

ENV_PATH = Path(__file__).resolve().parent / ".env"
load_dotenv(ENV_PATH, encoding="utf-8-sig")


def _env(key: str, default: str | None = None) -> str:
    value = os.getenv(key, default)
    if value is None:
        raise RuntimeError(f"Missing required environment variable: {key}")
    return value


def _env_duration(key: str) -> Optional[timedelta]:
    raw_value = os.getenv(key)
    if raw_value in (None, ""):
        return None
    parts = raw_value.split(":")
    if len(parts) != 3:
        raise RuntimeError(f"Invalid duration format for {key}; expected HH:MM:SS")
    try:
        hours, minutes, seconds = (int(part) for part in parts)
    except ValueError as exc:
        raise RuntimeError(f"Duration for {key} must be numeric") from exc
    return timedelta(hours=hours, minutes=minutes, seconds=seconds)


@dataclass(frozen=True)
class Settings:
    whatsapp_token: str
    phone_number_id: str
    verify_token: str
    database_path: Path
    cycle_questionary_time: Optional[timedelta]

    @classmethod
    def from_env(cls) -> "Settings":
        base_dir = Path(__file__).resolve().parent
        db_path = Path(os.getenv("DATABASE_PATH", base_dir / "whatsapp.sqlite3"))
        cycle_duration = _env_duration("CYCLE_QUESTIONARY_TIME")
        return cls(
            whatsapp_token=_env("WHATSAPP_TOKEN"),
            phone_number_id=_env("WHATSAPP_PHONE_NUMBER_ID"),
            verify_token=_env("WHATSAPP_VERIFY_TOKEN", ""),
            database_path=db_path,
            cycle_questionary_time=cycle_duration,
        )
