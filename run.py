#!/usr/bin/env python3
"""Unified CLI runner for OpenUse (Desktop & Browser Automation)."""

import argparse
import sys
from typing import Optional

from open_use.agent import OpenAgent


def main():
    parser = argparse.ArgumentParser(description="OpenUse: Dual-Core OS & Web Autonomous Agent")
    parser.add_argument("--mcp", action="store_true", help="Start as a Model Context Protocol (MCP) stdio server")
    parser.add_argument("--goal", type=str, default="", help="Task objective in natural language")
    parser.add_argument("--url", type=str, default="", help="Starting URL if executing a web task")
    parser.add_argument("--mode", type=str, choices=["auto", "desktop", "browser"], default="auto", help="Execution mode")
    parser.add_argument("--max-steps", type=int, default=20, help="Maximum step limit")

    args = parser.parse_args()

    # Launch MCP Server mode
    if args.mcp:
        from open_use.mcp_server import main as mcp_main
        mcp_main()
        return

    if not args.goal:
        parser.print_help()
        sys.exit(1)

    agent = OpenAgent()
    agent.run(goal=args.goal, mode=args.mode, url=args.url if args.url else None)


if __name__ == "__main__":
    main()
