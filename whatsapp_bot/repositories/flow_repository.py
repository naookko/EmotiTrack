
"""In-memory persistence helpers for flow session management."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from typing import Dict, List, Optional

from ..models import FlowSession


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class FlowRepository:
    """Stores flow sessions in memory instead of SQLite."""

    def __init__(self) -> None:
        self._sessions: Dict[int, FlowSession] = {}
        self._next_id = 1

    def _new_id(self) -> int:
        session_id = self._next_id
        self._next_id += 1
        return session_id

    def _sessions_for(self, wa_id: str) -> List[FlowSession]:
        return [session for session in self._sessions.values() if session.wa_id == wa_id]

    def create_session(
        self,
        wa_id: str,
        flow_name: str,
        context: Optional[Dict] = None,
        *,
        step_index: int = 0,
    ) -> FlowSession:
        session_id = self._new_id()
        now = _utcnow_iso()
        session = FlowSession(
            id=session_id,
            wa_id=wa_id,
            flow_name=flow_name,
            step_index=step_index,
            is_active=True,
            started_at=now,
            updated_at=now,
            completed_at=None,
            context=dict(context or {}),
        )
        self._sessions[session_id] = session
        return session

    def get_active_session(self, wa_id: str) -> Optional[FlowSession]:
        active = [s for s in self._sessions_for(wa_id) if s.is_active]
        active.sort(key=lambda s: s.updated_at, reverse=True)
        return active[0] if active else None

    def get_active_session_by_flow(self, wa_id: str, flow_name: str) -> Optional[FlowSession]:
        active = [
            s for s in self._sessions_for(wa_id)
            if s.flow_name == flow_name and s.is_active
        ]
        active.sort(key=lambda s: s.updated_at, reverse=True)
        return active[0] if active else None

    def get_latest_session(self, wa_id: str, flow_name: str) -> Optional[FlowSession]:
        sessions = [
            s for s in self._sessions_for(wa_id)
            if s.flow_name == flow_name
        ]
        sessions.sort(key=lambda s: s.started_at, reverse=True)
        return sessions[0] if sessions else None

    def save_progress(
        self,
        session: FlowSession,
        *,
        step_index: Optional[int] = None,
        context: Optional[Dict] = None,
        is_active: Optional[bool] = None,
        completed: Optional[bool] = None,
    ) -> FlowSession:
        updated_at = _utcnow_iso()
        new_context = dict(session.context) if context is None else dict(context)
        active_flag = session.is_active if is_active is None else is_active
        completed_at: Optional[str]
        if completed:
            completed_at = updated_at
            active_flag = False
        elif completed is False:
            completed_at = None
        else:
            completed_at = session.completed_at
        new_session = replace(
            session,
            step_index=session.step_index if step_index is None else step_index,
            is_active=active_flag,
            updated_at=updated_at,
            completed_at=completed_at,
            context=new_context,
        )
        self._sessions[new_session.id] = new_session
        return new_session

    def deactivate_flow(self, wa_id: str, flow_name: str) -> None:
        for session in self._sessions_for(wa_id):
            if session.flow_name != flow_name or not session.is_active:
                continue
            self.save_progress(session, is_active=False, completed=None)

    def list_active_flows(self, wa_id: str) -> List[FlowSession]:
        return [s for s in self._sessions_for(wa_id) if s.is_active]

    def delete_all_sessions(self) -> None:
        self._sessions.clear()
        self._next_id = 1
