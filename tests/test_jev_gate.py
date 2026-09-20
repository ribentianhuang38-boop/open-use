"""Unit tests for JevGate enforcement, JevContext lifecycle, and Chained Composite pipeline."""

import os
import unittest
from unittest.mock import MagicMock, patch

from open_use.agent import OpenAgent
from open_use.core.jev_gate import (
    JevContext,
    JevEnforcementError,
    require_jev_token,
)
from open_use.desktop.agent import DesktopAgent
from open_use.desktop.hal import LinuxPlatform, UIElement


class TestJevGateEnforcement(unittest.TestCase):
    """Verify that unmediated hardware actions are strictly intercepted by JevGate."""

    def setUp(self):
        # Clear any ambient bypass
        os.environ.pop("OPENUSE_ALLOW_RAW_HAL", None)

    def test_direct_platform_click_raises_enforcement_error(self):
        """Direct call to platform.click outside JevContext MUST raise JevEnforcementError."""
        lp = LinuxPlatform()
        with self.assertRaises(JevEnforcementError) as ctx:
            lp.click(100, 200)
        self.assertIn("JevGate VIOLATION", str(ctx.exception))
        self.assertIn("bypassed Jev System One", str(ctx.exception))

    def test_direct_platform_type_text_raises_enforcement_error(self):
        """Direct call to platform.type_text outside JevContext MUST raise JevEnforcementError."""
        lp = LinuxPlatform()
        with self.assertRaises(JevEnforcementError):
            lp.type_text("forbidden_text")

    def test_direct_platform_hotkey_raises_enforcement_error(self):
        """Direct call to platform.hotkey outside JevContext MUST raise JevEnforcementError."""
        lp = LinuxPlatform()
        with self.assertRaises(JevEnforcementError):
            lp.hotkey(["ctrl", "v"])

    def test_call_within_jev_session_succeeds_and_records_telemetry(self):
        """Hardware actions within with JevContext.session() execute and record telemetry."""
        lp = LinuxPlatform()
        with patch("subprocess.run") as mock_run:
            with JevContext.session(step=1, decision_token="btn_42") as sess:
                lp.click(150, 250)
                lp.type_text("authorized_input")

                self.assertEqual(len(sess.executed_actions), 2)
                self.assertEqual(sess.executed_actions[0]["action"], "click")
                self.assertEqual(sess.executed_actions[1]["action"], "type_text")

    def test_bypass_for_test_helper(self):
        """JevContext.bypass_for_test allows unit tests to mock without live Jev server."""
        lp = LinuxPlatform()
        with patch("subprocess.run"):
            with JevContext.bypass_for_test():
                # Should not raise
                lp.click(50, 50)
                lp.scroll(50, 50, 3)

    def test_desktop_agent_actions_run_inside_jev_session(self):
        """DesktopAgent.step() MUST execute native hardware actions inside an authorized Jev session."""
        from open_use.core.dual_core import CapabilityAssessment, BranchHealth

        mock_platform = MagicMock(spec=LinuxPlatform)
        mock_platform.capture_screen.return_value = "/tmp/fake.png"
        mock_platform.detect_ui_elements.return_value = [
            UIElement(id="1", label="Submit", category="button", bbox=[10, 10, 50, 50], center=[30, 30])
        ]

        agent = DesktopAgent(goal="Click Submit", platform=mock_platform, dry_run=False)

        # Mock JevClient decision and orchestrator checks
        with patch.object(agent.orchestrator, "assess_jev_capacity", return_value=CapabilityAssessment(can_handle=True, reason="normal", confidence=0.95)), \
             patch.object(agent.orchestrator, "check_branch_health", return_value=BranchHealth(on_track=True, drift_type="none", confidence=1.0, recommended_rollback="none")), \
             patch.object(agent.client, "query_systemone") as mock_query:
            mock_resp = MagicMock()
            mock_choice = MagicMock()
            mock_choice.choice = "btn_1"
            mock_resp.get_choice.return_value = mock_choice
            mock_resp.latency_ms = 45
            mock_query.return_value = mock_resp

            # Track if Jev session is active when mock_platform.click is called
            session_active_during_click = []

            def click_hook(x, y):
                session_active_during_click.append(JevContext.is_active_jev_session())

            mock_platform.click.side_effect = click_hook

            res = agent.step()
            self.assertTrue(mock_platform.click.called)
            self.assertTrue(session_active_during_click)
            self.assertTrue(session_active_during_click[0], "Click must be executed inside active JevContext!")

    def test_composite_goal_decomposition(self):
        """OpenAgent._decompose_goal correctly splits compound goals by conjunctions."""
        agent = OpenAgent()
        goal = "在YouTube搜索木工视频然后给视频点赞随后发给QQ 3496306656"
        subgoals = agent._decompose_goal(goal)
        self.assertEqual(len(subgoals), 3)
        self.assertEqual(subgoals[0], "在YouTube搜索木工视频")
        self.assertEqual(subgoals[1], "给视频点赞")
        self.assertEqual(subgoals[2], "发给QQ 3496306656")

    def test_composite_pipeline_dry_run_telemetry(self):
        """OpenAgent.run_composite produces execution certificate and telemetry."""
        agent = OpenAgent()
        goals = ["在YouTube搜索木工", "发给QQ 3496306656"]
        with patch.object(agent, "run_browser", return_value={"status": "dry_run", "jev_steps": 2}), \
             patch.object(agent, "run_desktop", return_value=[MagicMock(action_type="click"), MagicMock(action_type="click")]):
            result = agent.run_composite(goals=goals, dry_run=True)

            self.assertEqual(result["status"], "completed")
            self.assertEqual(len(result["stages"]), 2)
            self.assertEqual(result["total_jev_steps"], 4)
            self.assertEqual(result["total_llm_steps"], 0)
            self.assertEqual(result["jev_ratio"], 1.0)


if __name__ == "__main__":
    unittest.main()
