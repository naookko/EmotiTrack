"""Service layer that handles webhook events."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from ..models import FlowSession, WebhookLog
from ..repositories.log_repository import LogRepository
from .flow_engine import FlowEngine, FlowResponse

LOGGER = logging.getLogger(__name__)


class WebhookService:
    """Coordinates webhook processing, persistence, and conversational flows."""

    DEFAULT_WA_ID = "5213325204729"
    START_FLOW = "start"
    DASS_FLOW = "dass21"
    FINAL_FLOW = "final"

    def __init__(
        self,
        repository: LogRepository,
        flow_engine: FlowEngine,
        cycle_duration: Optional[timedelta],
    ) -> None:
        self._repository = repository
        self._flow_engine = flow_engine
        self._cycle_duration = cycle_duration

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
            if event_type == "message":
                self._handle_message_event(log_entry, item, is_new)
        return logs

    def recent_logs(self, limit: int = 20) -> List[WebhookLog]:
        return self._repository.fetch_recent_webhooks(limit)

    def _handle_message_event(self, log_entry: WebhookLog, item: Dict[str, Any], is_new: bool) -> None:
        wa_id = log_entry.wa_id
        if is_new:
            LOGGER.info("Starting onboarding flow for new wa_id=%s", wa_id)
            self._flow_engine.ensure_session(self.START_FLOW, wa_id)
            return
        if self._cycle_duration and self._ensure_cycle_state(wa_id):
            LOGGER.info("Cycle expired for wa_id=%s; restarted DASS-21 flow", wa_id)
            return
        response = self._parse_flow_response(item)
        if not response:
            LOGGER.debug("Ignoring message without actionable content for wa_id=%s", wa_id)
            return
        session = self._resolve_session_for_response(wa_id)
        if not session:
            LOGGER.info("No active flow awaiting response for %s; restarting onboarding flow", wa_id)
            session = self._flow_engine.ensure_session(self.START_FLOW, wa_id)
        updated_session = self._flow_engine.handle_response(session, response)
        self._after_progress(updated_session)

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
        if session.flow_name == self.START_FLOW:
            if session.is_active:
                return
            answers = session.context.get(self._flow_engine.ANSWERS_KEY, {})
            consent = (answers.get("consent") or {}).get("value")
            if consent == "consent_yes":
                self._start_dass_flow(session.wa_id)
            return
        if session.flow_name == self.DASS_FLOW:
            if session.is_active:
                return
            self._start_final_flow(session)

    def _start_dass_flow(self, wa_id: str) -> None:
        active = self._flow_engine.active_session(self.DASS_FLOW, wa_id)
        if active:
            return
        latest = self._flow_engine.latest_session(self.DASS_FLOW, wa_id)
        if latest and not latest.is_active and self._cycle_duration:
            started_at = self._parse_timestamp_value(latest.started_at)
            if started_at and datetime.now(timezone.utc) - started_at < self._cycle_duration:
                LOGGER.info("Cycle still active for wa_id=%s; skipping new DASS-21 run", wa_id)
                return
        self._flow_engine.ensure_session(self.DASS_FLOW, wa_id)

    def _start_final_flow(self, dass_session: FlowSession) -> None:
        if not self._cycle_duration:
            return
        started_at = self._parse_timestamp_value(dass_session.started_at)
        if not started_at:
            return
        next_date = started_at + self._cycle_duration
        variables = {"next_date": self._format_datetime(next_date)}
        self._flow_engine.ensure_session(self.FINAL_FLOW, dass_session.wa_id, variables)

    def _ensure_cycle_state(self, wa_id: str) -> bool:
        active = self._flow_engine.active_session(self.DASS_FLOW, wa_id)
        target = active or self._flow_engine.latest_session(self.DASS_FLOW, wa_id)
        if not target or not self._cycle_duration:
            return False
        started_at = self._parse_timestamp_value(target.started_at)
        if not started_at:
            return False
        if datetime.now(timezone.utc) - started_at < self._cycle_duration:
            return False
        LOGGER.info("Resetting DASS-21 flow for wa_id=%s due to elapsed cycle", wa_id)
        self._flow_engine.deactivate(self.DASS_FLOW, wa_id)
        self._flow_engine.deactivate(self.FINAL_FLOW, wa_id)
        self._flow_engine.ensure_session(self.DASS_FLOW, wa_id)
        return True

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

    def _extract_status_text(self, event_type: str, item: Dict) -> str:
        if event_type == "message":
            return item.get("type", "message")
        return item.get("status", "status")

    def _extract_timestamp(self, item: Dict) -> Optional[str]:
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

    @staticmethod
    def _parse_timestamp_value(raw: Optional[str]) -> Optional[datetime]:
        if not raw:
            return None
        try:
            return datetime.fromisoformat(raw)
        except ValueError:
            return None

    @staticmethod
    def _format_datetime(dt_value: datetime) -> str:
        local_dt = dt_value.astimezone(timezone.utc)
        return local_dt.strftime("%Y-%m-%d %H:%M UTC")
