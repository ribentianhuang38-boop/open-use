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


def get_llm_provider() -> str:
    """Get the preferred System 2 LLM provider: auto, gemini, openai, anthropic, or custom."""
    load_env()
    return os.environ.get("LLM_PROVIDER", os.environ.get("OPENUSE_LLM_PROVIDER", "auto")).lower()


def get_llm_api_key(provider: Optional[str] = None) -> Optional[str]:
    """Retrieve API key for the requested or auto-detected LLM provider."""
    load_env()
    prov = (provider or get_llm_provider()).lower()
    if prov in ("gemini", "google"):
        return os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    elif prov == "openai":
        return os.environ.get("OPENAI_API_KEY")
    elif prov == "anthropic":
        return os.environ.get("ANTHROPIC_API_KEY")
    
    # Generic or auto detection
    return (
        os.environ.get("LLM_API_KEY")
        or os.environ.get("GEMINI_API_KEY")
        or os.environ.get("GOOGLE_API_KEY")
        or os.environ.get("OPENAI_API_KEY")
        or os.environ.get("ANTHROPIC_API_KEY")
    )


def get_llm_base_url(provider: Optional[str] = None) -> Optional[str]:
    """Retrieve Base URL for OpenAI-compatible or custom providers."""
    load_env()
    prov = (provider or get_llm_provider()).lower()
    if prov == "openai":
        return os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    return os.environ.get("LLM_BASE_URL")


def get_llm_model(provider: Optional[str] = None) -> Optional[str]:
    """Retrieve default or configured model name for the provider."""
    load_env()
    prov = (provider or get_llm_provider()).lower()
    if prov in ("gemini", "google"):
        return os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")
    elif prov == "openai":
        return os.environ.get("OPENAI_MODEL", "gpt-4o")
    elif prov == "anthropic":
        return os.environ.get("ANTHROPIC_MODEL", "claude-3-5-sonnet-20241022")
    return os.environ.get("LLM_MODEL")

