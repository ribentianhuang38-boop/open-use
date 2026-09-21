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
from .llm_agent import LLMProxyAgent, LLMStepDecision


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
        llm_agent: Optional[LLMProxyAgent] = None,
        confidence_threshold: float = 0.50,
        max_loop_count: int = 2,
    ):
        self.client = client or JevClient()
        self.llm_agent = llm_agent or LLMProxyAgent()
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
                        "Standard desktop UI micro-action available: clicking a search box, button, "
                        "or contact item, typing/pasting text or contact numbers, pasting message payload, or pressing Return."
                    ),
                    "need_llm_help": (
                        "Unrecoverable deadlock, unexpected OS system permission dialog, "
                        "or complex mathematical reasoning requiring high-order cognitive intervention."
                    ),
                },
                "instructions": {
                    "goal": goal,
                    "rules": "Default to 'can_handle' for standard desktop application navigation, typing, and sending.",
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
                    "on_track": "The UI is on the normal path toward fulfilling the goal. Normal contact search results, chat conversation windows, message inputs, or app windows are ALWAYS on_track.",
                    "wrong_modal": "An unwanted advertising popup, unrelated modal dialog, or intrusive notification that blocks the user's path.",
                    "error_dialog": "A crash dialog, system error popup, or exception alert.",
                    "drifted": "The window switched completely to an entirely unrelated application or desktop space.",
                },
                "instructions": {
                    "goal": goal,
                    "rules": "Contact dropdowns, search result items, conversation panes, message history, and input fields are valid intermediate states, NOT wrong modals. Only trigger rollback on genuine unwanted blocking modals or error alerts with high confidence.",
                },
            }
        }

        try:
            resp = self.client.query_systemone(state=state_payload, questions=questions)
            choice = resp.get_choice("branch_status")
            status = choice.choice if choice else "on_track"

            if status == "wrong_modal" and (choice.confidence >= 0.85):
                return BranchHealth(on_track=False, drift_type=status, confidence=choice.confidence, recommended_rollback="esc")
            elif status in ("error_dialog", "drifted") and (choice.confidence >= 0.85):
                return BranchHealth(on_track=False, drift_type=status, confidence=choice.confidence, recommended_rollback="back")
            return BranchHealth(on_track=True, drift_type="normal", confidence=choice.confidence if choice else 1.0, recommended_rollback="none")
        except Exception:
            return BranchHealth(on_track=True, drift_type="normal", confidence=0.5, recommended_rollback="none")

    def execute_rollback(
        self,
        rollback_type: str,
        platform_instance: Any,
        target_app: Optional[str] = None,
    ) -> bool:
        """Execute instantaneous compensatory rollback action to restore main branch."""
        print(f"  ⏪ [Branch Rollback] Detected wrong branch! Executing rollback: {rollback_type}")
        if rollback_type == "esc":
            platform_instance.press_key("escape")
            time.sleep(0.3)
            return True
        elif rollback_type in ("back", "drifted"):
            if target_app and hasattr(platform_instance, "activate_app"):
                print(f"  ⏪ [Branch Rollback] Re-focusing target application: {target_app}")
                platform_instance.activate_app(target_app)
                time.sleep(0.4)
                return True
            else:
                if hasattr(platform_instance, "hotkey"):
                    platform_instance.hotkey(["cmd", "["])
                else:
                    platform_instance.press_key("escape")
                time.sleep(0.3)
                return True
        return False

    def query_unified_step(
        self,
        goal: str,
        screen_summary: str,
        prioritized_elements: List[Any],
        action_criteria: Dict[str, str],
        step_number: int,
        last_action: str = "none",
        history: Optional[List[Dict[str, Any]]] = None,
        instructions_rule: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Execute a single unified Jev query combining branch health, capacity self-assessment,
        action decision, and goal completion in ~500ms (replacing 4 serial requests).
        """
        is_loop, loop_reason = self.is_stuck_in_loop()
        if is_loop:
            return {
                "branch_status": "normal",
                "recommended_rollback": "none",
                "can_handle": False,
                "capacity_confidence": 0.1,
                "capacity_reason": f"loop_detected: {loop_reason}",
                "action_choice": "wait",
                "action_confidence": 0.0,
                "is_goal_completed": False,
                "completion_confidence": 0.0,
                "latency_ms": 0,
            }

        state_payload = {
            "task_goal": goal,
            "step": step_number,
            "platform": sys.platform,
            "numbered_buttons": [
                f"[{el.id}] {el.category.upper()}: '{el.label}' @ {el.center}"
                for el in prioritized_elements[:45]
            ],
            "recent_actions": (history or [])[-4:],
            "screen_text_snippet": screen_summary[:1500],
            "last_action": last_action,
        }

        questions = {
            "branch_status": {
                "type": "choice",
                "criteria": {
                    "normal": "The UI is on the normal path toward fulfilling the goal. Normal contact search results, chat conversation windows, message inputs, or app windows are ALWAYS on_track.",
                    "wrong_modal": "An unwanted advertising popup, unrelated modal dialog, or intrusive notification that blocks the user's path.",
                    "error_dialog": "A crash dialog, system error popup, or exception alert.",
                    "drifted": "The window switched completely to an entirely unrelated application or desktop space.",
                },
                "instructions": {
                    "goal": goal,
                    "rules": "Contact dropdowns, search result items, conversation panes, message history, and input fields are valid intermediate states, NOT wrong modals.",
                },
            },
            "can_handle": {
                "type": "choice",
                "criteria": {
                    "can_handle": "Standard desktop UI micro-action available: clicking a search box, button, or contact item, typing/pasting text, pasting message payload, or pressing Return.",
                    "need_llm_help": "Unrecoverable deadlock, unexpected OS system permission dialog, or complex reasoning requiring high-order cognitive intervention.",
                },
                "instructions": {
                    "goal": goal,
                    "rules": "Default to 'can_handle' for standard desktop application navigation, typing, and sending.",
                },
            },
            "next_step_action": {
                "type": "choice",
                "criteria": action_criteria,
                "instructions": {
                    "goal": goal,
                    "rules": instructions_rule or (
                        "Carefully inspect the screen. "
                        "If the target contact's chat window is already visible/active on screen, select 'paste_and_send' immediately. "
                        "If the message has already been sent into the chat, select 'done'. "
                        "Only click search or type if the target chat is NOT currently open."
                    ),
                },
            },
            "goal_completion": {
                "type": "choice",
                "criteria": {
                    "in_progress": "The goal is not yet completed; further actions are required.",
                    "completed": "The goal has been completely achieved on screen (e.g. message sent and visible).",
                },
                "instructions": {
                    "goal": goal,
                    "rules": "Select 'completed' only if the requested message/information has actually been sent and displayed in the target chat conversation.",
                },
            },
        }

        try:
            resp = self.client.query_systemone(state=state_payload, questions=questions)
            branch_choice = resp.get_choice("branch_status")
            capacity_choice = resp.get_choice("can_handle")
            action_choice = resp.get_choice("next_step_action")
            comp_choice = resp.get_choice("goal_completion")

            branch_status = branch_choice.choice if branch_choice else "normal"
            branch_conf = branch_choice.confidence if branch_choice else 1.0

            can_handle = True
            if capacity_choice:
                if capacity_choice.choice == "need_llm_help":
                    can_handle = False
                elif capacity_choice.choice == "can_handle":
                    can_handle = (capacity_choice.confidence >= self.confidence_threshold) if isinstance(capacity_choice.confidence, (int, float)) else True
                else:
                    can_handle = True

            # Rollback recommendation
            rollback = "none"
            if branch_status == "wrong_modal" and isinstance(branch_conf, (int, float)) and branch_conf >= 0.85:
                rollback = "esc"
            elif branch_status in ("error_dialog", "drifted") and isinstance(branch_conf, (int, float)) and branch_conf >= 0.85:
                rollback = "back"

            is_completed = (comp_choice.choice == "completed" and comp_choice.confidence >= 0.70) if comp_choice else False

            return {
                "branch_status": branch_status,
                "branch_confidence": branch_conf,
                "recommended_rollback": rollback,
                "can_handle": can_handle,
                "capacity_confidence": capacity_choice.confidence if capacity_choice else 0.7,
                "capacity_reason": "high_confidence" if can_handle else "low_confidence_or_complex",
                "action_choice": action_choice.choice if action_choice else "wait",
                "action_confidence": action_choice.confidence if action_choice else 0.5,
                "is_goal_completed": is_completed,
                "completion_confidence": comp_choice.confidence if comp_choice else 0.0,
                "latency_ms": resp.latency_ms,
            }
        except Exception as exc:
            # Fallback on network/connection issue
            return {
                "branch_status": "normal",
                "branch_confidence": 0.5,
                "recommended_rollback": "none",
                "can_handle": True,
                "capacity_confidence": 0.5,
                "capacity_reason": f"unified_query_fallback: {exc}",
                "action_choice": "wait",
                "action_confidence": 0.5,
                "is_goal_completed": False,
                "completion_confidence": 0.0,
                "latency_ms": 0,
            }

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

    def maybe_reclaim_control(
        self,
        current_ui_summary: str = "",
        goal: str = "",
        screen_summary: Optional[str] = None,
    ) -> bool:
        """Parallel reclamation check: If currently under LLM, evaluate if Jev can safely take back control."""
        if self.current_mode != ControllerMode.SYSTEM_2_LLM:
            return False

        summary = screen_summary if screen_summary is not None else current_ui_summary
        verdict = self.sniff_jev_reclaim(summary, goal)
        if verdict.can_reclaim:
            print(f"\n🔄 [Jev Control Reclaimed] State regularized! Handing control back to Jev System One. (conf={verdict.confidence:.2f}, reason='{verdict.rationale}')")
            self.current_mode = ControllerMode.SYSTEM_1_JEV
            return True
        return False

    def escalate_and_act(
        self,
        goal: str,
        escalation_reason: str,
        screen_summary: str,
        image_path: Optional[str] = None,
        elements: Optional[List[Any]] = None,
        history: Optional[List[Dict[str, Any]]] = None,
    ) -> LLMStepDecision:
        """Hand off execution to the System 2 LLM Proxy Agent to break deadlocks."""
        self.current_mode = ControllerMode.SYSTEM_2_LLM
        decision = self.llm_agent.act(
            goal=goal,
            escalation_reason=escalation_reason,
            screen_summary=screen_summary,
            image_path=image_path,
            elements=elements,
            history=history,
        )
        self.record_step(decision.action_type, decision.target_label)
        return decision
