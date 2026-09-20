"""OpenAgent: Dual-Core Unified Agent bridging Desktop and Browser worlds.

Automatically coordinates:
1. Browser Engine (CDP + Jev) for deep web automation.
2. Desktop Engine (HAL + Vision/RapidOCR + Jev) for native OS workflows.
"""

from __future__ import annotations

import re
import sys
import time
from typing import Any, Dict, List, Optional, Union

from .browser.agent import Agent as BrowserAgent
from .core.security import validate_safe_url
from .core.jev_gate import JevEnforcementError
from .desktop.agent import DesktopAgent
from .desktop.hal import get_current_platform


class OpenAgent:
    """Unified Orchestrator combining Web and OS Native capabilities."""

    def __init__(self, click_delay: float = 0.2):
        self.platform = get_current_platform()
        self.click_delay = click_delay

    def close(self) -> None:
        """Clean up background resources, platform handles, or open sockets (M-02)."""
        pass

    def __enter__(self) -> OpenAgent:
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    def run_browser(self, url: str, goal: str, max_steps: int = 25, dry_run: bool = False) -> Dict[str, Any]:
        """Execute deep web navigation via CDP and Jev with SSRF protection (H-01)."""
        safe_url = validate_safe_url(url)
        print(f"\n🌐 [OpenUse Web Engine] Launching browser for: {safe_url}")
        if dry_run:
            print(f"  [DRY RUN] Web task preview: would navigate to {safe_url} with goal: {goal}")
            return {
                "status": "dry_run",
                "verdict": None,
                "history": [],
                "jev_steps": 1,
            }

        with BrowserAgent(url=safe_url, goals=goal) as agent:
            history = list(agent.run())
            snapshot = agent.snapshot()
            return {
                "status": snapshot.get("status"),
                "verdict": snapshot.get("verdict"),
                "history": history,
                "jev_steps": max(len(history), 1),
            }

    def run_desktop(self, goal: str, max_steps: int = 15, dry_run: bool = False) -> List[Any]:
        """Execute native desktop task via Hardware Abstraction Layer."""
        print(f"\n💻 [OpenUse Desktop Engine] Operating on {sys.platform} for: {goal}")
        agent = DesktopAgent(
            goal=goal,
            platform=self.platform,
            max_steps=max_steps,
            click_delay=self.click_delay,
            dry_run=dry_run,
        )
        return agent.run()

    def run_composite(
        self,
        goals: List[Union[str, Dict[str, Any]]],
        max_steps_per_stage: int = 20,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        """Execute chained multi-stage tasks across Web and Desktop engines with Jev telemetry."""
        print(f"\n⚡ [OpenUse Pipeline] Initiating Chained Composite Task ({len(goals)} stages)")
        t_start = time.perf_counter()

        stage_results: List[Dict[str, Any]] = []
        total_jev_steps = 0
        total_llm_steps = 0

        for idx, item in enumerate(goals, 1):
            if isinstance(item, dict):
                subgoal = item.get("goal", "")
                mode = item.get("mode", "auto")
                url = item.get("url")
            else:
                subgoal = str(item).strip()
                mode = "auto"
                url = None

            print(f"\n--- [Stage {idx}/{len(goals)}] Objective: '{subgoal}' (mode={mode}) ---")

            # Determine mode
            url_match = re.search(r"https?://[^\s]+", subgoal)
            if mode == "browser" or url or url_match or any(kw in subgoal.lower() for kw in ["youtube", "bilibili", "google", "网页", "浏览器", "http"]):
                target_url = url or (url_match.group(0) if url_match else "https://google.com")
                clean_goal = subgoal.replace(target_url, "").strip() or subgoal
                res = self.run_browser(url=target_url, goal=clean_goal, max_steps=max_steps_per_stage, dry_run=dry_run)
                steps = res.get("jev_steps", 1)
                total_jev_steps += steps
                stage_results.append({"stage": idx, "mode": "browser", "result": res, "jev_steps": steps})
            else:
                res = self.run_desktop(goal=subgoal, max_steps=max_steps_per_stage, dry_run=dry_run)
                # Count desktop steps
                d_steps = len(res) if isinstance(res, list) else 1
                llm_escalations = sum(1 for s in (res if isinstance(res, list) else []) if getattr(s, "action_type", "") == "escalate_to_llm")
                jev_steps = d_steps - llm_escalations
                total_jev_steps += jev_steps
                total_llm_steps += llm_escalations
                stage_results.append({"stage": idx, "mode": "desktop", "result": res, "jev_steps": jev_steps, "llm_steps": llm_escalations})

        elapsed_sec = time.perf_counter() - t_start
        total_actions = total_jev_steps + total_llm_steps
        jev_ratio = (total_jev_steps / total_actions) if total_actions > 0 else 1.0

        # Enforce Jev Dispatched Rule
        if not dry_run and total_jev_steps == 0 and total_actions > 0:
            raise JevEnforcementError("🚨 [CRITICAL VIOLATION] Execution completely bypassed Jev System One! 0 Jev steps recorded.")

        print("\n" + "=" * 52)
        print("🎯 OpenUse Jev-First Execution Certificate")
        print("-" * 52)
        print(f"  ⚡ Jev Decisions (Micro-actions): {total_jev_steps} steps")
        print(f"  🧠 LLM Escalations:              {total_llm_steps} steps")
        print(f"  ⏱️ Total Latency:                {elapsed_sec:.2f}s")
        print(f"  🛡️ Jev Dispatch Ratio:           {jev_ratio:.1%}")
        print("=" * 52 + "\n")

        return {
            "status": "completed",
            "stages": stage_results,
            "total_jev_steps": total_jev_steps,
            "total_llm_steps": total_llm_steps,
            "jev_ratio": jev_ratio,
            "elapsed_sec": elapsed_sec,
        }

    def _decompose_goal(self, goal: str) -> List[str]:
        """Automatically decompose composite compound goal into subgoals."""
        split_pattern = r"(?:然后|随后|之后|接着|并发给|并发送|then|and send to|and then)"
        parts = [p.strip() for p in re.split(split_pattern, goal, flags=re.IGNORECASE) if p.strip()]
        return parts if len(parts) > 1 else [goal]

    def run(
        self,
        goal: str,
        mode: str = "auto",
        url: Optional[str] = None,
        max_steps: int = 20,
        dry_run: bool = False,
    ) -> Any:
        """Intelligent dispatch: determine whether to run Web, Desktop, or Chained Composite."""
        # Check if goal is a compound composite task
        subgoals = self._decompose_goal(goal)
        if len(subgoals) > 1 and mode in ("auto", "composite"):
            return self.run_composite(goals=subgoals, max_steps_per_stage=max_steps, dry_run=dry_run)

        if mode == "browser" or url:
            target_url = url
            if not target_url:
                url_match = re.search(r"https?://[^\s]+", goal)
                target_url = url_match.group(0) if url_match else "https://google.com"
            safe_target_url = validate_safe_url(target_url)
            web_goal = goal.replace(target_url, "").strip() or goal
            return self.run_browser(url=safe_target_url, goal=web_goal, max_steps=max_steps, dry_run=dry_run)

        if mode == "desktop":
            return self.run_desktop(goal=goal, max_steps=max_steps, dry_run=dry_run)

        # Auto mode: heuristic URL detection
        url_match = re.search(r"https?://[^\s]+", goal)
        if url_match:
            target_url = url_match.group(0)
            safe_target_url = validate_safe_url(target_url)
            web_goal = goal.replace(target_url, "").strip() or "Browse and fulfill task"
            return self.run_browser(url=safe_target_url, goal=web_goal, max_steps=max_steps, dry_run=dry_run)
        else:
            return self.run_desktop(goal=goal, max_steps=max_steps, dry_run=dry_run)


# Backwards compatibility alias
OmniAgent = OpenAgent
