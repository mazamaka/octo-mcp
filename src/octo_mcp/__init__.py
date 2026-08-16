"""Octo Browser MCP Server -- control antidetect browser profiles with AI."""

__version__ = "0.3.0"
__author__ = "Maksym Babenko"

__all__ = [
    "BrowserManager",
    "OctoAPIError",
    "OctoCloudClient",
    "OctoLocalClient",
    "__version__",
]

from .browser_manager import BrowserManager
from .octo_client import OctoAPIError, OctoCloudClient, OctoLocalClient
