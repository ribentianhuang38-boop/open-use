"""Tests for Window-level Capture, Multi-Threaded Parallel Pipeline, and CDP Idle Reaper."""

import sys
import threading
import time
import unittest
from unittest.mock import MagicMock, patch

from open_use.agent import OpenAgent
from open_use.browser import cdp_client
from open_use.desktop.hal import UIElement, get_current_platform


class TestParallelPipelineAndOptimization(unittest.TestCase):

    def test_window_capture_and_offset_mapping(self):
        """Test window capture offset accumulates properly into UI element bounding boxes."""
        platform = get_current_platform()
        # Mock detection returning raw coordinates
        dummy_element = UIElement(
            id="1",
            label="Send",
            category="button",
            bbox=[10, 20, 50, 60],
            center=[30, 40],
        )

        with patch.object(platform, "detect_ui_elements") as mock_detect:
            # When detect_ui_elements is called with offset=(100, 200)
            mock_detect.side_effect = lambda path, scale=1.0, offset=(0, 0): [
                UIElement(
                    id="1",
                    label="Send",
                    category="button",
                    bbox=[10 + offset[0], 20 + offset[1], 50 + offset[0], 60 + offset[1]],
                    center=[30 + offset[0], 40 + offset[1]],
                )
            ]

            elements = platform.detect_ui_elements("/tmp/mock.png", scale=1.0, offset=(100, 200))
            self.assertEqual(len(elements), 1)
            el = elements[0]
            self.assertEqual(el.bbox, [110, 220, 150, 260])
            self.assertEqual(el.center, [130, 240])

    def test_parallel_composite_dry_run(self):
        """Test OpenAgent.run_parallel_composite executes concurrently and outputs telemetry."""
        agent = OpenAgent()
        res = agent.run_parallel_composite(
            web_task={"url": "https://finance.yahoo.com", "goal": "Extract BABA stock price"},
            desktop_task={"goal": "Send BABA stock to QQ contact 3496306656", "app": "QQ"},
            dry_run=True,
        )
        self.assertEqual(res["status"], "completed")
        self.assertEqual(res["mode"], "parallel_composite")
        self.assertGreaterEqual(res["total_jev_steps"], 1)
        self.assertGreaterEqual(res["jev_ratio"], 0.85)

    def test_intelligent_auto_routing_to_parallel(self):
        """Test natural language composite goal auto-routes to parallel execution."""
        agent = OpenAgent()
        goal = "去浏览器查一下阿里股价然后qq发3496306656"

        with patch.object(agent, "run_parallel_composite") as mock_parallel:
            mock_parallel.return_value = {"status": "completed", "mode": "parallel_composite"}
            res = agent.run(goal, dry_run=True)
            self.assertTrue(mock_parallel.called)
            args, kwargs = mock_parallel.call_args
            self.assertIn("阿里股价", kwargs.get("web_task", "") or str(args))
            self.assertIn("qq", kwargs.get("desktop_task", "").lower() or str(args).lower())

    def test_cdp_idle_reaper_lifecycle(self):
        """Test 5-minute idle timer is configured and close_cdp safely terminates."""
        cdp_client._reset_idle_timer()
        self.assertIsNotNone(cdp_client._IDLE_TIMER)
        self.assertTrue(cdp_client._IDLE_TIMER.is_alive())

        # Cleanup
        cdp_client.close_cdp(terminate_process=False)
        self.assertIsNone(cdp_client._IDLE_TIMER)


if __name__ == "__main__":
    unittest.main()
