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
from .desktop.agent import DesktopAgent
from .desktop.hal import get_current_platform


class OpenAgent:
    """Unified Orchestrator combining Web and OS Native capabilities."""

    def __init__(self, click_delay: float = 0.2):
        self.platform = get_current_platform()
        self.click_delay = click_delay

    def run_browser(self, url: str, goal: str, max_steps: int = 25) -> Dict[str, Any]:
        """Execute deep web navigation via CDP and Jev."""
        print(f"\n🌐 [OpenUse Web Engine] Launching browser for: {url}")
        with BrowserAgent(url=url, goals=goal) as agent:
            history = list(agent.run())
            snapshot = agent.snapshot()
            return {
                "status": snapshot.get("status"),
                "verdict": snapshot.get("verdict"),
                "history": history,
            }

    def run_desktop(self, goal: str, max_steps: int = 15) -> List[Any]:
        """Execute native desktop task via Hardware Abstraction Layer."""
        print(f"\n💻 [OpenUse Desktop Engine] Operating on {sys.platform} for: {goal}")
        agent = DesktopAgent(goal=goal, platform=self.platform, max_steps=max_steps, click_delay=self.click_delay)
        return agent.run()

    def run(self, goal: str, mode: str = "auto", url: Optional[str] = None, max_steps: int = 20) -> Any:
        """Intelligent dispatch: determine whether to run Web, Desktop, or Chained."""
        if mode == "browser" or url:
            target_url = url
            if not target_url:
                url_match = re.search(r"https?://[^\s]+", goal)
                target_url = url_match.group(0) if url_match else "https://google.com"
            web_goal = goal.replace(target_url, "").strip() or goal
            return self.run_browser(url=target_url, goal=web_goal, max_steps=max_steps)

        if mode == "desktop":
            return self.run_desktop(goal=goal, max_steps=max_steps)

        # Auto mode: heuristic URL detection
        url_match = re.search(r"https?://[^\s]+", goal)
        if url_match:
            target_url = url_match.group(0)
            web_goal = goal.replace(target_url, "").strip() or "Browse and fulfill task"
            return self.run_browser(url=target_url, goal=web_goal, max_steps=max_steps)
        else:
            return self.run_desktop(goal=goal, max_steps=max_steps)


# Backwards compatibility alias
OmniAgent = OpenAgent
