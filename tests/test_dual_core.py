import unittest
from unittest.mock import MagicMock

from open_use.core.dual_core import (
    BranchHealth,
    CapabilityAssessment,
    ControllerMode,
    DualCoreOrchestrator,
    ReclaimVerdict,
)
from open_use.desktop.hal import LinuxPlatform


class TestDualCoreOrchestrator(unittest.TestCase):
    """Test DualCoreOrchestrator handover, loop detection, and rollback."""

    def setUp(self):
        self.orchestrator = DualCoreOrchestrator()

    def test_loop_detection_repeated_targets(self):
        self.orchestrator.record_step("click", "btn_1")
        self.orchestrator.record_step("click", "btn_1")
        self.orchestrator.record_step("click", "btn_1")

        is_stuck, reason = self.orchestrator.is_stuck_in_loop()
        self.assertTrue(is_stuck)
        self.assertIn("Repeatedly targeted", reason)

        # Capacity assessment should automatically flag loop and decline handling
        assessment = self.orchestrator.assess_jev_capacity(
            screen_summary="some text",
            goal="send message",
            available_elements_count=5,
        )
        self.assertFalse(assessment.can_handle)
        self.assertIn("loop_detected", assessment.reason)

    def test_zero_elements_escalation(self):
        fresh_orch = DualCoreOrchestrator()
        assessment = fresh_orch.assess_jev_capacity(
            screen_summary="",
            goal="do something",
            available_elements_count=0,
        )
        self.assertFalse(assessment.can_handle)
        self.assertEqual(assessment.reason, "zero_elements_visible")

    def test_normal_capacity_assessment(self):
        fresh_orch = DualCoreOrchestrator()
        assessment = fresh_orch.assess_jev_capacity(
            screen_summary="Settings General Network Display",
            goal="Click General",
            available_elements_count=10,
        )
        self.assertTrue(assessment.can_handle)

    def test_branch_health_normal(self):
        health = self.orchestrator.check_branch_health(
            current_ui_summary="Profile settings and account info",
            goal="Edit profile",
            last_action="click",
        )
        self.assertIsInstance(health, BranchHealth)
        self.assertTrue(health.on_track)
        self.assertEqual(health.recommended_rollback, "none")

    def test_rollback_execution(self):
        mock_platform = MagicMock()
        self.orchestrator.execute_rollback("esc", mock_platform)
        mock_platform.press_key.assert_called_with("escape")

        self.orchestrator.execute_rollback("back", mock_platform)
        mock_platform.hotkey.assert_called_with(["cmd", "["])


if __name__ == "__main__":
    unittest.main()
