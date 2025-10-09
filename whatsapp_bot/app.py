
"""Flask application entry point for the WhatsApp bot."""

from __future__ import annotations

import logging
from typing import Any, Dict

from flask import Flask, abort, request

from whatsapp_bot.config import Settings
from whatsapp_bot.repositories.log_repository import LogRepository
from whatsapp_bot.repositories.flow_repository import FlowRepository
from whatsapp_bot.services.chat_bot_api_client import ChatBotApiClient
from whatsapp_bot.services.flow_engine import FlowEngine
from whatsapp_bot.services.webhook_service import WebhookService
from whatsapp_bot.services.whatsapp_client import WhatsAppClient

logging.basicConfig(level=logging.INFO)
LOGGER = logging.getLogger(__name__)

settings = Settings.from_env()

log_repository = LogRepository()
flow_repository = FlowRepository()
whatsapp_client = WhatsAppClient(settings.whatsapp_token, settings.phone_number_id)
chat_bot_api = ChatBotApiClient(settings.chat_bot_api_url)


def _record_answer(session, step, response, answer_payload) -> None:
    """Synchronise flow answers with the chat bot API."""

    if not step.answer_key:
        return
    try:
        if session.flow_name == WebhookService.START_FLOW:
            updates: Dict[str, Any] = {}
            if step.answer_key == "consent":
                updates["consent_accepted"] = response.value == "consent_yes"
            elif step.answer_key == "age":
                try:
                    updates["age"] = int(response.value)
                except (TypeError, ValueError):
                    LOGGER.warning("Invalid age response for wa_id=%s: %s", session.wa_id, response.value)
                    return
            elif step.answer_key == "semester_band":
                updates["semester"] = answer_payload.get("display") or answer_payload.get("value")
            elif step.answer_key == "career":
                updates["career"] = answer_payload.get("display") or answer_payload.get("value")
            if updates:
                chat_bot_api.update_student_fields(session.wa_id, **updates)
        elif session.flow_name == WebhookService.DASS_FLOW:
            allowed_values = {
                str(row.get("id"))
                for section in (step.sections or [])
                for row in section.get("rows", [])
                if row.get("id") is not None
            }
            if allowed_values and response.value not in allowed_values:
                LOGGER.warning("Ignoring response '%s' for wa_id=%s step=%s; expected one of %s", response.value, session.wa_id, step.id, sorted(allowed_values))
                return
            variables = session.context.get(FlowEngine.VARIABLES_KEY, {})
            questionnaire_id = variables.get("questionnaire_id")
            if questionnaire_id:
                chat_bot_api.update_questionnaire_answers(
                    session.wa_id,
                    str(questionnaire_id),
                    {step.answer_key: answer_payload},
                )
    except Exception:
        LOGGER.exception("Failed to persist answer for wa_id=%s step=%s", session.wa_id, step.id)


flow_engine = FlowEngine(
    flow_repository,
    log_repository,
    whatsapp_client,
    answer_recorder=_record_answer,
)
webhook_service = WebhookService(log_repository, flow_engine, chat_bot_api)

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
    app.logger.info("Logs endpoint returning %d entries", len(log_entries))
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
    flow_repository.delete_all_sessions()
    log_repository.delete_all_data()
    app.logger.warning("In-memory stores cleared via /debug/db")
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
    app.logger.info("Webhook processed %d entries", len(logs))
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
