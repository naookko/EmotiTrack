"""Service layer that handles webhook events."""

from __future__ import annotations

import logging
from typing import Dict, List, Optional, Tuple

from ..models import WebhookLog
from ..repositories.log_repository import LogRepository
from .whatsapp_client import WhatsAppClient

LOGGER = logging.getLogger(__name__)


class WebhookService:
    """Coordinates webhook processing, persistence, and replies."""

    DEFAULT_WA_ID = "5213325204729"

    def __init__(self, repository: LogRepository, whatsapp_client: WhatsAppClient) -> None:
        self._repository = repository
        self._whatsapp_client = whatsapp_client

    def process_webhook(self, payload: Dict) -> List[WebhookLog]:
        logs: List[WebhookLog] = []
        message_events = [
            ("message", change.get("value", {}), message)
            for entry in payload.get("entry", [])
            for change in entry.get("changes", [])
            for message in change.get("value", {}).get("messages", [])
        ]
        status_events = [
            ("status", change.get("value", {}), status)
            for entry in payload.get("entry", [])
            for change in entry.get("changes", [])
            for status in change.get("value", {}).get("statuses", [])
        ]

        for event_type, value, item in message_events + status_events:
            result = self._log_event(event_type, value, item)
            if not result:
                continue
            log_entry, is_new = result
            logs.append(log_entry)
            if is_new:
                self._handle_new_conversation(log_entry.wa_id)
            elif event_type == "message":
                self._reply_hello(log_entry.wa_id)
        return logs

    def _log_event(self, event_type: str, value: Dict, item: Dict) -> Optional[Tuple[WebhookLog, bool]]:
        wa_id = self._resolve_wa_id(event_type, item)
        if not wa_id:
            LOGGER.warning("Could not resolve wa_id for event %s; using default", event_type)
            wa_id = self.DEFAULT_WA_ID
        is_new = not self._repository.conversation_exists(wa_id)
        input_phone = value.get("metadata", {}).get("display_phone_number") or value.get("metadata", {}).get("phone_number_id", "")
        message_text = self._extract_message_text(event_type, item)
        status_text = self._extract_status_text(event_type, item)
        timestamp = self._extract_timestamp(item)

        log_entry = WebhookLog(
            wa_id=wa_id,
            input_phone=input_phone,
            message=message_text,
            status=status_text,
            timestamp=timestamp,
        )
        self._repository.save_webhook_log(log_entry)
        LOGGER.info("Logged %s event for %s", event_type, wa_id)
        return log_entry, is_new

    def _handle_new_conversation(self, wa_id: str) -> None:
        welcome = (
            f"Hola {wa_id}! Bienvenido a EmotiTrack. "
            "Antes de iniciar la evaluacion DASS-21 necesitamos tu consentimiento informado."
        )
        self._send_text_safe(wa_id, welcome)
        consent_text = (
            "Aceptas nuestro aviso de privacidad y autorizas el uso de tus datos "
            "para continuar con la evaluacion DASS-21?"
        )
        buttons = [
            {"id": "consent_yes", "title": "Si, iniciar"},
            {"id": "consent_no", "title": "No, gracias"},
        ]
        try:
            self._whatsapp_client.send_reply_buttons(wa_id, consent_text, buttons)
        except Exception as exc:  # pragma: no cover
            LOGGER.exception("Failed to send consent buttons to %s: %s", wa_id, exc)

    def _reply_hello(self, wa_id: str) -> None:
        self._send_text_safe(wa_id, f"Hello {wa_id}")

    def _send_text_safe(self, wa_id: str, message: str) -> None:
        try:
            self._whatsapp_client.send_text_message(wa_id, message)
        except Exception as exc:  # pragma: no cover
            LOGGER.exception("Failed to send message to %s: %s", wa_id, exc)

    def _resolve_wa_id(self, event_type: str, item: Dict) -> Optional[str]:
        if event_type == "message":
            return item.get("from")
        if event_type == "status":
            return item.get("recipient_id")
        return None

    def _extract_message_text(self, event_type: str, item: Dict) -> str:
        if event_type == "message":
            message_type = item.get("type", "")
            if message_type == "text":
                return item.get("text", {}).get("body", "")
            return message_type or "message"
        status_value = item.get("status", "")
        return f"status:{status_value}" if status_value else "status"

    def _extract_status_text(self, event_type: str, item: Dict) -> str:
        if event_type == "message":
            return item.get("type", "message")
        return item.get("status", "status")

    def _extract_timestamp(self, item: Dict) -> Optional[str]:
        timestamp = item.get("timestamp")
        if timestamp is None:
            return None
        return str(timestamp)

    def recent_logs(self, limit: int = 20) -> List[WebhookLog]:
        return self._repository.fetch_recent_webhooks(limit)
