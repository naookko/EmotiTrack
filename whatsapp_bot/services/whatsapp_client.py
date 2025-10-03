"""WhatsApp API client."""

from __future__ import annotations

import logging
from typing import Any, Dict

import requests

LOGGER = logging.getLogger(__name__)


class WhatsAppClient:
    """Small wrapper around the WhatsApp Cloud API."""

    API_URL_TEMPLATE = "https://graph.facebook.com/v22.0/{phone_number_id}/messages"

    def __init__(self, token: str, phone_number_id: str) -> None:
        self._token = token
        self._phone_number_id = phone_number_id

    def send_text_message(self, recipient: str, message: str) -> Dict[str, Any]:
        url = self.API_URL_TEMPLATE.format(phone_number_id=self._phone_number_id)
        payload = {
            "messaging_product": "whatsapp",
            "to": recipient,
            "type": "text",
            "text": {"preview_url": False, "body": message},
        }
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
        }
        LOGGER.debug("Sending WhatsApp message to %s", recipient)
        response = requests.post(url, json=payload, headers=headers, timeout=15)
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            LOGGER.error("WhatsApp API error: %s | Response: %s", exc, response.text)
            raise
        return response.json()
