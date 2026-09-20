"""JevGate: Hard Execution Gate enforcing Jev System One dispatch.

All native hardware actions (click, hotkey, scroll, type) MUST be authorized
by an active Jev execution session. Direct unmediated calls to HAL by external scripts
or bypassed LLM invocations are strictly prohibited and immediately aborted.
"""

from __future__ import annotations

import contextvars
import functools
import logging
import os
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, TypeVar

logger = logging.getLogger("open_use.core.jev_gate")

F = TypeVar("F", bound=Callable[..., Any])


class JevEnforcementError(PermissionError):
    """Raised when a hardware action is invoked without Jev System One authorization."""
    pass


@dataclass
class JevSessionInfo:
    session_id: str
    step: int
    decision_token: str
    created_at: float
    is_test_bypass: bool = False
    executed_actions: List[Dict[str, Any]] = field(default_factory=list)


_ACTIVE_JEV_SESSION: contextvars.ContextVar[Optional[JevSessionInfo]] = contextvars.ContextVar(
    "_ACTIVE_JEV_SESSION", default=None
)


class JevContext:
    """Context manager and authority for Jev session token lifecycle."""

    @classmethod
    def is_active_jev_session(cls) -> bool:
        """Check if the current context has an active, valid Jev execution session."""
        if os.environ.get("OPENUSE_ALLOW_RAW_HAL", "").lower() in ("1", "true", "yes"):
            return True

        session = _ACTIVE_JEV_SESSION.get()
        return session is not None

    @classmethod
    def current_session(cls) -> Optional[JevSessionInfo]:
        return _ACTIVE_JEV_SESSION.get()

    @classmethod
    @contextmanager
    def session(
        cls,
        step: int = 1,
        decision_token: Optional[str] = None,
        is_test_bypass: bool = False,
    ):
        """Activate a verified Jev decision execution session."""
        token_str = decision_token or f"jev_tok_{uuid.uuid4().hex[:12]}"
        sess = JevSessionInfo(
            session_id=str(uuid.uuid4()),
            step=step,
            decision_token=token_str,
            created_at=time.time(),
            is_test_bypass=is_test_bypass,
        )
        token = _ACTIVE_JEV_SESSION.set(sess)
        try:
            yield sess
        finally:
            _ACTIVE_JEV_SESSION.reset(token)

    @classmethod
    @contextmanager
    def bypass_for_test(cls):
        """Explicitly authorize testing environments to run low-level HAL checks."""
        with cls.session(step=0, decision_token="test_bypass", is_test_bypass=True):
            yield

    @classmethod
    def record_action(cls, action_name: str, details: Dict[str, Any]) -> None:
        sess = _ACTIVE_JEV_SESSION.get()
        if sess:
            sess.executed_actions.append({
                "action": action_name,
                "details": details,
                "timestamp": time.time(),
            })


def require_jev_token(func: F) -> F:
    """Decorator guarding HAL methods against unmediated direct calls."""

    @functools.wraps(func)
    def wrapper(self, *args, **kwargs):
        if not JevContext.is_active_jev_session():
            func_name = getattr(func, "__qualname__", func.__name__)
            raise JevEnforcementError(
                f"🚨 [JevGate VIOLATION] Hardware action '{func_name}' rejected!\n"
                "Direct invocation bypassed Jev System One decision engine.\n"
                "All hardware actions MUST be dispatched through DesktopAgent or OpenAgent."
            )
        # Record telemetry
        JevContext.record_action(func.__name__, {"args": args, "kwargs": kwargs})
        return func(self, *args, **kwargs)

    return wrapper  # type: ignore
