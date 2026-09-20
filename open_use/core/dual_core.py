"""Adaptive Dual-Core Handover & Self-Cognition Engine.

Coordinates the dynamic handoff between:
1. System 1 (TypeSafe Jev): Sub-50ms rapid execution, self-confidence gating, and error branch rollback.
2. System 2 (LLM): Strategic intervention, impasse breaking, and macro reasoning.

Architecture Principles:
- Jev First: Route to Jev by default.
- Self-Assessment: Jev evaluates its own ability to proceed on every step.
- Escalation on Loop/Confusion: Handoff to LLM when confidence drops or loops are detected.
- Continuous Sniffing: When LLM is active, Jev checks in parallel if it can reclaim control.
- Fast Branch Rollback: Detect wrong-path drift or dead-end modals and rollback immediately.
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple

from .jev_client import JevClient, JevResponse


class ControllerMode(str, Enum):
    SYSTEM_1_JEV = "jev_fast"
    SYSTEM_2_LLM = "llm_slow"


@dataclass
class CapabilityAssessment:
    """Outcome of Jev evaluating whether it can handle the current situation."""
    can_handle: bool
    confidence: float
    reason: str  # "high_confidence", "low_confidence", "loop_detected", "complex_reasoning"
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class BranchHealth:
    """Outcome of checking if the agent drifted into a wrong branch/modal."""
    on_track: bool
    drift_type: str  # "normal", "wrong_modal", "error_dialog", "irrelevant_page"
    confidence: float
    recommended_rollback: str  # "none", "esc", "back", "cancel"


@dataclass
class ReclaimVerdict:
    """Outcome of checking if Jev can safely take back control from LLM."""
    can_reclaim: bool
    confidence: float
    rationale: str


class DualCoreOrchestrator:
    """Manages the dynamic handover and branch rollback between Jev and LLM."""

    def __init__(
        self,
        client: Optional[JevClient] = None,
        confidence_threshold: float = 0.65,
        max_loop_count: int = 2,
    ):
        self.client = client or JevClient()
        self.confidence_threshold = confidence_threshold
        self.max_loop_count = max_loop_count
        self.current_mode = ControllerMode.SYSTEM_1_JEV

        self.action_history: List[str] = []
        self.target_history: List[str] = []
        self.step_counter = 0

    def record_step(self, action: str, target: Optional[str] = None):
        """Record an executed action for loop and branch tracking."""
        self.action_history.append(action)
        if target:
            self.target_history.append(target)

    def is_stuck_in_loop(self) -> Tuple[bool, str]:
        """Detect repetitive unhelpful actions or ping-pong clicks."""
        if len(self.target_history) >= self.max_loop_count + 1:
            recent = self.target_history[- (self.max_loop_count + 1):]
            if len(set(recent)) == 1:
                return True, f"Repeatedly targeted '{recent[0]}' {len(recent)} times"

        if len(self.action_history) >= 4:
            recent_actions = self.action_history[-4:]
            if recent_actions == ["wait", "wait", "wait", "wait"]:
                return True, "Consecutive idle wait cycles"
        return False, ""

    def assess_jev_capacity(
        self,
        screen_summary: str,
        goal: str,
        available_elements_count: int,
        last_action_failed: bool = False,
    ) -> CapabilityAssessment:
        """Let Jev self-assess if it can confidently make progress on this step."""
        is_loop, loop_reason = self.is_stuck_in_loop()
        if is_loop:
            return CapabilityAssessment(
                can_handle=False,
                confidence=0.1,
                reason=f"loop_detected: {loop_reason}",
            )

        if available_elements_count == 0 and not last_action_failed:
            return CapabilityAssessment(
                can_handle=False,
                confidence=0.2,
                reason="zero_elements_visible",
            )

        state_payload = {
            "task_goal": goal,
            "screen_text_snippet": screen_summary[:1500],
            "action_history": self.action_history[-4:],
        }

        questions = {
            "jev_can_handle": {
                "type": "choice",
                "criteria": {
                    "can_handle": (
                        "The next step is straightforward: a clear button to click, text to type, "
                        "or a standard UI pattern that directly advances the goal."
                    ),
                    "need_llm_help": (
                        "The UI is ambiguous, requires complex natural language inference, "
                        "unexpected error dialogues, or unconventional navigation beyond basic button clicks."
                    ),
                },
                "instructions": {
                    "goal": goal,
                    "rules": "Be honest about capability. If uncertain or in a confusing state, choose 'need_llm_help'.",
                },
            }
        }

        try:
            resp = self.client.query_systemone(state=state_payload, questions=questions)
            choice = resp.get_choice("jev_can_handle")
            if not choice:
                return CapabilityAssessment(can_handle=True, confidence=0.7, reason="default_fallback")

            can_handle = (choice.choice == "can_handle") and (choice.confidence >= self.confidence_threshold)
            return CapabilityAssessment(
                can_handle=can_handle,
                confidence=choice.confidence,
                reason="high_confidence" if can_handle else "low_confidence_or_complex",
                raw=choice.raw,
            )
        except Exception as e:
            # On connection hiccup, fall back to conservative judgment
            return CapabilityAssessment(can_handle=True, confidence=0.5, reason=f"query_error: {e}")

    def check_branch_health(
        self,
        current_ui_summary: str,
        goal: str,
        last_action: str,
    ) -> BranchHealth:
        """Detect if the agent drifted into an erroneous modal, irrelevant popup, or error screen."""
        state_payload = {
            "goal": goal,
            "last_action": last_action,
            "current_ui_sample": current_ui_summary[:1500],
        }

        questions = {
            "branch_status": {
                "type": "choice",
                "criteria": {
                    "on_track": "The UI is on the normal path toward fulfilling the goal.",
                    "wrong_modal": "An unwanted popup, search modal, dropdown, or advertising overlay opened.",
                    "error_dialog": "An error message, permission alert, or exception dialog appeared.",
                    "drifted": "The UI completely drifted into an unrelated application or section.",
                },
            }
        }

        try:
            resp = self.client.query_systemone(state=state_payload, questions=questions)
            choice = resp.get_choice("branch_status")
            status = choice.choice if choice else "on_track"

            if status == "wrong_modal":
                return BranchHealth(on_track=False, drift_type=status, confidence=choice.confidence, recommended_rollback="esc")
            elif status in ("error_dialog", "drifted"):
                return BranchHealth(on_track=False, drift_type=status, confidence=choice.confidence, recommended_rollback="back")
            return BranchHealth(on_track=True, drift_type="normal", confidence=1.0, recommended_rollback="none")
        except Exception:
            return BranchHealth(on_track=True, drift_type="normal", confidence=0.5, recommended_rollback="none")

    def execute_rollback(
        self,
        rollback_type: str,
        platform_instance: Any,
    ) -> bool:
        """Execute instantaneous compensatory rollback action to restore main branch."""
        print(f"  ⏪ [Branch Rollback] Detected wrong branch! Executing rollback: {rollback_type}")
        if rollback_type == "esc":
            platform_instance.press_key("escape")
            time.sleep(0.3)
            return True
        elif rollback_type == "back":
            mod_key = "cmd" if sys.platform == "darwin" else "alt"
            platform_instance.hotkey([mod_key, "["] if sys.platform == "darwin" else ["alt", "left"])
            time.sleep(0.3)
            return True
        return False

    def sniff_jev_reclaim(
        self,
        current_ui_summary: str,
        goal: str,
    ) -> ReclaimVerdict:
        """When LLM is driving, sniff in parallel whether Jev can take back control."""
        state_payload = {
            "goal": goal,
            "ui_state": current_ui_summary[:1500],
        }

        questions = {
            "can_reclaim": {
                "type": "choice",
                "criteria": {
                    "yes": "The screen is in a clean, predictable state (e.g. target window focused, input clear). Jev can execute directly.",
                    "no": "Still requires high-level planning or complex multi-step reasoning by LLM.",
                },
            }
        }

        try:
            resp = self.client.query_systemone(state=state_payload, questions=questions)
            choice = resp.get_choice("can_reclaim")
            can_rec = (choice.choice == "yes") if choice else False
            conf = choice.confidence if choice else 0.0
            return ReclaimVerdict(
                can_reclaim=can_rec and (conf >= 0.7),
                confidence=conf,
                rationale="State regularized; Jev ready to resume fast loop" if can_rec else "LLM still needed",
            )
        except Exception:
            return ReclaimVerdict(can_reclaim=False, confidence=0.0, rationale="sniff_error")
