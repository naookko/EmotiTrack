"""Data transfer objects for WhatsApp logging."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class WebhookLog:
    wa_id: str
    input_phone: str
    message: str
    status: str


@dataclass(frozen=True)
class AnswerLog:
    wa_id: str
    answer: str
