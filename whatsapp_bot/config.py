
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
    chat_bot_api_url: str

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            whatsapp_token=_env("WHATSAPP_TOKEN"),
            phone_number_id=_env("WHATSAPP_PHONE_NUMBER_ID"),
            verify_token=_env("WHATSAPP_VERIFY_TOKEN", ""),
            chat_bot_api_url=_env("URL_CHAT_BOT_API"),
        )
