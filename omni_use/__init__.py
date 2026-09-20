"""OmniUse: Dual-Core OS & Web Autonomous Agent Framework."""

from .agent import OmniAgent
from .desktop.agent import DesktopAgent
from .desktop.hal import get_current_platform, UIElement

__all__ = ["OmniAgent", "DesktopAgent", "get_current_platform", "UIElement"]
