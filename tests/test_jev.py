import os
import unittest
from unittest.mock import MagicMock, patch

from open_use.core.jev_client import ChoiceResult, JevClient, JevResponse, ScoreResult
from open_use.core.jev_judge import GoalVerdict, JevJudge, ProgressVerdict, SafetyVerdict


class TestJevClientAndJudge(unittest.TestCase):
    """Test JevClient and JevJudge components."""

    def test_env_alias_sync(self):
        with patch.dict(os.environ, {"JEV_API_KEY": "test_jev_secret_123"}, clear=True):
            from open_use.core.jev_client import _load_env_file
            _load_env_file()
            self.assertEqual(os.environ.get("TYPESAFE_API_KEY"), "test_jev_secret_123")

    def test_jev_client_local_fallback(self):
        # When no API key is provided, JevClient falls back locally
        client = JevClient(api_key=None)
        self.assertTrue(client._local_fallback)

        resp = client.query_systemone(
            state={"screen": "empty"},
            questions={
                "next_step_action": {
                    "type": "choice",
                    "criteria": {"btn_1": "Click 1", "btn_2": "Click 2"},
                },
                "confidence_score": {
                    "type": "score",
                    "criteria": ["low", "medium", "high"],
                },
            },
        )
        self.assertIsInstance(resp, JevResponse)
        choice = resp.get_choice("next_step_action")
        self.assertIsNotNone(choice)
        self.assertEqual(choice.choice, "btn_1")
        self.assertGreater(choice.confidence, 0.5)

        score = resp.get_score("confidence_score")
        self.assertIsNotNone(score)
        self.assertGreaterEqual(score.score, 0.0)

    def test_judge_goal_completion_signatures(self):
        judge = JevJudge()

        # Should support screen_state keyword
        verdict1 = judge.judge_goal_completion(
            screen_state={"active_window": "Chat", "visible_text": "已发送"},
            goal="Send message",
        )
        self.assertIsInstance(verdict1, GoalVerdict)

        # Should also support page_state keyword (compatibility for browser agent)
        verdict2 = judge.judge_goal_completion(
            page_state={"title": "Google", "text": "Search results"},
            goal="Search something",
        )
        self.assertIsInstance(verdict2, GoalVerdict)

    def test_judge_progress_method(self):
        judge = JevJudge()
        verdict = judge.judge_progress(
            prev_summary="login window",
            curr_summary="main dashboard",
            last_action={"action": "click", "target": "submit"},
        )
        self.assertIsInstance(verdict, ProgressVerdict)
        self.assertTrue(verdict.made_progress)

    def test_check_safety_method(self):
        judge = JevJudge()
        verdict = judge.check_safety(
            goal="Clean temporary folder",
            action="rm -rf /",
        )
        self.assertIsInstance(verdict, SafetyVerdict)
        self.assertIn(verdict.risk_level, {"safe", "medium_risk", "high_risk"})


if __name__ == "__main__":
    unittest.main()
