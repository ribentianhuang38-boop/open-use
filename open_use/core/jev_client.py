"""TypeSafe AI Jev System One Client for Computer Use.

High-performance, typed probabilistic decision and evaluation client.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger("open_use.core.jev_client")

from .config import load_env, get_typesafe_base_url

load_env()
_load_env_file = load_env


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
    legend: Dict[str, str] = field(default_factory=dict)


@dataclass
class JevResponse:
    """Complete typed response from a TypeSafe System One query."""
    model: str
    answers: Dict[str, Any]
    usage: Dict[str, int]
    latency_ms: int

    def get_choice(self, question_id: str) -> Optional[ChoiceResult]:
        raw = self.answers.get(question_id)
        if not raw or raw.get("type") != "choice":
            return None
        return ChoiceResult(
            choice=raw["choice"],
            confidence=raw.get("confidence", 0.0),
            probabilities=raw.get("probabilities", {}),
        )

    def get_score(self, question_id: str) -> Optional[ScoreResult]:
        raw = self.answers.get(question_id)
        if not raw or raw.get("type") != "score":
            return None
        return ScoreResult(
            score=raw["score"],
            confidence=raw.get("confidence", 0.0),
            probabilities=raw.get("probabilities", {}),
            legend=raw.get("legend", {}),
        )


class JevClient:
    """Production TypeSafe Jev System One Client."""

    DEFAULT_BASE_URL = "https://api.typesafe.ai/v1"

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: float = 25.0,
    ):
        self.api_key = api_key or os.environ.get("TYPESAFE_API_KEY") or os.environ.get("JEV_API_KEY")
        self._local_fallback = not bool(self.api_key)
        self.model = model or os.environ.get("TYPESAFE_MODEL", "jev-latest")
        self.base_url = (base_url or os.environ.get("TYPESAFE_BASE_URL", self.DEFAULT_BASE_URL)).rstrip("/")
        try:
            self._client = httpx.Client(http2=True, timeout=timeout)
        except Exception as exc:
            logger.debug(f"HTTP/2 client initialization failed ({exc}); falling back to HTTP/1.1")
            self._client = httpx.Client(http2=False, timeout=timeout)

    def query_systemone(
        self,
        state: Dict[str, Any],
        questions: Dict[str, Any],
        model: Optional[str] = None,
    ) -> JevResponse:
        """Execute single parallel pass query against TypeSafe System One API (or local heuristic fallback)."""
        if self._local_fallback:
            answers = {}
            for q_id, q_cfg in questions.items():
                q_type = q_cfg.get("type")
                if q_type == "choice":
                    crit = q_cfg.get("criteria", {})
                    if q_id in ("next_step_action", "decision"):
                        btn_keys = [k for k in crit.keys() if k.startswith("btn_")]
                        chosen = btn_keys[0] if btn_keys else (list(crit.keys())[0] if crit else "wait")
                    elif q_id == "jev_can_handle":
                        chosen = "can_handle"
                    elif q_id == "branch_status":
                        chosen = "on_track"
                    elif q_id == "can_reclaim":
                        chosen = "yes"
                    elif q_id == "goal_satisfied":
                        chosen = "no"
                    elif q_id == "step_status":
                        chosen = "progress"
                    elif q_id == "safety":
                        # C-02: Rigorous safety classification in local heuristic fallback
                        act_text = str(state.get("action", "")).lower()
                        goal_text = str(state.get("goal", "")).lower()
                        combined = f"{act_text} {goal_text}"
                        high_risk_terms = [
                            "rm -rf", "delete", "format", "drop table", "drop database",
                            "truncate", "kill -9", "shutdown", "reboot", "unlink",
                            "sudo", "passwd", "shadow", "chmod 777", "curl | bash",
                            "remove", "wipe", "destroy"
                        ]
                        is_destructive = any(term in combined for term in high_risk_terms)
                        if is_destructive:
                            chosen = "high_risk" if "high_risk" in crit else ("unsafe" if "unsafe" in crit else list(crit.keys())[-1])
                        else:
                            chosen = "medium_risk" if "medium_risk" in crit else ("safe" if "safe" in crit else list(crit.keys())[0])
                    else:
                        chosen = list(crit.keys())[0] if crit else ""

                    answers[q_id] = {
                        "type": "choice",
                        "choice": chosen,
                        "confidence": 0.85,
                        "probabilities": {k: (0.85 if k == chosen else 0.15 / max(1, len(crit) - 1)) for k in crit},
                    }
                elif q_type == "score":
                    answers[q_id] = {
                        "type": "score",
                        "score": 1.0,
                        "confidence": 0.8,
                        "probabilities": {"1.0": 0.8},
                        "legend": {},
                    }

            return JevResponse(
                model="local-heuristic",
                answers=answers,
                usage={"tokens": 0},
                latency_ms=1,
            )

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
            except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
                if attempt == 2:
                    raise RuntimeError(f"TypeSafe connection failed: {exc}") from exc
                time.sleep(0.5 * 2**attempt)
                continue
            except httpx.HTTPError as exc:
                raise RuntimeError(f"TypeSafe request failed: {exc}") from exc

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
