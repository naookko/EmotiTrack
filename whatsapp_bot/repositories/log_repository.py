"""Repositories encapsulating persistence for logs."""

from __future__ import annotations

from typing import Iterable, List

from ..database import Database
from ..models import AnswerLog, WebhookLog


class LogRepository:
    """Provides high-level CRUD operations for log tables."""

    def __init__(self, database: Database) -> None:
        self._db = database

    def save_webhook_log(self, log: WebhookLog) -> None:
        with self._db.connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO log_webhook (wa_id, input, message, status)
                VALUES (?, ?, ?, ?)
                """,
                (log.wa_id, log.input_phone, log.message, log.status),
            )
            conn.commit()

    def save_answer(self, log: AnswerLog) -> None:
        with self._db.connection() as conn:
            conn.execute(
                """
                INSERT INTO log_answers (wa_id, answer)
                VALUES (?, ?)
                """,
                (log.wa_id, log.answer),
            )
            conn.commit()

    def fetch_recent_webhooks(self, limit: int = 20) -> List[WebhookLog]:
        if limit <= 0:
            raise ValueError("limit must be positive")
        with self._db.connection() as conn:
            cursor = conn.execute(
                """
                SELECT wa_id, input, message, status
                FROM log_webhook
                ORDER BY rowid DESC
                LIMIT ?
                """,
                (limit,),
            )
            rows = cursor.fetchall()
        return [WebhookLog(wa_id=row[0], input_phone=row[1], message=row[2], status=row[3]) for row in rows]

    def fetch_answers_for(self, wa_id: str) -> Iterable[AnswerLog]:
        with self._db.connection() as conn:
            cursor = conn.execute(
                """
                SELECT wa_id, answer
                FROM log_answers
                WHERE wa_id = ?
                ORDER BY rowid DESC
                """,
                (wa_id,),
            )
            rows = cursor.fetchall()
        return [AnswerLog(wa_id=row[0], answer=row[1]) for row in rows]
