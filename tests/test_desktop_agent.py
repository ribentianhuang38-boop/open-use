import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from open_use.desktop.agent import DesktopAgent, DesktopStepResult
from open_use.desktop.hal import DesktopPlatform, UIElement


class MockDesktopPlatform(DesktopPlatform):
    """Mock platform for deterministic desktop agent testing."""

    def __init__(self):
        self.clicked_points = []
        self.typed_texts = []
        self.pressed_keys = []
        self.hotkeys = []
        self.screenshots_captured = []
        self.screenshots_cleaned = []

    def capture_screen(self, output_path=None) -> str:
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.write(b"dummy_png_bytes")
            path = f.name
        self.screenshots_captured.append(path)
        return path

    def cleanup_screenshot(self, file_path) -> None:
        if file_path and os.path.exists(file_path):
            os.unlink(file_path)
            self.screenshots_cleaned.append(file_path)

    def detect_ui_elements(self, image_path: str, scale: float = 1.0):
        return [
            UIElement(id="1", label="Search or enter web address", category="input", bbox=[10, 10, 200, 40], center=[105, 25]),
            UIElement(id="2", label="发送", category="button", bbox=[210, 10, 280, 40], center=[245, 25]),
            UIElement(id="3", label="Close Window", category="button", bbox=[290, 10, 350, 40], center=[320, 25]),
        ]

    def click(self, x: int, y: int) -> None:
        self.clicked_points.append((x, y))

    def double_click(self, x: int, y: int) -> None:
        pass

    def right_click(self, x: int, y: int) -> None:
        pass

    def type_text(self, text: str) -> None:
        self.typed_texts.append(text)

    def press_key(self, key_name: str) -> None:
        self.pressed_keys.append(key_name)

    def hotkey(self, keys) -> None:
        self.hotkeys.append(keys)

    def copy_file_to_clipboard(self, file_path: str) -> None:
        pass

    def scroll(self, x: int, y: int, delta: int) -> None:
        pass

    def activate_app(self, app_name: str) -> None:
        pass


class TestDesktopAgent(unittest.TestCase):
    """Test DesktopAgent execution lifecycle and fixes."""

    def test_completion_keywords_presence(self):
        # Defect 18 check: COMPLETION_KEYWORDS exists and is used
        self.assertTrue(hasattr(DesktopAgent, "COMPLETION_KEYWORDS"))
        self.assertIn("已发送", DesktopAgent.COMPLETION_KEYWORDS)
        self.assertIn("Success", DesktopAgent.COMPLETION_KEYWORDS)

    def test_agent_step_and_screenshot_cleanup(self):
        # Defect 17 check: screenshots must be cleaned up after detection
        platform = MockDesktopPlatform()
        agent = DesktopAgent(goal="Click 'Search or enter web address'", platform=platform, max_steps=2, click_delay=0.0)

        step_res = agent.step()
        self.assertIsInstance(step_res, DesktopStepResult)
        self.assertEqual(step_res.step, 1)

        # Verify that all captured screenshots were cleaned up
        self.assertGreater(len(platform.screenshots_captured), 0)
        self.assertEqual(len(platform.screenshots_captured), len(platform.screenshots_cleaned))
        for p in platform.screenshots_captured:
            self.assertFalse(os.path.exists(p))

    def test_type_text_extraction(self):
        # Defect 14 check: type_text extracts text from goal
        platform = MockDesktopPlatform()
        agent = DesktopAgent(goal='Type "HelloWorld" into the search box', platform=platform, click_delay=0.0)

        with patch.object(agent, "_batched_decision_and_safety") as mock_decision:
            mock_choice = MagicMock()
            mock_choice.choice = "type_text"
            mock_decision.return_value = {"decision": mock_choice, "safety": None}

            res = agent.step()
            self.assertEqual(res.action_type, "type_text")
            self.assertIn("HelloWorld", platform.typed_texts)


if __name__ == "__main__":
    unittest.main()
