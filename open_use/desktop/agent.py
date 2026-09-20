"""Cross-Platform Desktop Agent powered by HAL and Jev System One.

Runs transparently on both macOS (Apple Vision) and Windows (RapidOCR ONNX).
"""

from __future__ import annotations

import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..core.jev_client import JevClient
from ..core.jev_judge import JevJudge
from ..core.dual_core import DualCoreOrchestrator, ControllerMode, CapabilityAssessment, BranchHealth
from ..core.jev_gate import JevContext
from .hal import DesktopPlatform, UIElement, get_current_platform


@dataclass
class DesktopStepResult:
    step: int
    action_type: str
    target_label: Optional[str]
    target_point: Optional[List[int]]
    is_goal_satisfied: bool
    judge_score: float
    latency_ms: int


class DesktopAgent:
    """Universal Desktop Agent operating across macOS and Windows."""

    COMPLETION_KEYWORDS = {
        "已发送", "发送成功", "已完成", "Success", "Sent", "Done", "Copied",
        "已复制", "Saved", "已保存", "成功", "Complete",
    }

    def __init__(
        self,
        goal: str,
        platform: Optional[DesktopPlatform] = None,
        max_steps: int = 15,
        click_delay: float = 0.2,
        scale: float = 1.0 if sys.platform == "win32" else 2.0,
        enable_judge: bool = True,
        dry_run: bool = False,
        target_app: Optional[str] = None,
    ):
        self.goal = goal
        self.platform = platform or get_current_platform()
        self.max_steps = max_steps
        self.click_delay = click_delay
        self.scale = scale
        self.dry_run = dry_run
        
        # Auto-infer target app from goal if not explicitly passed
        if target_app:
            self.target_app = target_app
        else:
            goal_lower = goal.lower()
            if "qq" in goal_lower:
                self.target_app = "QQ"
            elif "wechat" in goal_lower or "微信" in goal_lower:
                self.target_app = "WeChat"
            else:
                self.target_app = None

        self.client = JevClient()
        self.judge = JevJudge(client=self.client) if enable_judge else None
        self.orchestrator = DualCoreOrchestrator(client=self.client)

        self.history: List[Dict[str, Any]] = []
        self.step_count = 0
        self._recent_targets: List[str] = []
        self.consecutive_wait_count = 0

    def _detect_loop(self, target_label: str) -> bool:
        self._recent_targets.append(target_label)
        if len(self._recent_targets) > 6:
            self._recent_targets.pop(0)
        return len(self._recent_targets) >= 3 and len(set(self._recent_targets[-3:])) == 1

    def _batched_decision_and_safety(self, elements: List[UIElement]) -> Dict[str, Any]:
        """Prioritize elements by goal semantics using fuzzy matching, number buttons, and query Jev."""
        import difflib
        goal_lower = self.goal.lower()
        goal_tokens = [t for t in re.split(r'[\s,，.。!！?？]+', goal_lower) if len(t) >= 2]

        def _score_el(el: UIElement) -> float:
            lbl = el.label.lower().strip()
            if not lbl:
                return 2.0
            # 1. Exact substring
            if lbl in goal_lower or any(t in lbl for t in goal_tokens):
                return 0.0
            # 2. Fuzzy similarity (catches OCR character distortions, e.g., 腺 vs 𣊊)
            max_sim = 0.0
            for token in goal_tokens:
                sim = difflib.SequenceMatcher(None, lbl, token).ratio()
                if sim > max_sim:
                    max_sim = sim
            if max_sim >= 0.5:
                return 0.1 - (max_sim * 0.1)  # High priority between 0.0 and 0.05

            if el.category in ("button", "input", "control"):
                return 1.0
            return 2.0

        prioritized = sorted(elements, key=_score_el)

        criteria: Dict[str, str] = {}
        for el in prioritized[:35]:
            cat_name = el.category.upper()
            criteria[f"btn_{el.id}"] = f"[{el.id}] {cat_name} '{el.label}' at point {el.center}"

        criteria["paste_and_send"] = "Paste current clipboard content (image or text) into focused area and send immediately with Return key"
        criteria["type_text"] = "Type text into the currently focused input field"
        criteria["press_return"] = "Press the Return/Enter key"
        criteria["scroll_down"] = "Scroll down to see more content"
        criteria["scroll_up"] = "Scroll up to see previous content"
        criteria["wait"] = "Wait 1 second for the UI or loading to complete"
        criteria["done"] = "The user goal is already completely fulfilled; stop execution"

        state_payload = {
            "task_goal": self.goal,
            "step": self.step_count,
            "platform": sys.platform,
            "numbered_buttons": [
                f"[{el.id}] {el.category.upper()}: '{el.label}' @ {el.center}"
                for el in prioritized[:45]
            ],
            "recent_actions": self.history[-4:],
        }

        questions = {
            "next_step_action": {
                "type": "choice",
                "criteria": criteria,
                "instructions": {
                    "goal": self.goal,
                    "rules": (
                        "Select the button or action option that makes the most direct progress toward the goal. "
                        "If the goal is achieved, select 'done'. "
                        "If text needs to be typed, select 'type_text'. "
                        "Avoid selecting the same button repeatedly."
                    ),
                },
            },
        }

        resp = self.client.query_systemone(state=state_payload, questions=questions)
        return {
            "decision": resp.get_choice("next_step_action"),
            "latency_ms": resp.latency_ms,
        }

    def step(self) -> DesktopStepResult:
        """Single perceive -> decide -> act step."""
        self.step_count += 1
        t_start = time.perf_counter()

        # 1. Capture screen (targeted window if available) & detect UI elements
        if hasattr(self.platform, "capture_window"):
            cap_res = self.platform.capture_window(self.target_app)
            if isinstance(cap_res, tuple) and len(cap_res) == 2:
                raw_shot, offset = cap_res
            else:
                raw_shot, offset = cap_res, (0, 0)
        else:
            raw_shot, offset = self.platform.capture_screen(), (0, 0)

        try:
            try:
                elements = self.platform.detect_ui_elements(raw_shot, scale=self.scale, offset=offset)
            except TypeError:
                elements = self.platform.detect_ui_elements(raw_shot, scale=self.scale)
        finally:
            self.platform.cleanup_screenshot(raw_shot)
        screen_summary = " ".join(e.label for e in elements[:35])

        # 2.1 Wrong Branch Monitor & Auto-Rollback
        last_action_name = self.history[-1]["action"] if self.history else "none"
        branch = self.orchestrator.check_branch_health(screen_summary, self.goal, last_action=last_action_name)
        if not branch.on_track and branch.recommended_rollback != "none":
            with JevContext.session(step=self.step_count, decision_token=f"rollback_{branch.recommended_rollback}"):
                self.orchestrator.execute_rollback(branch.recommended_rollback, self.platform)
            # Re-capture normalized screen after rollback
            time.sleep(0.3)
            if hasattr(self.platform, "capture_window"):
                cap_res = self.platform.capture_window(self.target_app)
                if isinstance(cap_res, tuple) and len(cap_res) == 2:
                    raw_shot, offset = cap_res
                else:
                    raw_shot, offset = cap_res, (0, 0)
            else:
                raw_shot, offset = self.platform.capture_screen(), (0, 0)
            try:
                try:
                    elements = self.platform.detect_ui_elements(raw_shot, scale=self.scale, offset=offset)
                except TypeError:
                    elements = self.platform.detect_ui_elements(raw_shot, scale=self.scale)
            finally:
                self.platform.cleanup_screenshot(raw_shot)
            screen_summary = " ".join(e.label for e in elements[:35])

        # 2.2 Jev Self-Assessment: Can I handle this?
        capacity = self.orchestrator.assess_jev_capacity(
            screen_summary=screen_summary,
            goal=self.goal,
            available_elements_count=len(elements),
        )
        if not capacity.can_handle:
            conf_val = float(capacity.confidence) if isinstance(capacity.confidence, (int, float)) else 0.0
            print(f"  🛑 [Jev Handover] Jev self-assessed inability to proceed: '{capacity.reason}' (conf={conf_val:.2f}). Escalate to LLM!")
            return DesktopStepResult(
                step=self.step_count,
                action_type="escalate_to_llm",
                target_label=capacity.reason,
                target_point=None,
                is_goal_satisfied=False,
                judge_score=0.0,
                latency_ms=int((time.perf_counter() - t_start) * 1000),
            )

        if not elements:
            return DesktopStepResult(
                step=self.step_count,
                action_type="wait",
                target_label="no_elements",
                target_point=None,
                is_goal_satisfied=False,
                judge_score=0.0,
                latency_ms=int((time.perf_counter() - t_start) * 1000),
            )

        # 3. Jev Decision
        batch_result = self._batched_decision_and_safety(elements)
        decision = batch_result["decision"]
        raw_choice = decision.choice if decision else "wait"

        # 4. Parse choice
        if raw_choice in ("paste_and_send", "type_text", "press_return", "scroll_down", "scroll_up", "wait", "done"):
            action_type = raw_choice
            chosen_element = None
            target_point = None
            target_label = raw_choice
        else:
            num_match = re.search(r'\d+', raw_choice)
            target_id = num_match.group(0) if num_match else raw_choice
            chosen_element = next((e for e in elements if e.id == target_id), None)
            if chosen_element:
                action_type = "click"
                target_point = chosen_element.center
                target_label = chosen_element.label
            else:
                action_type = "wait"
                target_point = None
                target_label = raw_choice

        # Loop break & wait impasse check
        if self._detect_loop(target_label):
            print(f"  ⚠️ Loop detected! Switching to wait.")
            action_type = "wait"

        if action_type == "wait":
            self.consecutive_wait_count += 1
        else:
            self.consecutive_wait_count = 0

        if self.consecutive_wait_count >= 3:
            print(f"  🛑 [Jev Impasse] Encountered 3 consecutive wait cycles without progress. Escalate to LLM!")
            return DesktopStepResult(
                step=self.step_count,
                action_type="escalate_to_llm",
                target_label="consecutive_wait_impasse",
                target_point=None,
                is_goal_satisfied=False,
                judge_score=0.0,
                latency_ms=int((time.perf_counter() - t_start) * 1000),
            )

        print(f"  👉 Step {self.step_count}: Decision={raw_choice} -> Action={action_type} Target='{target_label}' Point={target_point}")

        # 5. Native Execution
        if not self.dry_run:
            with JevContext.session(step=self.step_count, decision_token=raw_choice):
                if action_type == "paste_and_send":
                    mod_key = "cmd" if sys.platform == "darwin" else "ctrl"
                    self.platform.hotkey([mod_key, "v"])
                    time.sleep(0.4)
                    self.platform.press_key("return")
                    time.sleep(self.click_delay)
                elif action_type == "type_text":
                    text_match = re.search(r'["\']([^"\']+)["\']', self.goal)
                    text_to_type = text_match.group(1) if text_match else ""
                    if not text_to_type:
                        for kw in ("输入", "type", "send", "发送"):
                            if kw in self.goal:
                                parts = self.goal.split(kw, 1)
                                if len(parts) > 1 and parts[1].strip():
                                    text_to_type = parts[1].strip().split()[0]
                                    break
                    if text_to_type:
                        self.platform.type_text(text_to_type)
                        time.sleep(self.click_delay)
                elif action_type == "click" and target_point:
                    self.platform.click(target_point[0], target_point[1])
                    time.sleep(self.click_delay)
                elif action_type == "press_return":
                    self.platform.press_key("return")
                    time.sleep(self.click_delay)
                elif action_type == "scroll_down":
                    self.platform.scroll(500, 400, -5)
                    time.sleep(self.click_delay)
                elif action_type == "scroll_up":
                    self.platform.scroll(500, 400, 5)
                    time.sleep(self.click_delay)
                elif action_type == "wait":
                    time.sleep(0.8)
        else:
            print(f"  [DRY RUN] Would execute action: {action_type} target: '{target_label}' point: {target_point}")

        # 6. Judge verification (M-03: strictly rely on JevJudge, avoid naive keyword_hit & step >= 2)
        if action_type == "done":
            is_satisfied = True
            judge_score = 1.0
        elif self.judge:
            verdict = self.judge.judge_goal_completion(
                screen_state={"visible_text": screen_summary, "active_window": ""},
                goal=self.goal,
                history=self.history,
            )
            is_satisfied = verdict.is_satisfied
            judge_score = verdict.score
        else:
            is_satisfied = False
            judge_score = 0.0

        step_res = DesktopStepResult(
            step=self.step_count,
            action_type=action_type,
            target_label=target_label,
            target_point=target_point,
            is_goal_satisfied=is_satisfied,
            judge_score=judge_score,
            latency_ms=int((time.perf_counter() - t_start) * 1000),
        )
        self.orchestrator.record_step(action_type, target_label)
        self.history.append({
            "step": self.step_count,
            "action": action_type,
            "target": target_label,
            "point": target_point,
        })
        return step_res

    def run(self) -> List[DesktopStepResult]:
        """Execute autonomous loop until goal completion or max steps."""
        results: List[DesktopStepResult] = []
        print(f"\n🚀 [Omni Desktop Agent] Starting goal on {sys.platform}: '{self.goal}'")
        for _ in range(self.max_steps):
            res = self.step()
            results.append(res)
            if res.is_goal_satisfied or res.action_type == "done":
                print(f"✅ Goal satisfied in {self.step_count} steps!")
                break
        return results
