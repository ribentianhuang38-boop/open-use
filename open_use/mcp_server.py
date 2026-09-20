"""Model Context Protocol (MCP) Server for OpenUse.

Exposes dual-core Desktop and Browser automation tools via standard JSON-RPC 2.0 stdio.
Compatible with Claude Desktop, Cursor, Windsurf, Zed, and Antigravity.
"""

from __future__ import annotations

import json
import os
import sys
import traceback
from typing import Any, Dict, List, Optional

from .agent import OpenAgent, OmniAgent
from .desktop.hal import get_current_platform


class MCPServer:
    """Standard MCP stdio server implementation (JSON-RPC 2.0)."""

    def __init__(self):
        self.agent = OpenAgent()
        self.platform = get_current_platform()

    def get_tools_manifest(self) -> List[Dict[str, Any]]:
        """Return schema for all exposed tools."""
        return [
            {
                "name": "open_run",
                "description": "Execute a high-level dual-core autonomous task, automatically coordinating between Desktop apps and Browser.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "goal": {
                            "type": "string",
                            "description": "Natural language task goal, e.g., 'https://example.com download report and send via QQ'",
                        },
                    },
                    "required": ["goal"],
                },
            },
            {
                "name": "omni_run",
                "description": "Alias for open_run (backwards compatibility).",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "goal": {
                            "type": "string",
                            "description": "Natural language task goal",
                        },
                    },
                    "required": ["goal"],
                },
            },
            {
                "name": "desktop_run_goal",
                "description": "Execute an autonomous multi-step native desktop task (WeChat, QQ, Office, Finder, System Settings) via local fast vision + Jev.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "goal": {
                            "type": "string",
                            "description": "Desktop task goal, e.g., 'Click contact 镇宅前列腺 and send screenshot'",
                        },
                        "max_steps": {
                            "type": "integer",
                            "description": "Maximum number of steps (default: 15)",
                            "default": 15,
                        },
                    },
                    "required": ["goal"],
                },
            },
            {
                "name": "browser_run_goal",
                "description": "Execute an autonomous deep web task (forms, scraping, downloading files) via CDP + Jev without screenshot tokens.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "url": {
                            "type": "string",
                            "description": "Target webpage URL",
                        },
                        "goal": {
                            "type": "string",
                            "description": "Objective on the webpage",
                        },
                        "max_steps": {
                            "type": "integer",
                            "description": "Maximum step limit (default: 25)",
                            "default": 25,
                        },
                    },
                    "required": ["url", "goal"],
                },
            },
            {
                "name": "desktop_get_buttons",
                "description": "Inspect current desktop screen and return structured numbered buttons [1], [2], [3] with coordinates and labels.",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                },
            },
            {
                "name": "desktop_click_button",
                "description": "Click a specific numbered button or UI control by its ID from desktop_get_buttons.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "button_id": {
                            "type": "string",
                            "description": "The button ID to click, e.g., '1' or '10'",
                        },
                    },
                    "required": ["button_id"],
                },
            },
            {
                "name": "desktop_type_text",
                "description": "Type text natively into the currently focused desktop input field.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "text": {
                            "type": "string",
                            "description": "Unicode text string to type",
                        },
                    },
                    "required": ["text"],
                },
            },
            {
                "name": "desktop_copy_file_to_clipboard",
                "description": "Mount a local file path to the OS clipboard so it can be pasted into chat apps or folders via Ctrl+V / Cmd+V.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "file_path": {
                            "type": "string",
                            "description": "Absolute or relative path to the local file",
                        },
                    },
                    "required": ["file_path"],
                },
            },
        ]

    def handle_tool_call(self, name: str, args: Dict[str, Any]) -> Any:
        """Dispatch tool calls to corresponding engine."""
        if name in ("open_run", "omni_run"):
            res = self.agent.run(goal=args["goal"])
            return {"status": "success", "result": str(res)}

        elif name == "desktop_run_goal":
            max_steps = args.get("max_steps", 15)
            res = self.agent.run_desktop(goal=args["goal"], max_steps=max_steps)
            return {"status": "success", "steps_executed": len(res), "completed": any(r.is_goal_satisfied for r in res)}

        elif name == "browser_run_goal":
            url = args["url"]
            goal = args["goal"]
            max_steps = args.get("max_steps", 25)
            res = self.agent.run_browser(url=url, goal=goal, max_steps=max_steps)
            return {"status": "success", "browser_result": res}

        elif name == "desktop_get_buttons":
            shot = self.platform.capture_screen()
            scale = 1.0 if sys.platform == "win32" else 2.0
            elements = self.platform.detect_ui_elements(shot, scale=scale)
            return {
                "total": len(elements),
                "buttons": [
                    {"id": el.id, "label": el.label, "category": el.category, "center": el.center}
                    for el in elements[:60]
                ],
            }

        elif name == "desktop_click_button":
            btn_id = str(args["button_id"]).replace("btn_", "").strip()
            shot = self.platform.capture_screen()
            scale = 1.0 if sys.platform == "win32" else 2.0
            elements = self.platform.detect_ui_elements(shot, scale=scale)
            target = next((e for e in elements if e.id == btn_id), None)
            if not target:
                return {"status": "error", "message": f"Button with ID {btn_id} not found"}
            self.platform.click(target.center[0], target.center[1])
            return {"status": "success", "clicked": target.label, "point": target.center}

        elif name == "desktop_type_text":
            self.platform.type_text(args["text"])
            return {"status": "success", "typed": args["text"]}

        elif name == "desktop_copy_file_to_clipboard":
            self.platform.copy_file_to_clipboard(args["file_path"])
            return {"status": "success", "mounted_file": args["file_path"]}

        else:
            raise ValueError(f"Unknown tool: {name}")

    def run_stdio(self) -> None:
        """Run standard MCP JSON-RPC stdio event loop."""
        sys.stderr.write("OpenUse MCP Server started (stdio mode)\n")
        sys.stderr.flush()

        while True:
            line = sys.stdin.readline()
            if not line:
                break
            line = line.strip()
            if not line:
                continue

            try:
                req = json.loads(line)
            except Exception:
                continue

            req_id = req.get("id")
            method = req.get("method")
            params = req.get("params", {})

            # MCP Protocol Handlers
            if method == "initialize":
                resp = {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {
                            "tools": {},
                        },
                        "serverInfo": {
                            "name": "open-use",
                            "version": "0.1.0",
                        },
                    },
                }
            elif method == "notifications/initialized":
                continue
            elif method == "tools/list":
                resp = {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "tools": self.get_tools_manifest(),
                    },
                }
            elif method == "tools/call":
                tool_name = params.get("name")
                tool_args = params.get("arguments", {})
                try:
                    out = self.handle_tool_call(tool_name, tool_args)
                    resp = {
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "result": {
                            "content": [
                                {
                                    "type": "text",
                                    "text": json.dumps(out, ensure_ascii=False, indent=2),
                                }
                            ],
                        },
                    }
                except Exception as err:
                    resp = {
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "isError": True,
                        "error": {
                            "code": -32603,
                            "message": str(err),
                            "data": traceback.format_exc(),
                        },
                    }
            elif method == "ping":
                resp = {"jsonrpc": "2.0", "id": req_id, "result": {}}
            else:
                resp = {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32601, "message": f"Method not found: {method}"},
                }

            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()


def main():
    server = MCPServer()
    server.run_stdio()


if __name__ == "__main__":
    main()
