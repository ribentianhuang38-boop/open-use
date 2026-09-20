#!/usr/bin/env python3
"""Unified CLI runner for OmniUse (Desktop & Browser Automation)."""

import argparse
import sys

from omni_use.agent import OmniAgent


def main():
    parser = argparse.ArgumentParser(description="OmniUse: Dual-Core OS & Web Autonomous Agent")
    parser.add_argument("--mcp", action="store_true", help="Start as a Model Context Protocol (MCP) stdio server")
    parser.add_argument("--goal", type=str, default=None, help="Task objective in natural language")
    parser.add_argument("--url", type=str, default=None, help="Starting URL if executing a web task")
    parser.add_argument("--mode", choices=["auto", "desktop", "browser"], default="auto", help="Execution mode")
    parser.add_argument("--max-steps", type=int, default=15, help="Maximum step limit")

    args = parser.parse_args()

    if args.mcp:
        from omni_use.mcp_server import main as mcp_main
        mcp_main()
        return

    if not args.goal:
        parser.error("--goal is required when not in --mcp mode")

    agent = OmniAgent()

    if args.mode == "browser" or (args.mode == "auto" and args.url):
        if not args.url:
            print("Error: --url is required when mode is 'browser'")
            sys.exit(1)
        agent.run_browser(url=args.url, goal=args.goal, max_steps=args.max_steps)
    elif args.mode == "desktop":
        agent.run_desktop(goal=args.goal, max_steps=args.max_steps)
    else:
        agent.run(goal=args.goal)


if __name__ == "__main__":
    main()
