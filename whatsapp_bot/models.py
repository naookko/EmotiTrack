"""Data transfer objects for WhatsApp logging."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class WebhookLog:
    wa_id: str
    input_phone: str
    message: str
    status: str
    timestamp: Optional[str] = None


@dataclass(frozen=True)
class AnswerLog:
    wa_id: str
    answer: str
