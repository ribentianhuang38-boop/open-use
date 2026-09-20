"""Adapter for integrating TypeSafe Jev Judge with standard Browser-Use.

Provides drop-in evaluation hooks, goal verifiers, and safety middlewares
that can be plugged into standard `browser-use` agent workflows.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

try:
    from .jev_judge import GoalVerdict, JevJudge, ProgressVerdict, SafetyVerdict
except ImportError:
    from jev_judge import GoalVerdict, JevJudge, ProgressVerdict, SafetyVerdict

logger = logging.getLogger("browser_use_jev.adapter")


class JevJudgeEvaluator:
    """Drop-in evaluator for standard browser-use tasks.

    Replaces slow and expensive LLM-as-a-judge calls (e.g. GPT-4o) with
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
        """Evaluate if the task succeeded.

        Returns:
            (passed: bool, verdict: GoalVerdict)
        """
        verdict = self.judge.judge_goal_completion(
            page_state=final_page_state,
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
        verdict = self.judge.judge_action_safety(
            proposed_action=action,
            page_state=current_page_state,
            goal=task_goal,
        )
        if not verdict.is_safe:
            logger.warning(
                f"[JevJudge Guardrail] Blocked risky action: {action.get('label')} "
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
        return self.judge.judge_step_progress(
            prev_page_state=prev_page,
            current_page_state=current_page,
            action_taken=executed_action,
            goal=task_goal,
        )


def verify_browser_state(page_text: str, page_title: str, page_url: str, goal: str) -> Dict[str, Any]:
    """Quick helper function to verify any web page state with Jev Judge."""
    judge = JevJudge()
    verdict = judge.judge_goal_completion(
        page_state={"text": page_text, "title": page_title, "url": page_url},
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
