"""Utilities to allocate temporary WA IDs for simulator-driven conversations."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, List, Optional

from .chat_bot_api_client import ChatBotApiClient

LOGGER = logging.getLogger(__name__)


class SimulationManager:
    """Allocates synthetic wa_id values so a real tester can mimic multiple users."""

    DEFAULT_SEED = 5213144600001

    def __init__(
        self,
        chat_api: ChatBotApiClient,
        *,
        real_wa_id: Optional[str],
        wa_ids_path: Optional[Path] = None,
    ) -> None:
        self._chat_api = chat_api
        self._real_wa_id = real_wa_id.strip() if real_wa_id else None
        if wa_ids_path and not isinstance(wa_ids_path, Path):
            wa_ids_path = Path(wa_ids_path)
        self._wa_ids_path = wa_ids_path
        self._candidates = self._load_candidates()
        self._candidate_pointer = 0
        self._active_aliases: Dict[str, str] = {}

    def resolve_storage_wa_id(self, wa_id: str, *, allocate: bool = False) -> str:
        """Returns the wa_id to be used for persistence, allocating a synthetic one if needed."""

        if not self._is_simulated_user(wa_id):
            return wa_id
        alias = self._active_aliases.get(wa_id)
        if alias:
            return alias
        if not allocate:
            return wa_id
        alias = self._reserve_next_alias()
        if alias:
            self._active_aliases[wa_id] = alias
            return alias
        return wa_id

    def release_alias(self, storage_wa_id: str) -> None:
        """Releases an alias once the simulated questionnaire is over."""

        if not self._active_aliases:
            return
        for tester, alias in list(self._active_aliases.items()):
            if alias == storage_wa_id:
                LOGGER.info("Releasing simulated wa_id=%s for tester=%s", alias, tester)
                self._active_aliases.pop(tester, None)
                break

    def _is_simulated_user(self, wa_id: str) -> bool:
        return bool(self._real_wa_id and wa_id == self._real_wa_id)

    def _reserve_next_alias(self) -> Optional[str]:
        pointer = self._candidate_pointer
        while True:
            candidate_value = self._candidate_value(pointer)
            exists = self._student_exists(candidate_value)
            if exists is None:
                return None
            pointer += 1
            if exists:
                continue
            self._candidate_pointer = pointer
            alias = str(candidate_value)
            LOGGER.info("Assigned simulated wa_id=%s", alias)
            return alias

    def _student_exists(self, candidate_value: int) -> Optional[bool]:
        wa_id = str(candidate_value)
        try:
            student = self._chat_api.get_student(wa_id)
        except Exception:
            LOGGER.exception("Failed to verify existence for simulated wa_id=%s", wa_id)
            return None
        return student is not None

    def _candidate_value(self, pointer: int) -> int:
        if 0 <= pointer < len(self._candidates):
            return self._candidates[pointer]
        if self._candidates:
            base = self._candidates[-1]
        else:
            base = self.DEFAULT_SEED - 1
        overflow = pointer - len(self._candidates)
        return base + overflow + 1

    def _load_candidates(self) -> List[int]:
        if not self._wa_ids_path:
            return []
        path = self._wa_ids_path
        if not path.exists():
            LOGGER.warning("Simulation wa_id list %s not found; falling back to sequence", path)
            return []
        values: List[int] = []
        seen: set[int] = set()
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            stripped = raw_line.strip()
            if not stripped:
                continue
            try:
                value = int(stripped)
            except ValueError:
                LOGGER.warning("Ignoring invalid wa_id '%s' in %s", stripped, path)
                continue
            if value in seen:
                continue
            values.append(value)
            seen.add(value)
        return values
