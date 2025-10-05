
"""Repositories encapsulating persistence for logs (in-memory variant)."""

from __future__ import annotations

from typing import Iterable, List

from ..models import AnswerLog, WebhookLog


class LogRepository:
    """Provides high-level CRUD operations for log tables using in-memory storage."""

    def __init__(self) -> None:
        self._webhooks: List[WebhookLog] = []
        self._answers: List[AnswerLog] = []

    def save_webhook_log(self, log: WebhookLog) -> None:
        self._webhooks.append(log)

    def conversation_exists(self, wa_id: str) -> bool:
        return any(entry.wa_id == wa_id for entry in self._webhooks)

    def save_answer(self, log: AnswerLog) -> None:
        self._answers.append(log)

    def fetch_recent_webhooks(self, limit: int = 20) -> List[WebhookLog]:
        if limit <= 0:
            raise ValueError("limit must be positive")
        return list(reversed(self._webhooks[-limit:]))

    def fetch_all_webhooks(self) -> List[WebhookLog]:
        return list(reversed(self._webhooks))

    def fetch_answers_for(self, wa_id: str) -> Iterable[AnswerLog]:
        return [answer for answer in self._answers if answer.wa_id == wa_id]

    def fetch_all_answers(self) -> List[AnswerLog]:
        return list(self._answers)

    def delete_all_data(self) -> None:
        self._webhooks.clear()
        self._answers.clear()
