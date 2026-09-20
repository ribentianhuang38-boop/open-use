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


if __name__ == "__main__":
    unittest.main()
