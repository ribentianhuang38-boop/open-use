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
        from open_use.core.jev_gate import JevContext
        lp = LinuxPlatform()
        # capture_screen should return a valid file path
        shot = lp.capture_screen()
        self.assertTrue(os.path.exists(shot))
        lp.cleanup_screenshot(shot)

        # UI element detection returns list
        elements = lp.detect_ui_elements(shot)
        self.assertIsInstance(elements, list)

        # Mocked execution methods should not throw unhandled exceptions under Jev session
        with patch("subprocess.run") as mock_run:
            with JevContext.bypass_for_test():
                lp.click(100, 200)
                mock_run.assert_called_with(["xdotool", "mousemove", "100", "200", "click", "1"], timeout=5.0, check=False)

                lp.type_text("hello")
                mock_run.assert_called_with(["xdotool", "type", "--", "hello"], timeout=5.0, check=False)

                lp.press_key("return")
                mock_run.assert_called_with(["xdotool", "key", "return"], timeout=5.0, check=False)

                lp.hotkey(["ctrl", "c"])
                mock_run.assert_called_with(["xdotool", "key", "ctrl+c"], timeout=5.0, check=False)

    def test_win_platform_mocked(self):
        """Test Windows platform scale attribute and SendInput logic via mocks (I-01, M-04)."""
        import ctypes
        from open_use.desktop.platform_win import WinPlatform
        from open_use.core.jev_gate import JevContext
        wp = WinPlatform()
        self.assertEqual(wp.scale, 1.0)

        mock_user32 = MagicMock()
        with patch("sys.platform", "win32"):
            with patch.object(ctypes, "windll", create=True) as mock_windll:
                mock_windll.user32 = mock_user32
                with patch.object(wp, "_get_screen_dimensions", return_value=(1920, 1080)):
                    with JevContext.bypass_for_test():
                        wp.click(100, 200)
                        self.assertTrue(mock_user32.SendInput.called)

                        wp.scroll(100, 200, 3)
                        self.assertTrue(mock_user32.SendInput.called)


if __name__ == "__main__":
    unittest.main()
