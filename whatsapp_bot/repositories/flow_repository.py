"""Persistence helpers for flow session management."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from ..database import Database
from ..models import FlowSession


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _isoformat(dt: Optional[datetime] = None) -> str:
    value = dt or _utcnow()
    return value.replace(microsecond=0).isoformat()


def _row_to_session(row: Any) -> FlowSession:
    context_raw = row[8] if row[8] is not None else "{}"
    context = json.loads(context_raw)
    return FlowSession(
        id=row[0],
        wa_id=row[1],
        flow_name=row[2],
        step_index=row[3],
        is_active=bool(row[4]),
        started_at=row[5],
        updated_at=row[6],
        completed_at=row[7],
        context=context,
    )


class FlowRepository:
    """Provides CRUD operations over flow_sessions."""

    def __init__(self, database: Database) -> None:
        self._db = database

    def create_session(
        self,
        wa_id: str,
        flow_name: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> FlowSession:
        now = _isoformat()
        context_json = json.dumps(context or {})
        with self._db.connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO flow_sessions (
                    wa_id, flow_name, step_index, is_active, started_at, updated_at, context
                )
                VALUES (?, ?, 0, 1, ?, ?, ?)
                """,
                (wa_id, flow_name, now, now, context_json),
            )
            session_id = cursor.lastrowid
            conn.commit()
            row = conn.execute(
                """
                SELECT id, wa_id, flow_name, step_index, is_active, started_at, updated_at, completed_at, context
                FROM flow_sessions
                WHERE id = ?
                """,
                (session_id,),
            ).fetchone()
        return _row_to_session(row)

    def get_active_session(self, wa_id: str) -> Optional[FlowSession]:
        with self._db.connection() as conn:
            row = conn.execute(
                """
                SELECT id, wa_id, flow_name, step_index, is_active, started_at, updated_at, completed_at, context
                FROM flow_sessions
                WHERE wa_id = ? AND is_active = 1
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                (wa_id,),
            ).fetchone()
        return _row_to_session(row) if row else None

    def get_active_session_by_flow(self, wa_id: str, flow_name: str) -> Optional[FlowSession]:
        with self._db.connection() as conn:
            row = conn.execute(
                """
                SELECT id, wa_id, flow_name, step_index, is_active, started_at, updated_at, completed_at, context
                FROM flow_sessions
                WHERE wa_id = ? AND flow_name = ? AND is_active = 1
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                (wa_id, flow_name),
            ).fetchone()
        return _row_to_session(row) if row else None

    def get_latest_session(self, wa_id: str, flow_name: str) -> Optional[FlowSession]:
        with self._db.connection() as conn:
            row = conn.execute(
                """
                SELECT id, wa_id, flow_name, step_index, is_active, started_at, updated_at, completed_at, context
                FROM flow_sessions
                WHERE wa_id = ? AND flow_name = ?
                ORDER BY started_at DESC
                LIMIT 1
                """,
                (wa_id, flow_name),
            ).fetchone()
        return _row_to_session(row) if row else None

    def save_progress(
        self,
        session: FlowSession,
        *,
        step_index: Optional[int] = None,
        context: Optional[Dict[str, Any]] = None,
        is_active: Optional[bool] = None,
        completed: Optional[bool] = None,
    ) -> FlowSession:
        new_step = step_index if step_index is not None else session.step_index
        new_context = context if context is not None else session.context
        active_flag = session.is_active if is_active is None else is_active
        updated_at = _isoformat()
        completed_at: Optional[str]
        if completed is True:
            completed_at = updated_at
            active_flag = False
        elif completed is False:
            completed_at = None
        else:
            completed_at = session.completed_at
        with self._db.connection() as conn:
            conn.execute(
                """
                UPDATE flow_sessions
                SET step_index = ?,
                    is_active = ?,
                    updated_at = ?,
                    completed_at = ?,
                    context = ?
                WHERE id = ?
                """,
                (
                    new_step,
                    1 if active_flag else 0,
                    updated_at,
                    completed_at,
                    json.dumps(new_context),
                    session.id,
                ),
            )
            conn.commit()
        return replace(
            session,
            step_index=new_step,
            is_active=active_flag,
            updated_at=updated_at,
            completed_at=completed_at,
            context=new_context,
        )

    def deactivate_flow(self, wa_id: str, flow_name: str) -> None:
        timestamp = _isoformat()
        with self._db.connection() as conn:
            conn.execute(
                """
                UPDATE flow_sessions
                SET is_active = 0,
                    updated_at = ?,
                    completed_at = COALESCE(completed_at, ?)
                WHERE wa_id = ? AND flow_name = ? AND is_active = 1
                """,
                (timestamp, timestamp, wa_id, flow_name),
            )
            conn.commit()

    def list_active_flows(self, wa_id: str) -> List[FlowSession]:
        with self._db.connection() as conn:
            rows = conn.execute(
                """
                SELECT id, wa_id, flow_name, step_index, is_active, started_at, updated_at, completed_at, context
                FROM flow_sessions
                WHERE wa_id = ? AND is_active = 1
                ORDER BY updated_at DESC
                """,
                (wa_id,),
            ).fetchall()
        return [_row_to_session(row) for row in rows]
