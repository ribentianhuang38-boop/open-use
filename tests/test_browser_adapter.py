import unittest
from unittest.mock import MagicMock

from open_use.browser.browser_use_adapter import JevJudgeEvaluator, verify_browser_state
from open_use.core.jev_judge import GoalVerdict, JevJudge, ProgressVerdict, SafetyVerdict


class TestBrowserUseAdapter(unittest.TestCase):
    """Test browser-use adapter methods and integration with JevJudge."""

    def setUp(self):
        self.evaluator = JevJudgeEvaluator()

    def test_evaluate_task_outcome(self):
        passed, verdict = self.evaluator.evaluate_task_outcome(
            final_page_state={"title": "Dashboard", "text": "Welcome to your account"},
            task_goal="Log in to dashboard",
        )
        self.assertIsInstance(passed, bool)
        self.assertIsInstance(verdict, GoalVerdict)

    def test_evaluate_action_safety(self):
        is_safe, verdict = self.evaluator.evaluate_action_safety(
            action={"action": "click", "label": "Delete Account"},
            current_page_state={"title": "Settings"},
            task_goal="Delete user account permanently",
        )
        self.assertIsInstance(is_safe, bool)
        self.assertIsInstance(verdict, SafetyVerdict)

    def test_evaluate_step_progress(self):
        verdict = self.evaluator.evaluate_step(
            prev_page={"text": "Step 1: fill email"},
            current_page={"text": "Step 2: enter password"},
            executed_action={"action": "click", "target": "Next"},
            task_goal="Complete signup",
        )
        self.assertIsInstance(verdict, ProgressVerdict)

    def test_verify_browser_state_helper(self):
        result = verify_browser_state(
            page_text="Order confirmed #12345",
            page_title="Confirmation",
            page_url="https://shop.example.com/confirm",
            goal="Place order",
        )
        self.assertIn("success", result)
        self.assertIn("score", result)
        self.assertIn("confidence", result)
        self.assertIn("latency_ms", result)


if __name__ == "__main__":
    unittest.main()
