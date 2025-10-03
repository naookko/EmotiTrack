"""Flask application entry point for the WhatsApp bot."""

from __future__ import annotations

import logging
from typing import Any, Dict

from flask import Flask, abort, request

from whatsapp_bot.config import Settings
from whatsapp_bot.database import Database
from whatsapp_bot.repositories.log_repository import LogRepository
from whatsapp_bot.services.webhook_service import WebhookService
from whatsapp_bot.services.whatsapp_client import WhatsAppClient

logging.basicConfig(level=logging.INFO)

settings = Settings.from_env()
database = Database(settings.database_path)
database.initialise()

log_repository = LogRepository(database)
whatsapp_client = WhatsAppClient(settings.whatsapp_token, settings.phone_number_id)
webhook_service = WebhookService(log_repository, whatsapp_client)

app = Flask(__name__)


@app.route("/health", methods=["GET"])
def health() -> Dict[str, str]:
    return {"status": "ok"}


@app.route("/logs", methods=["GET"])
def logs() -> Dict[str, Any]:
    limit_param = request.args.get("limit", "20")
    try:
        limit = max(1, int(limit_param))
    except ValueError:
        abort(400, "limit must be numeric")
    log_entries = webhook_service.recent_logs(limit)
    return {
        "logs": [
            {
                "wa_id": log.wa_id,
                "input": log.input_phone,
                "message": log.message,
                "status": log.status,
            }
            for log in log_entries
        ]
    }


@app.route("/webhook", methods=["GET"])
def verify() -> Any:
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    if mode == "subscribe" and token == settings.verify_token:
        return challenge or ""
    return abort(403)


@app.route("/webhook", methods=["POST"])
def webhook() -> Dict[str, Any]:
    payload = request.get_json(silent=True) or {}
    logs = webhook_service.process_webhook(payload)
    app.logger.info("Logs endpoint returning %d entries: %s", len(payload), payload)
    return {
        "received": len(logs),
        "logs": [
            {
                "wa_id": log.wa_id,
                "input": log.input_phone,
                "message": log.message,
                "status": log.status,
            }
            for log in logs
        ],
    }


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
