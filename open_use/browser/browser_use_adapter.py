"""Adapter for integrating TypeSafe Jev Judge with standard Browser-Use.

Provides drop-in evaluation hooks, goal verifiers, and safety middlewares
that can be plugged into standard `browser-use` agent workflows.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from ..core.jev_judge import GoalVerdict, JevJudge, ProgressVerdict, SafetyVerdict

logger = logging.getLogger("open_use.browser.adapter")


class JevJudgeEvaluator:
    """Drop-in evaluator for standard browser-use tasks.

    Replaces slow and expensive LLM-as-a-judge calls with
    TypeSafe Jev (<300ms, calibrated confidence, typed score).
    """

    def __init__(self, judge: Optional[JevJudge] = None, min_confidence: float = 0.6):
        self.judge = judge or JevJudge()
        self.min_confidence = min_confidence

    def evaluate_task_outcome(
        self,
        final_page_state: Dict[str, Any],
        task_goal: str,
        action_history: Optional[List[Dict[str, Any]]] = None,
    ) -> Tuple[bool, GoalVerdict]:
        """Evaluate if the task succeeded."""
        verdict = self.judge.judge_goal_completion(
            screen_state=final_page_state,
            goal=task_goal,
            history=action_history,
        )

        passed = verdict.is_satisfied and (verdict.confidence >= self.min_confidence)
        logger.info(
            f"[JevJudge] Task Evaluation -> Passed: {passed} "
            f"(Score: {verdict.score:.2f}/3.0, Conf: {verdict.confidence:.2f}, Latency: {verdict.latency_ms}ms)"
        )
        return passed, verdict

    def evaluate_action_safety(
        self,
        action: Dict[str, Any],
        current_page_state: Dict[str, Any],
        task_goal: str,
    ) -> Tuple[bool, SafetyVerdict]:
        """Pre-execution guardrail check for proposed browser actions."""
        action_desc = action.get("label") or action.get("action") or str(action)
        verdict = self.judge.check_safety(
            goal=task_goal,
            action=str(action_desc),
        )
        if not verdict.is_safe:
            logger.warning(
                f"[JevJudge Guardrail] Blocked risky action: {action_desc} "
                f"Risk: {verdict.risk_level}, Confidence: {verdict.confidence:.2f}"
            )
        return verdict.is_safe, verdict

    def evaluate_step(
        self,
        prev_page: Dict[str, Any],
        current_page: Dict[str, Any],
        executed_action: Dict[str, Any],
        task_goal: str,
    ) -> ProgressVerdict:
        """Evaluate if the step made forward progress or encountered a blocker."""
        return self.judge.judge_progress(
            prev_summary=str(prev_page.get("text") or prev_page),
            curr_summary=str(current_page.get("text") or current_page),
            last_action=executed_action,
        )


def verify_browser_state(page_text: str, page_title: str, page_url: str, goal: str) -> Dict[str, Any]:
    """Quick helper function to verify any web page state with Jev Judge."""
    judge = JevJudge()
    verdict = judge.judge_goal_completion(
        screen_state={"visible_text": page_text, "active_window": page_title, "url": page_url},
        goal=goal,
    )
    return {
        "success": verdict.is_satisfied,
        "score": verdict.score,
        "confidence": verdict.confidence,
        "probability": verdict.satisfaction_probability,
        "latency_ms": verdict.latency_ms,
        "details": verdict.raw_response,
    }
