
"""HTTP client for interacting with the Chat Bot API service."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

import requests

LOGGER = logging.getLogger(__name__)


class ChatBotApiClient:
    """Small helper around the FastAPI chat bot backend."""

    def __init__(
        self,
        base_url: str,
        *,
        session: Optional[requests.Session] = None,
        timeout: int = 10,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._session = session or requests.Session()
        self._timeout = timeout

    def _url(self, *parts: str) -> str:
        suffix = "/".join(part.strip("/") for part in parts if part)
        return f"{self._base_url}/{suffix}" if suffix else self._base_url

    def _request(
        self,
        method: str,
        url: str,
        *,
        allow_statuses: tuple[int, ...] = (),
        **kwargs: Any,
    ) -> requests.Response:
        response = self._session.request(method, url, timeout=self._timeout, **kwargs)
        if response.status_code in allow_statuses:
            return response
        try:
            response.raise_for_status()
        except requests.HTTPError:
            LOGGER.exception("ChatBot API request failed: %s %s", method, url)
            raise
        return response

    def get_student(self, wa_id: str) -> Optional[Dict[str, Any]]:
        url = self._url("students", wa_id)
        response = self._request("GET", url, allow_statuses=(404,))
        if response.status_code == 404:
            return None
        data = response.json()
        if isinstance(data, dict) and data.get("message") == "Student not found":
            return None
        return data

    def create_student(self, wa_id: str) -> Dict[str, Any]:
        url = self._url("students")
        payload = {"wha_id": wa_id, "consent_accepted": False}
        response = self._request("POST", url, json=payload)
        return response.json()

    def update_student_fields(self, wa_id: str, **fields: Any) -> Dict[str, Any]:
        current = self.get_student(wa_id) or {"consent_accepted": False, "age": None, "semester": None, "career": None}
        payload = {
            "wha_id": wa_id,
            "consent_accepted": fields.get("consent_accepted", current.get("consent_accepted", False)),
            "age": fields.get("age", current.get("age")),
            "semester": fields.get("semester", current.get("semester")),
            "career": fields.get("career", current.get("career")),
        }
        url = self._url("students")
        response = self._request("PATCH", url, json=payload)
        return response.json()

    def latest_questionnaire(self, wa_id: str) -> Optional[Dict[str, Any]]:
        url = self._url("responses", wa_id)
        response = self._request("GET", url, allow_statuses=(404,))
        if response.status_code == 404:
            return None
        data = response.json()
        responses = data.get("responses") if isinstance(data, dict) else None
        if not responses:
            return None
        def _sort_key(item: Dict[str, Any]) -> tuple:
            questionnaire_id = item.get("questionnaire_id")
            try:
                numeric_id = int(questionnaire_id)
            except (TypeError, ValueError):
                numeric_id = 0
            created_at = item.get("created_at") or item.get("response_date") or ""
            return numeric_id, str(created_at)
        responses.sort(key=_sort_key)
        return responses[-1]

    def update_questionnaire_answers(
        self,
        wa_id: str,
        questionnaire_id: str,
        updates: Dict[str, Any],
    ) -> Dict[str, Any]:
        url = self._url("responses", wa_id, questionnaire_id)
        response = self._request("PATCH", url, json=updates)
        return response.json()

    def calculate_questionnaire(self, questionnaire_id: str) -> Dict[str, Any]:
        url = self._url("calculation", questionnaire_id)
        response = self._request("POST", url)
        return response.json()

    def get_questionnaire_scores(self, questionnaire_id: str) -> Optional[Dict[str, Any]]:
        url = self._url("scores", questionnaire_id)
        response = self._request("GET", url, allow_statuses=(404,))
        if response.status_code == 404:
            return None
        return response.json()
