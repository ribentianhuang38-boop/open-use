"""OpenUse: Dual-Core OS & Web Autonomous Agent Framework."""

from .agent import OpenAgent, OmniAgent
from .desktop.agent import DesktopAgent
from .desktop.hal import DesktopPlatform, UIElement, get_current_platform

__all__ = ["OpenAgent", "OmniAgent", "DesktopAgent", "DesktopPlatform", "get_current_platform", "UIElement"]
