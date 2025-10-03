"""Service layer that handles webhook events."""

from __future__ import annotations

import logging
from typing import Dict, List

from ..models import WebhookLog
from ..repositories.log_repository import LogRepository
from .whatsapp_client import WhatsAppClient

LOGGER = logging.getLogger(__name__)


class WebhookService:
    """Coordinates webhook processing, persistence, and replies."""

    def __init__(self, repository: LogRepository, whatsapp_client: WhatsAppClient) -> None:
        self._repository = repository
        self._whatsapp_client = whatsapp_client

    def process_webhook(self, payload: Dict) -> List[WebhookLog]:
        logs: List[WebhookLog] = []
        message_pairs = [
            (change.get("value", {}), message)
            for entry in payload.get("entry", [])
            for change in entry.get("changes", [])
            for message in change.get("value", {}).get("messages", [])
        ]
        for value, message in message_pairs:
            log = self._log_message(value, message)
            if log is None:
                continue
            logs.append(log)
            self._reply_hello('523325204729')
        return logs

    def _log_message(self, value: Dict, message: Dict) -> WebhookLog | None:
        wa_id = message.get("from")
        if not wa_id:
            LOGGER.debug("Skipping message without wa_id: %s", message)
            return None
        message_text = message.get("text", {}).get("body", "")
        phone_number = value.get("metadata", {}).get("display_phone_number") or value.get("metadata", {}).get("phone_number_id", "")
        status = message.get("type", "received")
        log_entry = WebhookLog(
            wa_id=wa_id,
            input_phone=phone_number,
            message=message_text,
            status=status,
        )
        self._repository.save_webhook_log(log_entry)
        LOGGER.info("Logged webhook for %s", wa_id)
        return log_entry

    def _reply_hello(self, wa_id: str) -> None:
        try:
            self._whatsapp_client.send_text_message(wa_id, f"Hello {wa_id}")
        except Exception as exc:  # pragma: no cover - we want to keep bot running
            LOGGER.exception("Failed to send hello message to %s: %s", wa_id, exc)

    def recent_logs(self, limit: int = 20) -> List[WebhookLog]:
        return self._repository.fetch_recent_webhooks(limit)
