#!/usr/bin/env python3
"""Unified CLI entrypoint for OpenUse (Desktop & Browser Automation)."""

import argparse
import sys
from typing import Optional

from open_use.agent import OpenAgent


def main():
    parser = argparse.ArgumentParser(
        prog="openuse",
        description="OpenUse: Dual-Core OS & Web Autonomous Agent (MCP Server & CLI)",
    )
    parser.add_argument(
        "--mcp",
        action="store_true",
        help="Start as a Model Context Protocol (MCP) stdio server",
    )
    parser.add_argument(
        "--goal",
        type=str,
        default="",
        help="Task objective in natural language",
    )
    parser.add_argument(
        "--url",
        type=str,
        default="",
        help="Starting URL if executing a web task",
    )
    parser.add_argument(
        "--mode",
        type=str,
        choices=["auto", "desktop", "browser"],
        default="auto",
        help="Execution mode (default: auto)",
    )
    parser.add_argument(
        "--max-steps",
        type=int,
        default=20,
        help="Maximum step limit between 1 and 100 (default: 20)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulate execution without modifying system state or executing native actions",
    )

    args = parser.parse_args()

    # Launch MCP Server mode
    if args.mcp:
        from open_use.mcp_server import main as mcp_main
        mcp_main()
        return

    if not args.goal:
        parser.print_help()
        sys.exit(1)

    if not (1 <= args.max_steps <= 100):
        sys.stderr.write(f"Error: --max-steps must be between 1 and 100 (received {args.max_steps})\n")
        sys.exit(1)

    if args.url:
        from open_use.core.security import validate_safe_url
        try:
            validate_safe_url(args.url)
        except Exception as e:
            sys.stderr.write(f"Error: Invalid URL '{args.url}': {e}\n")
            sys.exit(1)

    kwargs = {
        "goal": args.goal,
        "mode": args.mode,
        "url": args.url if args.url else None,
        "max_steps": args.max_steps,
    }
    if args.dry_run:
        kwargs["dry_run"] = True

    agent = OpenAgent()
    try:
        agent.run(**kwargs)
    finally:
        agent.close()


if __name__ == "__main__":
    main()
