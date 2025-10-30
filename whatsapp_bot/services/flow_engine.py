"""Flow engine that dispatches conversation steps based on JSON definitions."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from ..models import AnswerLog, FlowSession
from ..repositories.flow_repository import FlowRepository
from ..repositories.log_repository import LogRepository
from .whatsapp_client import WhatsAppClient


LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class FlowResponse:
    """Represents a participant reply to a flow step."""

    value: str
    display: Optional[str]
    response_type: str
    received_at: str


@dataclass(frozen=True)
class FlowStepDefinition:
    """Immutable representation of a single step defined in JSON."""

    id: str
    message_type: str
    expects_response: bool
    next_step: Optional[str]
    next_by_choice: Dict[str, str]
    message: Optional[str]
    header: Optional[Dict[str, Any]]
    body: Optional[Dict[str, Any]]
    footer: Optional[Dict[str, Any]]
    button: Optional[str]
    sections: List[Dict[str, Any]]
    answer_key: Optional[str]
    end: bool
    placeholders: List[str]


@dataclass(frozen=True)
class FlowDefinition:
    """Represents a flow made of ordered step definitions."""

    name: str
    steps: Dict[str, FlowStepDefinition]
    order: List[str]

    def first_step_id(self) -> Optional[str]:
        return self.order[0] if self.order else None

    def get(self, step_id: str) -> FlowStepDefinition:
        return self.steps[step_id]

    def index_of(self, step_id: str) -> int:
        return self.order.index(step_id)

    def default_next(self, current_step_id: str) -> Optional[str]:
        try:
            idx = self.order.index(current_step_id)
        except ValueError:
            return None
        next_idx = idx + 1
        if next_idx >= len(self.order):
            return None
        return self.order[next_idx]


class FlowEngine:
    """Coordinates flow session state, persistence, and message delivery."""

    ANSWERS_KEY = "answers"
    CURRENT_STEP_KEY = "current_step"
    EXPECTED_KEY = "expected_response"
    VARIABLES_KEY = "variables"

    def __init__(
        self,
        flow_repository: FlowRepository,
        log_repository: LogRepository,
        whatsapp_client: WhatsAppClient,
        *,
        answer_recorder: Callable[[FlowSession, FlowStepDefinition, FlowResponse, Dict[str, Any]], None] | None = None,
        flows_path: Optional[Path] = None,
    ) -> None:
        self._flow_repository = flow_repository
        self._log_repository = log_repository
        self._whatsapp_client = whatsapp_client
        self._answer_recorder = answer_recorder
        self._flows_path = flows_path or Path(__file__).resolve().parent.parent / "flows"
        self._definitions = self._load_definitions()

    @property
    def repository(self) -> FlowRepository:
        return self._flow_repository

    @property
    def whatsapp_client(self) -> WhatsAppClient:
        return self._whatsapp_client

    def _load_definitions(self) -> Dict[str, FlowDefinition]:
        definitions: Dict[str, FlowDefinition] = {}
        for json_path in sorted(self._flows_path.glob("*_flow.json")):
            with json_path.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
            name = payload.get("name")
            steps_payload = payload.get("steps", [])
            steps: Dict[str, FlowStepDefinition] = {}
            order: List[str] = []
            for step in steps_payload:
                next_field = step.get("next")
                if isinstance(next_field, dict):
                    next_step = None
                    next_by_choice = {str(k): str(v) for k, v in next_field.items()}
                else:
                    next_step = str(next_field) if next_field else None
                    next_by_choice = {}
                definition = FlowStepDefinition(
                    id=step["id"],
                    message_type=step["message_type"],
                    expects_response=bool(step.get("expects_response", False)),
                    next_step=next_step,
                    next_by_choice=next_by_choice,
                    message=step.get("message"),
                    header=step.get("header"),
                    body=step.get("body"),
                    footer=step.get("footer"),
                    button=step.get("button"),
                    sections=step.get("sections", []),
                    answer_key=step.get("answer_key"),
                    end=bool(step.get("end", False)),
                    placeholders=list(step.get("placeholders", [])),
                )
                steps[definition.id] = definition
                order.append(definition.id)
            if not name:
                raise ValueError(f"Flow at {json_path} is missing a name")
            definitions[name] = FlowDefinition(name=name, steps=steps, order=order)
        return definitions

    def ensure_session(
        self,
        flow_name: str,
        wa_id: str,
        initial_variables: Optional[Dict[str, Any]] = None,
        *,
        context_overrides: Optional[Dict[str, Any]] = None,
        start_from_step: Optional[str] = None,
        initial_step_index: Optional[int] = None,
    ) -> FlowSession:
        """Returns the active session for flow_name or creates a new one."""

        session = self._flow_repository.get_active_session_by_flow(wa_id, flow_name)
        if session:
            return session
        flow = self._definition(flow_name)
        base_context: Dict[str, Any] = {
            self.ANSWERS_KEY: {},
            self.VARIABLES_KEY: dict(initial_variables or {}),
            self.CURRENT_STEP_KEY: None,
            self.EXPECTED_KEY: None,
        }
        if context_overrides:
            overrides = dict(context_overrides)
            answers_override = overrides.pop(self.ANSWERS_KEY, None)
            variables_override = overrides.pop(self.VARIABLES_KEY, None)
            base_context.update(overrides)
            if answers_override is not None:
                base_context[self.ANSWERS_KEY] = dict(answers_override)
            if variables_override is not None:
                merged = dict(base_context[self.VARIABLES_KEY])
                merged.update(dict(variables_override))
                base_context[self.VARIABLES_KEY] = merged
        step_index = initial_step_index if initial_step_index is not None else 0
        session = self._flow_repository.create_session(
            wa_id,
            flow_name,
            base_context,
            step_index=step_index,
        )
        next_step_id = start_from_step or flow.first_step_id()
        if next_step_id:
            session = self._advance_and_send(session, flow, next_step_id, base_context)
        return session

    def handle_response(self, session: FlowSession, response: FlowResponse) -> FlowSession:
        """Registers the response and advances the flow."""

        flow = self._definition(session.flow_name)
        context = dict(session.context)
        answers = dict(context.get(self.ANSWERS_KEY, {}))
        variables = dict(context.get(self.VARIABLES_KEY, {}))
        expected = context.get(self.EXPECTED_KEY) or {}
        current_step_id = expected.get("step_id") or context.get(self.CURRENT_STEP_KEY)
        if not current_step_id:
            current_step_id = flow.order[session.step_index] if session.step_index < len(flow.order) else flow.first_step_id()
        step = flow.get(current_step_id)
        allowed_values = self._allowed_response_ids(step)
        if allowed_values and response.value not in allowed_values:
            LOGGER.warning("Unexpected response '%s' for wa_id=%s step=%s; re-sending prompt", response.value, session.wa_id, step.id)
            context[self.CURRENT_STEP_KEY] = step.id
            context[self.EXPECTED_KEY] = {
                "step_id": step.id,
                "type": step.message_type,
                "answer_key": step.answer_key,
            }
            updated_session = self._flow_repository.save_progress(
                session,
                context=context,
                step_index=flow.index_of(step.id),
            )
            self._dispatch_step(session.wa_id, step, context)
            return updated_session
        if step.answer_key:
            answers[step.answer_key] = {
                "value": response.value,
                "display": response.display,
                "received_at": response.received_at,
                "step_id": step.id,
            }
            log_value = response.display if response.display else response.value
            timestamp = response.received_at
            composed = f"{step.answer_key}:{log_value} [{timestamp}]"
            self._log_repository.save_answer(AnswerLog(session.wa_id, composed))
            if self._answer_recorder:
                new_answer = answers[step.answer_key]
                try:
                    self._answer_recorder(session, step, response, new_answer)
                except Exception:
                    LOGGER.exception("Answer recorder failed for wa_id=%s step=%s", session.wa_id, step.id)
        context[self.ANSWERS_KEY] = answers
        context[self.VARIABLES_KEY] = variables
        context[self.CURRENT_STEP_KEY] = step.id
        context[self.EXPECTED_KEY] = None
        next_step_id = self._resolve_next_step(flow, step, response.value)
        updated_session = self._flow_repository.save_progress(
            session,
            context=context,
            step_index=flow.index_of(step.id),
        )
        if not next_step_id:
            return self._flow_repository.save_progress(
                updated_session,
                context=context,
                completed=True,
            )
        return self._advance_and_send(updated_session, flow, next_step_id, context)

    def update_variables(self, session: FlowSession, data: Dict[str, Any]) -> FlowSession:
        """Stores additional runtime variables for placeholder rendering."""

        context = dict(session.context)
        variables = dict(context.get(self.VARIABLES_KEY, {}))
        variables.update(data)
        context[self.VARIABLES_KEY] = variables
        return self._flow_repository.save_progress(session, context=context)

    def active_session(self, flow_name: str, wa_id: str) -> Optional[FlowSession]:
        """Returns the active session for the given flow if any exists."""

        return self._flow_repository.get_active_session_by_flow(wa_id, flow_name)

    def latest_session(self, flow_name: str, wa_id: str) -> Optional[FlowSession]:
        """Fetches the most recent session regardless of its active status."""

        return self._flow_repository.get_latest_session(wa_id, flow_name)

    def list_active_sessions(self, wa_id: str) -> List[FlowSession]:
        """Lists every active session tracked for the participant."""

        return self._flow_repository.list_active_flows(wa_id)

    def deactivate(self, flow_name: str, wa_id: str) -> None:
        """Marks every active session for the flow as inactive."""

        self._flow_repository.deactivate_flow(wa_id, flow_name)

    def flow_steps(self, flow_name: str) -> List[FlowStepDefinition]:
        """Returns the ordered list of step definitions for a flow."""

        flow = self._definition(flow_name)
        return [flow.get(step_id) for step_id in flow.order]

    def get_step(self, flow_name: str, step_id: str) -> FlowStepDefinition:
        """Convenience accessor to a single step definition."""

        return self._definition(flow_name).get(step_id)

    def _definition(self, flow_name: str) -> FlowDefinition:
        if flow_name not in self._definitions:
            raise KeyError(f"Flow '{flow_name}' is not defined")
        return self._definitions[flow_name]

    @staticmethod
    def _allowed_response_ids(step: FlowStepDefinition) -> List[str]:
        if step.message_type != "interactive_list":
            return []
        identifiers: List[str] = []
        for section in step.sections or []:
            for row in section.get("rows", []):
                row_id = row.get("id")
                if row_id is not None:
                    identifiers.append(str(row_id))
        return identifiers

    def _resolve_next_step(
        self,
        flow: FlowDefinition,
        step: FlowStepDefinition,
        response_value: str,
    ) -> Optional[str]:
        if step.next_by_choice:
            return step.next_by_choice.get(response_value)
        if step.next_step:
            return step.next_step
        return flow.default_next(step.id)

    def _advance_and_send(
        self,
        session: FlowSession,
        flow: FlowDefinition,
        step_id: str,
        context: Dict[str, Any],
    ) -> FlowSession:
        current_session = session
        cursor_id: Optional[str] = step_id
        while cursor_id:
            step = flow.get(cursor_id)
            self._dispatch_step(current_session.wa_id, step, context)
            context = dict(context)
            context[self.CURRENT_STEP_KEY] = step.id
            if step.expects_response:
                context[self.EXPECTED_KEY] = {
                    "step_id": step.id,
                    "type": step.message_type,
                    "answer_key": step.answer_key,
                }
            else:
                context[self.EXPECTED_KEY] = None
            current_session = self._flow_repository.save_progress(
                current_session,
                step_index=flow.index_of(step.id),
                context=context,
                completed=step.end,
            )
            if step.end:
                break
            if step.expects_response:
                break
            cursor_id = step.next_step or flow.default_next(step.id)
        return current_session

    def _dispatch_step(
        self,
        wa_id: str,
        step: FlowStepDefinition,
        context: Dict[str, Any],
    ) -> None:
        variables = context.get(self.VARIABLES_KEY, {})
        if step.message_type == "text":
            message = self._render_message(step.message or "", variables)
            self._whatsapp_client.send_text_message(wa_id, message)
            return
        if step.message_type == "interactive_list":
            header = step.header
            body = step.body or {}
            footer = step.footer
            sections = step.sections
            button = step.button or "Responder"
            self._whatsapp_client.send_interactive_list(
                recipient=wa_id,
                header=header,
                body=body,
                footer=footer,
                button=button,
                sections=sections,
            )
            return
        raise ValueError(f"Unsupported message type: {step.message_type}")

    @staticmethod
    def _render_message(template: str, variables: Dict[str, Any]) -> str:
        if not template:
            return ""
        try:
            return template.format(**variables)
        except KeyError:
            return template

    @staticmethod
    def iso_now() -> str:
        return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
