"""Data transfer objects for WhatsApp logging and flow sessions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional


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


@dataclass(frozen=True)
class FlowSession:
    id: int
    wa_id: str
    flow_name: str
    step_index: int
    is_active: bool
    started_at: str
    updated_at: str
    completed_at: Optional[str]
    context: Dict[str, Any]
