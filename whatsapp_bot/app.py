"""Flask application entry point for the WhatsApp bot."""

from __future__ import annotations

import logging
from typing import Any, Dict

from flask import Flask, abort, request

from whatsapp_bot.config import Settings
from whatsapp_bot.database import Database
from whatsapp_bot.repositories.log_repository import LogRepository
from whatsapp_bot.repositories.flow_repository import FlowRepository
from whatsapp_bot.services.flow_engine import FlowEngine
from whatsapp_bot.services.webhook_service import WebhookService
from whatsapp_bot.services.whatsapp_client import WhatsAppClient

logging.basicConfig(level=logging.INFO)

settings = Settings.from_env()
database = Database(settings.database_path)
database.initialise()

log_repository = LogRepository(database)
flow_repository = FlowRepository(database)
whatsapp_client = WhatsAppClient(settings.whatsapp_token, settings.phone_number_id)
flow_engine = FlowEngine(flow_repository, log_repository, whatsapp_client)
webhook_service = WebhookService(log_repository, flow_engine, settings.cycle_questionary_time)

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
    app.logger.info("Logs endpoint returning %d entries: %s", len(log_entries), log_entries)
    return {
        "logs": [
            {
                "wa_id": log.wa_id,
                "input": log.input_phone,
                "message": log.message,
                "status": log.status,
                "timestamp": log.timestamp,
            }
            for log in log_entries
        ]
    }


@app.route("/debug/db", methods=["GET"])
def dump_database() -> Dict[str, Any]:
    webhooks = log_repository.fetch_all_webhooks()
    answers = log_repository.fetch_all_answers()
    return {
        "webhooks": [
            {
                "wa_id": log.wa_id,
                "input": log.input_phone,
                "message": log.message,
                "status": log.status,
                "timestamp": log.timestamp,
            }
            for log in webhooks
        ],
        "answers": [
            {
                "wa_id": item.wa_id,
                "answer": item.answer,
            }
            for item in answers
        ],
    }


@app.route("/debug/db", methods=["DELETE"])
def reset_database() -> Dict[str, str]:
    log_repository.delete_all_data()
    app.logger.warning("All log tables cleared via /debug/db")
    return {"status": "cleared"}


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
    #app.logger.info("Webhook processed %d entries: %s", len(logs), logs)
    return {
        "received": len(logs),
        "logs": [
            {
                "wa_id": log.wa_id,
                "input": log.input_phone,
                "message": log.message,
                "status": log.status,
                "timestamp": log.timestamp,
            }
            for log in logs
        ],
    }


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
