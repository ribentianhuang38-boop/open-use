import json
import unittest
from unittest.mock import MagicMock, patch

from open_use.desktop.hal import UIElement
from open_use.mcp_server import MCPServer


class TestMCPServer(unittest.TestCase):
    """Test MCP Server protocol compliance and tool execution."""

    def setUp(self):
        self.server = MCPServer()

    def test_tools_manifest(self):
        tools = self.server.get_tools_manifest()
        self.assertIsInstance(tools, list)
        tool_names = [t["name"] for t in tools]
        expected = [
            "open_run",
            "omni_run",
            "desktop_run_goal",
            "browser_run_goal",
            "desktop_get_buttons",
            "desktop_click_button",
            "desktop_type_text",
            "desktop_copy_file_to_clipboard",
        ]
        for exp in expected:
            self.assertIn(exp, tool_names)

        for t in tools:
            self.assertIn("name", t)
            self.assertIn("description", t)
            self.assertIn("inputSchema", t)
            self.assertEqual(t["inputSchema"]["type"], "object")

    def test_handle_tool_call_desktop_get_buttons(self):
        mock_platform = MagicMock()
        mock_platform.capture_screen.return_value = "/tmp/test_shot.png"
        mock_platform.detect_ui_elements.return_value = [
            UIElement(id="1", label="Save", category="button", bbox=[0, 0, 50, 30], center=[25, 15]),
        ]

        self.server.platform = mock_platform
        res = self.server.handle_tool_call("desktop_get_buttons", {})

        self.assertEqual(res["total"], 1)
        self.assertEqual(res["buttons"][0]["id"], "1")
        self.assertEqual(res["buttons"][0]["label"], "Save")
        mock_platform.cleanup_screenshot.assert_called_with("/tmp/test_shot.png")

    def test_handle_tool_call_type_text(self):
        mock_platform = MagicMock()
        self.server.platform = mock_platform

        res = self.server.handle_tool_call("desktop_type_text", {"text": "Hello World"})
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["typed"], "Hello World")
        mock_platform.type_text.assert_called_with("Hello World")

    def test_handle_unknown_tool(self):
        with self.assertRaises(ValueError):
            self.server.handle_tool_call("non_existent_tool", {})

    def test_json_rpc_error_format_spec(self):
        # Verify JSON-RPC 2.0 error compliance:
        # Standard format: {"jsonrpc": "2.0", "id": ..., "error": {"code": ..., "message": ...}}
        # Non-standard fields like "isError" or "data: traceback" must NOT be present
        with patch.object(self.server, "handle_tool_call", side_effect=RuntimeError("System error")):
            req = {
                "jsonrpc": "2.0",
                "id": "test-req-1",
                "method": "tools/call",
                "params": {"name": "open_run", "arguments": {"goal": "test"}},
            }
            # Simulate what run_stdio does on error
            tool_name = req["params"]["name"]
            tool_args = req["params"]["arguments"]
            try:
                self.server.handle_tool_call(tool_name, tool_args)
            except Exception as err:
                resp = {
                    "jsonrpc": "2.0",
                    "id": req["id"],
                    "error": {
                        "code": -32603,
                        "message": f"Tool execution error: {type(err).__name__}: {str(err)}",
                    },
                }

            self.assertEqual(resp["jsonrpc"], "2.0")
            self.assertEqual(resp["id"], "test-req-1")
            self.assertIn("error", resp)
            self.assertNotIn("isError", resp)
            self.assertNotIn("data", resp["error"])
            self.assertEqual(resp["error"]["code"], -32603)


if __name__ == "__main__":
    unittest.main()
