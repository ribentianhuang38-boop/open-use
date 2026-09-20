"""OpenAgent: Dual-Core Unified Agent bridging Desktop and Browser worlds.

Automatically coordinates:
1. Browser Engine (CDP + Jev) for deep web automation.
2. Desktop Engine (HAL + Vision/RapidOCR + Jev) for native OS workflows.
"""

from __future__ import annotations

import re
import sys
from typing import Any, Dict, List, Optional

from .browser.agent import Agent as BrowserAgent
from .core.security import validate_safe_url
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
            }

        with BrowserAgent(url=safe_url, goals=goal) as agent:
            history = list(agent.run())
            snapshot = agent.snapshot()
            return {
                "status": snapshot.get("status"),
                "verdict": snapshot.get("verdict"),
                "history": history,
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

    def run(
        self,
        goal: str,
        mode: str = "auto",
        url: Optional[str] = None,
        max_steps: int = 20,
        dry_run: bool = False,
    ) -> Any:
        """Intelligent dispatch: determine whether to run Web, Desktop, or Chained."""
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
