"""Autonomous Browser Agent powered by TypeSafe Jev Decision Engine & Jev Judge."""

from __future__ import annotations

import base64
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from open_use.core.jev_judge import GoalVerdict, JevJudge
    from open_use.browser.browser import Browser, StalePage
    from open_use.browser.model import action_space, choose, field_context, field_text
    from open_use.browser.questions import MAX_STEPS
except ImportError:
    from ..core.jev_judge import GoalVerdict, JevJudge
    from .browser import Browser, StalePage
    from .model import action_space, choose, field_context, field_text
    from .questions import MAX_STEPS

logger = logging.getLogger("browser_use_jev.agent")


class Agent:
    """Browser agent that uses Jev for micro-actions and Jev Judge for verification."""

    def __init__(
        self,
        url: str,
        goals: str | List[str],
        *,
        record_dir: Optional[str | Path] = None,
        screenshots: bool = False,
        enable_judge: bool = True,
        min_judge_confidence: float = 0.5,
    ):
        task = goals.strip() if isinstance(goals, str) else "\n".join(goals).strip()
        if not task:
            raise ValueError("Supply a task/goal")
        plan = [task]
        self.pending_text = None
        self.browser = Browser(url)
        self.record_dir = Path(record_dir) if record_dir else None
        self.screenshots = screenshots or bool(record_dir)
        self.enable_judge = enable_judge
        self.min_judge_confidence = min_judge_confidence
        self.judge = JevJudge() if enable_judge else None

        try:
            page = self.browser.observe(screenshot=self.screenshots)
        except Exception:
            self.browser.close()
            raise

        self.state: Dict[str, Any] = dict(
            browser=self.browser,
            goal="\n".join(plan),
            page=page,
            decision=None,
            history=[],
            status="ready",
            plan=plan,
            plan_index=0,
            decisions=[],
            text_calls=[],
            elapsed_ms=0,
            started_at=None,
            record=bool(self.record_dir),
            verdict=None,
            judge_checks=[],
        )
        if self.record_dir:
            self.record_dir.mkdir(parents=True, exist_ok=True)
            (self.record_dir / "000000.jpg").write_bytes(base64.b64decode(page["screenshot"]))

    def snapshot(self) -> Dict[str, Any]:
        return {
            **{k: v for k, v in self.state.items() if k != "browser"},
            "elements": action_space(self.state["page"]["actions"])[0],
        }

    def command(self, name: str, body: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        body = body or {}
        state = self.state
        if name == "tick":
            try:
                self.command("predict", {})
                return self.command("act", {"fingerprint": state["page"]["fingerprint"]})
            except StalePage:
                state["decision"] = None
                state["status"] = "ready"
                state["page"] = state["browser"].observe(screenshot=self.screenshots)
                state["elapsed_ms"] = round((time.perf_counter() - state["started_at"]) * 1000)
                return self.snapshot()

        elif name == "predict":
            if not state["browser"]:
                raise ValueError("Browser not initialized")
            if state["started_at"] is None:
                state["started_at"] = time.perf_counter()
            if not state["browser"].fresh(state["page"]):
                state["page"] = state["browser"].observe(screenshot=self.screenshots)
            state["decision"] = None
            if state["status"] in {"done", "blocked"}:
                raise ValueError("This run has stopped.")
            if len(state["decisions"]) >= MAX_STEPS * 2:
                raise ValueError("Reached model-call budget")

            state["decision"] = choose(state["page"], state["goal"], state["history"])
            state["decisions"].append(
                {
                    **state["decision"],
                    "fingerprint": state["page"]["fingerprint"],
                    "elapsed_ms": round((time.perf_counter() - state["started_at"]) * 1000),
                }
            )
            state["status"] = "predicted"

        elif name == "act":
            decision, page = state["decision"], state["page"]
            if not decision or body.get("fingerprint") != page["fingerprint"]:
                raise ValueError("Observe and choose before acting")

            state["decision"] = None
            selected = decision["choice"]

            if selected in {"DONE", "BLOCKED"}:
                if not state["browser"].fresh(page):
                    state["status"] = "ready"
                    raise StalePage("Page changed since decision. Choose again.")

                if selected == "DONE" and self.enable_judge:
                    # Execute Jev Judge verification to avoid false-positive DONE stops
                    verdict: GoalVerdict = self.judge.judge_goal_completion(
                        page_state=page,
                        goal=state["goal"],
                        history=state["history"],
                    )
                    state["verdict"] = {
                        "is_satisfied": verdict.is_satisfied,
                        "confidence": verdict.confidence,
                        "score": verdict.score,
                        "probability": verdict.satisfaction_probability,
                        "latency_ms": verdict.latency_ms,
                    }
                    state["judge_checks"].append(state["verdict"])

                    if not verdict.is_satisfied:
                        logger.warning(
                            f"[JevJudge] Rejected premature DONE. Goal satisfied: {verdict.is_satisfied}, "
                            f"Score: {verdict.score:.2f}/3.0. Continuing task."
                        )
                        # Do not mark as done; re-observe and let the agent continue
                        state["status"] = "ready"
                        return self.snapshot()

                state["status"] = "done" if selected == "DONE" else "blocked"
                state["plan_index"] = int(selected == "DONE")
                state["elapsed_ms"] = round((time.perf_counter() - state["started_at"]) * 1000)
                return self.snapshot()

            action = next(a for a in page["actions"] if a["id"] == selected)
            if len(state["history"]) >= MAX_STEPS:
                state["status"] = "blocked"
                raise ValueError(f"Stopped at {MAX_STEPS}-action budget")

            text, helper = None, None
            if action["kind"] == "fill":
                if not state["browser"].fresh(page):
                    raise StalePage("Page changed before text generation. Choose again.")
                context = field_context(state["goal"], action, page, state["history"])
                if self.pending_text and self.pending_text[0] == context:
                    _, text, helper = self.pending_text
                else:
                    text, helper = field_text(context)
                    self.pending_text = (context, text, helper)
                    state["text_calls"].append({**helper, "field": action["label"], "value": text})

            state["browser"].act(action, page, text=text)
            self.pending_text = None
            state["elapsed_ms"] = round((time.perf_counter() - state["started_at"]) * 1000)

            state["history"].append(
                {
                    "step": len(state["history"]) + 1,
                    "action": action["label"],
                    "kind": action["kind"],
                    "choice": selected,
                    "probability": decision["probabilities"][selected],
                    "confidence": decision["confidence"],
                    "latency_ms": decision["latency_ms"],
                    "text": text,
                    "text_helper": helper["model"] if helper else None,
                    "text_latency_ms": helper["latency_ms"] if helper else 0,
                    "operation": decision["operation"],
                    "target": decision["target"],
                    "page_changed": None,
                    "url": page["url"],
                    "usage": decision["usage"],
                    "executed_ms": round((time.perf_counter() - state["started_at"]) * 1000),
                    "elapsed_ms": state["elapsed_ms"],
                }
            )
            state["page"] = state["browser"].observe(screenshot=self.screenshots)
            state["elapsed_ms"] = round((time.perf_counter() - state["started_at"]) * 1000)
            state["history"][-1].update(
                page_changed=state["page"]["fingerprint"] != page["fingerprint"],
                url=state["page"]["url"],
                elapsed_ms=state["elapsed_ms"],
            )
            if state["record"]:
                (self.record_dir / f"{state['elapsed_ms']:06d}.jpg").write_bytes(
                    base64.b64decode(state["page"]["screenshot"])
                )

            repeated = state["history"][-3:]
            state["status"] = (
                "blocked"
                if len(repeated) == 3 and all(h["page_changed"] is False and h["kind"] != "wait" for h in repeated)
                else "ready"
            )
        else:
            raise ValueError(f"Unknown command: {name}")

        return self.snapshot()

    def run(self):
        while self.state["status"] not in {"done", "blocked"}:
            yield self.command("tick")

    def close(self):
        if self.browser:
            self.browser.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
