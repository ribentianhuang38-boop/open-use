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
    ):
        self.goal = goal
        self.platform = platform or get_current_platform()
        self.max_steps = max_steps
        self.click_delay = click_delay
        self.scale = scale

        self.client = JevClient()
        self.judge = JevJudge(client=self.client) if enable_judge else None

        self.history: List[Dict[str, Any]] = []
        self.step_count = 0
        self._recent_targets: List[str] = []

    def _detect_loop(self, target_label: str) -> bool:
        self._recent_targets.append(target_label)
        if len(self._recent_targets) > 6:
            self._recent_targets.pop(0)
        return len(self._recent_targets) >= 3 and len(set(self._recent_targets[-3:])) == 1

    def _batched_decision_and_safety(self, elements: List[UIElement]) -> Dict[str, Any]:
        """Prioritize elements by goal semantics, number buttons, and query Jev."""
        goal_lower = self.goal.lower()

        def _score_el(el: UIElement) -> int:
            lbl = el.label.lower()
            if lbl and (lbl in goal_lower or any(part in lbl for part in goal_lower.split() if len(part) >= 2)):
                return 0
            if el.category in ("button", "input", "control"):
                return 1
            return 2

        prioritized = sorted(elements, key=_score_el)

        criteria: Dict[str, str] = {}
        for el in prioritized[:35]:
            cat_name = el.category.upper()
            criteria[f"btn_{el.id}"] = f"[{el.id}] {cat_name} '{el.label}' at point {el.center}"

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

        # 1. Capture screen
        raw_shot = self.platform.capture_screen()

        # 2. Detect UI elements (Vision on Mac / RapidOCR on Win)
        elements = self.platform.detect_ui_elements(raw_shot, scale=self.scale)

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
        if raw_choice in ("type_text", "press_return", "scroll_down", "scroll_up", "wait", "done"):
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

        # Loop break
        if self._detect_loop(target_label):
            print(f"  ⚠️ Loop detected! Switching to wait.")
            action_type = "wait"

        print(f"  👉 Step {self.step_count}: Decision={raw_choice} -> Action={action_type} Target='{target_label}' Point={target_point}")

        # 5. Native Execution
        if action_type == "click" and target_point:
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

        # 6. Judge verification
        is_satisfied = (action_type == "done")
        judge_score = 1.0 if is_satisfied else 0.0

        step_res = DesktopStepResult(
            step=self.step_count,
            action_type=action_type,
            target_label=target_label,
            target_point=target_point,
            is_goal_satisfied=is_satisfied,
            judge_score=judge_score,
            latency_ms=int((time.perf_counter() - t_start) * 1000),
        )
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
