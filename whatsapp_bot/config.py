
"""Application configuration handling."""

from __future__ import annotations

import os
from dataclasses import dataclass
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


def _env_int(key: str, default: int | None = None) -> int:
    value = _env(key, str(default) if default is not None else None)
    try:
        return int(value)
    except (TypeError, ValueError):
        raise RuntimeError(f"Environment variable {key} must be an integer") from None


@dataclass(frozen=True)
class Settings:
    whatsapp_token: str
    phone_number_id: str
    verify_token: str
    chat_bot_api_url: str
    questionnaire_timeout_minutes: int
    simulation_real_wa_id: Optional[str]
    simulation_wha_ids_file: Optional[Path]

    @classmethod
    def from_env(cls) -> "Settings":
        default_list_path = Path(__file__).resolve().parent.parent / "chat_bot_api" / "list_whaids.txt"
        simulation_real_wa_id = os.getenv("SIMULATION_REAL_WA_ID", "5213325204729").strip()
        simulation_real_wa_id = simulation_real_wa_id or None
        simulation_list_value = os.getenv("SIMULATION_WHA_IDS_FILE")
        simulation_path: Optional[Path] = None
        if simulation_list_value:
            simulation_path = Path(simulation_list_value).expanduser()
        elif default_list_path.exists():
            simulation_path = default_list_path
        return cls(
            whatsapp_token=_env("WHATSAPP_TOKEN"),
            phone_number_id=_env("WHATSAPP_PHONE_NUMBER_ID"),
            verify_token=_env("WHATSAPP_VERIFY_TOKEN", ""),
            chat_bot_api_url=_env("URL_CHAT_BOT_API"),
            questionnaire_timeout_minutes=_env_int("QUESTIONNAIRE_TIMEOUT_MINUTES", 1),
            simulation_real_wa_id=simulation_real_wa_id,
            simulation_wha_ids_file=simulation_path,
        )
