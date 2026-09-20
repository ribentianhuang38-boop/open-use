"""Model Context Protocol (MCP) Server for OpenUse.

Exposes dual-core Desktop and Browser automation tools via standard JSON-RPC 2.0 stdio.
Compatible with Claude Desktop, Cursor, Windsurf, Zed, and Antigravity.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import threading
import time
import traceback
from typing import Any, Dict, List, Optional

from .agent import OpenAgent, OmniAgent
from .desktop.hal import get_current_platform

try:
    from .core.security import validate_safe_file_path, validate_safe_url
except Exception:
    from open_use.core.security import validate_safe_file_path, validate_safe_url

logger = logging.getLogger("open_use.mcp_server")


class MCPServer:
    """Standard MCP stdio server implementation (JSON-RPC 2.0)."""

    def __init__(self):
        self.agent = OpenAgent()
        self.platform = get_current_platform()
        self._lock = threading.Lock()
        self._last_elements: Dict[str, Any] = {}
        self._last_shot_time: float = 0.0

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
                            "description": "Desktop task goal, e.g., 'Click contact ProjectLead and send screenshot'",
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
        """Dispatch tool calls to corresponding engine with concurrency locking and state isolation."""
        with self._lock:
            isolated_agent = OpenAgent(click_delay=self.agent.click_delay)
            try:
                if name in ("open_run", "omni_run"):
                    res = isolated_agent.run(goal=args["goal"])
                    return {"status": "success", "result": str(res)}

                elif name == "desktop_run_goal":
                    max_steps = args.get("max_steps", 15)
                    res = isolated_agent.run_desktop(goal=args["goal"], max_steps=max_steps)
                    last_step = res[-1] if res else None
                    needs_llm = (last_step.action_type == "escalate_to_llm") if last_step else False
                    return {
                        "status": "escalated_to_llm" if needs_llm else "success",
                        "completed": any(r.is_goal_satisfied for r in res),
                        "steps_executed": len(res),
                        "needs_llm_intervention": needs_llm,
                        "escalation_reason": last_step.target_label if needs_llm else "",
                        "next_hint": (
                            "Execute one strategic step (e.g. desktop_click_button or desktop_type_text) to break the impasse. "
                            "Jev will automatically sniff if it can reclaim control on subsequent cycles."
                            if needs_llm else "Task proceeded normally."
                        ),
                    }

                elif name == "browser_run_goal":
                    safe_url = validate_safe_url(args["url"])
                    goal = args["goal"]
                    max_steps = args.get("max_steps", 25)
                    res = isolated_agent.run_browser(url=safe_url, goal=goal, max_steps=max_steps)
                    return {"status": "success", "browser_result": res}

                elif name == "desktop_get_buttons":
                    shot = self.platform.capture_screen()
                    try:
                        scale = 1.0 if sys.platform == "win32" else 2.0
                        elements = self.platform.detect_ui_elements(shot, scale=scale)
                        self._last_elements = {el.id: el for el in elements}
                        self._last_shot_time = time.time()
                        return {
                            "total": len(elements),
                            "buttons": [
                                {"id": el.id, "label": el.label, "category": el.category, "center": el.center}
                                for el in elements[:60]
                            ],
                        }
                    finally:
                        self.platform.cleanup_screenshot(shot)

                elif name == "desktop_click_button":
                    btn_id = str(args["button_id"]).replace("btn_", "").strip()
                    # 1. Check recent cache (within 15 seconds) to prevent TOCTOU re-detection drift
                    target = None
                    if (time.time() - self._last_shot_time < 15.0) and (btn_id in self._last_elements):
                        target = self._last_elements[btn_id]

                    # 2. If not found in cache, fallback to fresh capture
                    if not target:
                        shot = self.platform.capture_screen()
                        try:
                            scale = 1.0 if sys.platform == "win32" else 2.0
                            elements = self.platform.detect_ui_elements(shot, scale=scale)
                            self._last_elements = {el.id: el for el in elements}
                            self._last_shot_time = time.time()
                            target = next((e for e in elements if e.id == btn_id), None)
                        finally:
                            self.platform.cleanup_screenshot(shot)

                    if not target:
                        return {"status": "error", "message": f"Button with ID {btn_id} not found"}
                    self.platform.click(target.center[0], target.center[1])
                    return {"status": "success", "clicked": target.label, "point": target.center}

                elif name == "desktop_type_text":
                    self.platform.type_text(args["text"])
                    return {"status": "success", "typed": args["text"]}

                elif name == "desktop_copy_file_to_clipboard":
                    safe_path = validate_safe_file_path(args["file_path"])
                    self.platform.copy_file_to_clipboard(str(safe_path))
                    return {"status": "success", "mounted_file": str(safe_path)}

                else:
                    raise ValueError(f"Unknown tool: {name}")
            finally:
                isolated_agent.close()

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
            except json.JSONDecodeError as jde:
                logger.warning(f"Failed to parse incoming JSON-RPC line: {jde}")
                resp = {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {
                        "code": -32700,
                        "message": f"Parse error: {str(jde)}",
                    },
                }
                sys.stdout.write(json.dumps(resp) + "\n")
                sys.stdout.flush()
                continue

            req_id = req.get("id")
            method = req.get("method")
            params = req.get("params", {})

            # JSON-RPC 2.0: A Notification is a Request object without an 'id' member.
            # The Server MUST NOT reply to a Notification.
            if ("id" not in req) or (req_id is None):
                continue

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
                    err_msg = str(err)
                    if isinstance(err, PermissionError):
                        err_msg = f"Security Sandbox Violation: {err}"
                    elif isinstance(err, FileNotFoundError):
                        err_msg = "File access error: Target does not exist or cannot be accessed safely."
                    resp = {
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "error": {
                            "code": -32603,
                            "message": f"Tool execution error: {type(err).__name__}: {err_msg}",
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
