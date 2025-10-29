
"""Service layer that handles webhook events."""

from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Tuple

from ..models import FlowSession, WebhookLog
from ..repositories.log_repository import LogRepository
from .chat_bot_api_client import ChatBotApiClient
from .flow_engine import FlowEngine, FlowResponse

LOGGER = logging.getLogger(__name__)


class WebhookService:
    """Coordinates webhook processing, persistence, and conversational flows."""

    DEFAULT_WA_ID = "5213325204729"
    START_FLOW = "start"
    DASS_FLOW = "dass21"

    def __init__(
        self,
        repository: LogRepository,
        flow_engine: FlowEngine,
        chat_api: ChatBotApiClient,
        *,
        questionnaire_timeout_minutes: int = 1,
    ) -> None:
        self._repository = repository
        self._flow_engine = flow_engine
        self._chat_api = chat_api
        self._questionnaire_timeout = timedelta(minutes=max(1, questionnaire_timeout_minutes))

    def process_webhook(self, payload: Dict[str, Any]) -> List[WebhookLog]:
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
            log_entry, student = result
            logs.append(log_entry)
            if event_type == "message":
                self._handle_message_event(log_entry, item, student)
        return logs

    def recent_logs(self, limit: int = 20) -> List[WebhookLog]:
        return self._repository.fetch_recent_webhooks(limit)

    def _handle_message_event(
        self,
        log_entry: WebhookLog,
        item: Dict[str, Any],
        student: Optional[Dict[str, Any]],
    ) -> None:
        wa_id = log_entry.wa_id
        if student is None:
            try:
                self._chat_api.create_student(wa_id)
                LOGGER.info("Registered new student for wa_id=%s", wa_id)
            except Exception:
                LOGGER.exception("Failed to create student for wa_id=%s", wa_id)
                return
            self._flow_engine.ensure_session(self.START_FLOW, wa_id)
            return

        response = self._parse_flow_response(item)
        if not response:
            LOGGER.debug("Ignoring message without actionable content for wa_id=%s", wa_id)
            return

        session = self._resolve_session_for_response(wa_id)
        if not session:
            session = self._ensure_default_session(wa_id, student)
            if not session:
                LOGGER.debug("No session available to handle response for wa_id=%s", wa_id)
                return

        updated_session = self._flow_engine.handle_response(session, response)
        self._after_progress(updated_session)

    def _ensure_default_session(
        self,
        wa_id: str,
        student: Dict[str, Any],
    ) -> Optional[FlowSession]:
        consent = bool(student.get("consent_accepted"))
        if not consent:
            LOGGER.info("Ensuring start flow for wa_id=%s", wa_id)
            return self._flow_engine.ensure_session(self.START_FLOW, wa_id)
        LOGGER.info("Ensuring questionnaire flow for wa_id=%s", wa_id)
        return self._ensure_questionnaire_session(wa_id)

    def _ensure_questionnaire_session(self, wa_id: str) -> Optional[FlowSession]:
        try:
            latest = self._chat_api.latest_questionnaire(wa_id)
        except Exception:
            LOGGER.exception("Failed to fetch questionnaire for wa_id=%s", wa_id)
            return None
        if not latest:
            LOGGER.warning("No questionnaire found for wa_id=%s", wa_id)
            return None
        answers = latest.get("answer") or {}
        questionnaire_id = latest.get("questionnaire_id")
        if questionnaire_id is None:
            LOGGER.warning("Questionnaire lacks identifier for wa_id=%s", wa_id)
            return None
        restart_required = False
        next_step_id = self._next_question_step(answers)
        if not next_step_id and self._questionnaire_expired(latest):
            LOGGER.info(
                "Questionnaire expired after completion; resetting for wa_id=%s", wa_id
            )
            answers = {}
            next_step_id = self._next_question_step(answers)
            restart_required = True
        if not next_step_id:
            LOGGER.info("Questionnaire already complete for wa_id=%s", wa_id)
            return None
        last_index = self._last_answered_step_index(answers)
        context_overrides = {
            self._flow_engine.ANSWERS_KEY: answers,
            self._flow_engine.CURRENT_STEP_KEY: self._last_answered_step_id(answers),
        }
        variables = {"questionnaire_id": questionnaire_id}
        session = self._flow_engine.ensure_session(
            self.DASS_FLOW,
            wa_id,
            initial_variables=variables,
            context_overrides=context_overrides,
            start_from_step=next_step_id,
            initial_step_index=max(last_index, 0),
        )
        if restart_required:
            LOGGER.debug(
                "Ignoring current message for wa_id=%s due to questionnaire restart", wa_id
            )
            return None
        return session

    def _questionnaire_expired(self, questionnaire: Dict[str, Any]) -> bool:
        timestamp = self._questionnaire_timestamp(questionnaire)
        if not timestamp:
            return False
        now = datetime.now(timezone.utc)
        return now - timestamp >= self._questionnaire_timeout

    @staticmethod
    def _questionnaire_timestamp(questionnaire: Dict[str, Any]) -> Optional[datetime]:
        for key in ("updated_at", "response_date", "created_at"):
            value = questionnaire.get(key)
            parsed = WebhookService._parse_datetime(value)
            if parsed:
                return parsed
        return None

    @staticmethod
    def _parse_datetime(value: Any) -> Optional[datetime]:
        if isinstance(value, datetime):
            return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        if isinstance(value, str):
            candidate = value.strip()
            if not candidate:
                return None
            if candidate.endswith("Z"):
                candidate = candidate[:-1] + "+00:00"
            try:
                parsed = datetime.fromisoformat(candidate)
            except ValueError:
                return None
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        return None

    def _next_question_step(self, answers: Dict[str, Any]) -> Optional[str]:
        steps = self._flow_engine.flow_steps(self.DASS_FLOW)
        for step in steps:
            if not step.expects_response or not step.answer_key:
                continue
            if not answers.get(step.answer_key):
                return step.id
        return None

    def _last_answered_step_index(self, answers: Dict[str, Any]) -> int:
        steps = self._flow_engine.flow_steps(self.DASS_FLOW)
        answered_keys = {key for key, value in answers.items() if value}
        last_index = -1
        for idx, step in enumerate(steps):
            if step.answer_key and step.answer_key in answered_keys:
                last_index = idx
        return last_index

    def _last_answered_step_id(self, answers: Dict[str, Any]) -> Optional[str]:
        steps = self._flow_engine.flow_steps(self.DASS_FLOW)
        for step in reversed(steps):
            if step.answer_key and answers.get(step.answer_key):
                return step.id
        return None

    def _resolve_session_for_response(self, wa_id: str) -> Optional[FlowSession]:
        for flow_name in (self.START_FLOW, self.DASS_FLOW):
            session = self._flow_engine.active_session(flow_name, wa_id)
            if session:
                expected = session.context.get(self._flow_engine.EXPECTED_KEY)
                if expected:
                    return session
        for session in self._flow_engine.list_active_sessions(wa_id):
            expected = session.context.get(self._flow_engine.EXPECTED_KEY)
            if expected:
                return session
        return self._flow_engine.active_session(self.DASS_FLOW, wa_id)

    def _after_progress(self, session: FlowSession) -> None:
        if session.flow_name == self.START_FLOW and not session.is_active:
            answers = session.context.get(self._flow_engine.ANSWERS_KEY, {})
            consent = (answers.get("consent") or {}).get("value")
            if consent == "consent_yes":
                self._ensure_questionnaire_session(session.wa_id)
            return
        if session.flow_name == self.DASS_FLOW and not session.is_active:
            LOGGER.info("Completed questionnaire flow for wa_id=%s", session.wa_id)

    def _log_event(
        self,
        event_type: str,
        value: Dict[str, Any],
        item: Dict[str, Any],
    ) -> Optional[Tuple[WebhookLog, Optional[Dict[str, Any]]]]:
        wa_id = self._resolve_wa_id(event_type, item)
        if not wa_id:
            LOGGER.warning("Could not resolve wa_id for event %s; using default", event_type)
            wa_id = self.DEFAULT_WA_ID
        student: Optional[Dict[str, Any]] = None
        try:
            student = self._chat_api.get_student(wa_id)
        except Exception:
            LOGGER.exception("Failed to consult student with wa_id=%s", wa_id)
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
        return log_entry, student

    def _parse_flow_response(self, message: Dict[str, Any]) -> Optional[FlowResponse]:
        message_type = message.get("type")
        received_at = self._timestamp_to_iso(message.get("timestamp"))
        if message_type == "interactive":
            interactive = message.get("interactive", {})
            list_reply = interactive.get("list_reply")
            if list_reply:
                return FlowResponse(
                    value=str(list_reply.get("id", "")),
                    display=list_reply.get("title"),
                    response_type="list",
                    received_at=received_at,
                )
            button_reply = interactive.get("button_reply")
            if button_reply:
                return FlowResponse(
                    value=str(button_reply.get("id", "")),
                    display=button_reply.get("title"),
                    response_type="button",
                    received_at=received_at,
                )
        if message_type == "text":
            body = message.get("text", {}).get("body")
            if body is None:
                return None
            trimmed = body.strip()
            return FlowResponse(
                value=trimmed,
                display=trimmed,
                response_type="text",
                received_at=received_at,
            )
        return None

    def _resolve_wa_id(self, event_type: str, item: Dict[str, Any]) -> Optional[str]:
        if event_type == "message":
            return item.get("from")
        if event_type == "status":
            return item.get("recipient_id")
        return None

    def _extract_message_text(self, event_type: str, item: Dict[str, Any]) -> str:
        if event_type == "message":
            message_type = item.get("type", "")
            if message_type == "text":
                return item.get("text", {}).get("body", "")
            if message_type == "interactive":
                interactive = item.get("interactive", {})
                if "list_reply" in interactive:
                    reply = interactive["list_reply"]
                    reply_id = reply.get("id", "")
                    return f"list_reply:{reply_id}"
                if "button_reply" in interactive:
                    reply = interactive["button_reply"]
                    reply_id = reply.get("id", "")
                    return f"button_reply:{reply_id}"
            return message_type or "message"
        status_value = item.get("status", "")
        return f"status:{status_value}" if status_value else "status"

    def _extract_status_text(self, event_type: str, item: Dict[str, Any]) -> str:
        if event_type == "message":
            return item.get("type", "message")
        return item.get("status", "status")

    def _extract_timestamp(self, item: Dict[str, Any]) -> Optional[str]:
        timestamp = item.get("timestamp")
        if timestamp is None:
            return None
        return str(timestamp)

    @staticmethod
    def _timestamp_to_iso(timestamp: Optional[str]) -> str:
        if not timestamp:
            return FlowEngine.iso_now()
        try:
            return datetime.fromtimestamp(int(timestamp), tz=timezone.utc).replace(microsecond=0).isoformat()
        except (TypeError, ValueError):
            return str(timestamp)
