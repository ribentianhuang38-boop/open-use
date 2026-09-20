"""TypeSafe AI Jev System One Client for Computer Use.

High-performance, typed probabilistic decision and evaluation client.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

try:
    from dotenv import load_dotenv
    _env_path = Path(__file__).resolve().parent / ".env"
    if _env_path.exists():
        load_dotenv(_env_path)
except ImportError:
    _env_path = Path(__file__).resolve().parent / ".env"
    if _env_path.exists():
        for line in _env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip("'\""))


@dataclass
class ChoiceResult:
    choice: str
    confidence: float
    probabilities: Dict[str, float]
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ScoreResult:
    score: float
    confidence: float
    probabilities: Dict[str, float]
    legend: Dict[str, str]
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class JevResponse:
    model: str
    answers: Dict[str, Any]
    usage: Dict[str, int]
    latency_ms: int

    def get_choice(self, question_id: str) -> Optional[ChoiceResult]:
        ans = self.answers.get(question_id)
        if not ans or ans.get("type") != "choice":
            return None
        return ChoiceResult(
            choice=ans.get("choice", ""),
            confidence=ans.get("confidence", 0.0),
            probabilities=ans.get("probabilities", {}),
            raw=ans,
        )

    def get_score(self, question_id: str) -> Optional[ScoreResult]:
        ans = self.answers.get(question_id)
        if not ans or ans.get("type") != "score":
            return None
        return ScoreResult(
            score=float(ans.get("score", 0.0)),
            confidence=float(ans.get("confidence", 0.0)),
            probabilities={str(k): float(v) for k, v in ans.get("probabilities", {}).items()},
            legend={str(k): str(v) for k, v in ans.get("legend", {}).items()},
            raw=ans,
        )


class JevClient:
    """Client for TypeSafe AI Jev (System One Model)."""

    DEFAULT_BASE_URL = "https://api.typesafe.ai/v1"

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: float = 25.0,
    ):
        self.api_key = api_key or os.environ.get("TYPESAFE_API_KEY")
        if not self.api_key:
            raise ValueError(
                "Missing TypeSafe API Key. Provide api_key or set TYPESAFE_API_KEY in .env or environment variable."
            )
        self.model = model or os.environ.get("TYPESAFE_MODEL", "jev-latest")
        self.base_url = (base_url or os.environ.get("TYPESAFE_BASE_URL", self.DEFAULT_BASE_URL)).rstrip("/")
        try:
            self._client = httpx.Client(http2=True, timeout=timeout)
        except Exception:
            self._client = httpx.Client(http2=False, timeout=timeout)

    def query_systemone(
        self,
        state: Dict[str, Any],
        questions: Dict[str, Any],
        model: Optional[str] = None,
    ) -> JevResponse:
        """Execute single parallel pass query against TypeSafe System One API."""
        url = f"{self.base_url}/systemone"
        target_model = model or self.model
        payload = {
            "model": target_model,
            "state": state,
            "questions": questions,
        }

        started = time.perf_counter()
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        for attempt in range(3):
            try:
                response = self._client.post(url, json=payload, headers=headers)
            except httpx.HTTPError as exc:
                if attempt == 2:
                    raise RuntimeError(f"TypeSafe connection failed: {exc}") from exc
                time.sleep(0.5 * 2**attempt)
                continue

            if response.status_code in {429, 502, 503, 529} and attempt < 2:
                time.sleep(0.5 * 2**attempt)
                continue

            if response.is_error:
                raise RuntimeError(
                    f"TypeSafe API returned HTTP {response.status_code}: {response.text}"
                )

            data = response.json()
            latency = round((time.perf_counter() - started) * 1000)
            return JevResponse(
                model=data.get("model", target_model),
                answers=data.get("answers", {}),
                usage=data.get("usage", {}),
                latency_ms=latency,
            )

        raise RuntimeError("TypeSafe API unavailable after retries")

    def choice(
        self,
        state: Dict[str, Any],
        criteria: Dict[str, str],
        instructions: Optional[Dict[str, Any]] = None,
        question_id: str = "decision",
        model: Optional[str] = None,
    ) -> ChoiceResult:
        """Convenience method for a single choice question."""
        q = {
            question_id: {
                "type": "choice",
                "criteria": criteria,
            }
        }
        if instructions:
            q[question_id]["instructions"] = instructions

        resp = self.query_systemone(state=state, questions=q, model=model)
        result = resp.get_choice(question_id)
        if not result:
            raise ValueError(f"Question '{question_id}' not found in response: {resp.answers}")
        return result

    def score(
        self,
        state: Dict[str, Any],
        criteria: List[str],
        instructions: Optional[Dict[str, Any]] = None,
        question_id: str = "evaluation",
        model: Optional[str] = None,
    ) -> ScoreResult:
        """Convenience method for a single score question."""
        q = {
            question_id: {
                "type": "score",
                "criteria": criteria,
            }
        }
        if instructions:
            q[question_id]["instructions"] = instructions

        resp = self.query_systemone(state=state, questions=q, model=model)
        result = resp.get_score(question_id)
        if not result:
            raise ValueError(f"Question '{question_id}' not found in response: {resp.answers}")
        return result

    def close(self):
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
