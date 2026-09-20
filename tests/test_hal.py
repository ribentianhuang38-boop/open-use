import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from open_use.desktop.hal import (
    DesktopPlatform,
    LinuxPlatform,
    UIElement,
    get_current_platform,
)


class TestHAL(unittest.TestCase):
    """Test Hardware Abstraction Layer across platforms."""

    def test_ui_element_dataclass(self):
        el = UIElement(
            id="1",
            label="Submit",
            category="button",
            bbox=[10, 20, 110, 60],
            center=[60, 40],
            badge_text="OK",
        )
        self.assertEqual(el.id, "1")
        self.assertEqual(el.label, "Submit")
        self.assertEqual(el.category, "button")
        self.assertEqual(el.bbox, [10, 20, 110, 60])
        self.assertEqual(el.center, [60, 40])
        self.assertEqual(el.badge_text, "OK")

    def test_cleanup_screenshot(self):
        platform = LinuxPlatform()
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            temp_path = f.name
        self.assertTrue(os.path.exists(temp_path))
        platform.cleanup_screenshot(temp_path)
        self.assertFalse(os.path.exists(temp_path))

        # Calling on non-existent path should not raise
        platform.cleanup_screenshot("/non/existent/path_12345.png")

    def test_get_current_platform(self):
        platform = get_current_platform()
        self.assertIsInstance(platform, DesktopPlatform)
        if sys.platform == "darwin":
            from open_use.desktop.platform_mac import MacPlatform
            self.assertIsInstance(platform, MacPlatform)
        elif sys.platform == "win32":
            from open_use.desktop.platform_win import WinPlatform
            self.assertIsInstance(platform, WinPlatform)
        else:
            self.assertIsInstance(platform, LinuxPlatform)

    def test_linux_platform_methods(self):
        lp = LinuxPlatform()
        # capture_screen should return a valid file path
        shot = lp.capture_screen()
        self.assertTrue(os.path.exists(shot))
        lp.cleanup_screenshot(shot)

        # UI element detection returns list
        elements = lp.detect_ui_elements(shot)
        self.assertIsInstance(elements, list)

        # Mocked execution methods should not throw unhandled exceptions
        with patch("subprocess.run") as mock_run:
            lp.click(100, 200)
            mock_run.assert_called_with(["xdotool", "mousemove", "100", "200", "click", "1"], check=False)

            lp.type_text("hello")
            mock_run.assert_called_with(["xdotool", "type", "--", "hello"], check=False)

            lp.press_key("Return")
            mock_run.assert_called_with(["xdotool", "key", "Return"], check=False)

            lp.hotkey(["ctrl", "c"])
            mock_run.assert_called_with(["xdotool", "key", "ctrl+c"], check=False)


if __name__ == "__main__":
    unittest.main()
