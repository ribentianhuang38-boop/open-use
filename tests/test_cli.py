import argparse
import unittest
from unittest.mock import MagicMock, patch

from open_use.cli import main


class TestCLI(unittest.TestCase):
    """Test CLI argument parsing and dispatching."""

    @patch("open_use.cli.OpenAgent")
    def test_cli_dispatch_with_max_steps(self, mock_agent_class):
        mock_agent_instance = MagicMock()
        mock_agent_class.return_value = mock_agent_instance

        test_args = ["openuse", "--goal", "Find file", "--mode", "desktop", "--max-steps", "42"]
        with patch("sys.argv", test_args):
            main()

        mock_agent_instance.run.assert_called_once_with(
            goal="Find file",
            mode="desktop",
            url=None,
            max_steps=42,
        )

    @patch("open_use.mcp_server.main")
    def test_cli_mcp_flag(self, mock_mcp_main):
        test_args = ["openuse", "--mcp"]
        with patch("sys.argv", test_args):
            main()

        mock_mcp_main.assert_called_once()

    @patch("open_use.cli.OpenAgent")
    def test_cli_dry_run_flag(self, mock_agent_class):
        mock_agent_instance = MagicMock()
        mock_agent_class.return_value = mock_agent_instance

        test_args = ["openuse", "--goal", "Preview something", "--dry-run"]
        with patch("sys.argv", test_args):
            main()

        mock_agent_instance.run.assert_called_once_with(
            goal="Preview something",
            mode="auto",
            url=None,
            max_steps=20,
            dry_run=True,
        )

    def test_cli_invalid_max_steps(self):
        test_args = ["openuse", "--goal", "Test", "--max-steps", "150"]
        with patch("sys.argv", test_args):
            with self.assertRaises(SystemExit) as cm:
                main()
            self.assertEqual(cm.exception.code, 1)

    def test_cli_ssrf_url_blocked(self):
        test_args = ["openuse", "--goal", "Test", "--url", "http://169.254.169.254/secret"]
        with patch("sys.argv", test_args):
            with self.assertRaises(SystemExit) as cm:
                main()
            self.assertEqual(cm.exception.code, 1)


if __name__ == "__main__":
    unittest.main()
