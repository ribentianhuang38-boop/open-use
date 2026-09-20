"""Unified Configuration and Environment Management for OpenUse."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

logger = logging.getLogger("open_use.core.config")

_ENV_LOADED = False


def load_env(force: bool = False) -> None:
    """Discover and load .env from current working directory or any parent directories."""
    global _ENV_LOADED
    if _ENV_LOADED and not force:
        key = os.environ.get("TYPESAFE_API_KEY") or os.environ.get("JEV_API_KEY")
        if key:
            os.environ.setdefault("TYPESAFE_API_KEY", key)
            os.environ.setdefault("JEV_API_KEY", key)
        return

    curr = Path.cwd().resolve()
    candidates = [curr / ".env"]
    # Add parents up to root
    for parent in curr.parents:
        candidates.append(parent / ".env")

    # Add package root parents
    pkg_dir = Path(__file__).resolve().parent
    for p in [pkg_dir, pkg_dir.parent, pkg_dir.parent.parent]:
        candidates.append(p / ".env")

    for env_path in candidates:
        if env_path.is_file():
            try:
                from dotenv import load_dotenv
                load_dotenv(env_path)
                logger.debug(f"Loaded .env from {env_path}")
            except ImportError:
                try:
                    for line in env_path.read_text(encoding="utf-8").splitlines():
                        line = line.strip()
                        if line and not line.startswith("#") and "=" in line:
                            k, v = line.split("=", 1)
                            os.environ.setdefault(k.strip(), v.strip().strip("'\""))
                    logger.debug(f"Loaded .env manually from {env_path}")
                except Exception as e:
                    logger.warning(f"Failed to read .env at {env_path}: {e}")
            break

    # Alias sync: JEV_API_KEY <-> TYPESAFE_API_KEY
    key = os.environ.get("TYPESAFE_API_KEY") or os.environ.get("JEV_API_KEY")
    if key:
        os.environ.setdefault("TYPESAFE_API_KEY", key)
        os.environ.setdefault("JEV_API_KEY", key)

    _ENV_LOADED = True


def get_typesafe_base_url() -> str:
    """Get the configured TypeSafe API Base URL."""
    load_env()
    return os.environ.get("TYPESAFE_BASE_URL", "https://api.typesafe.ai/v1").rstrip("/")


def get_cdp_port() -> int:
    """Get the configured Chrome DevTools Protocol port."""
    load_env()
    return int(os.environ.get("OPENUSE_CDP_PORT", "9333"))
