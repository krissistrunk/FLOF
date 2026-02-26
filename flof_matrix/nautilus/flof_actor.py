"""Base FLOF Actor — provides toggle-checking and config-access to NautilusTrader Actors."""

from __future__ import annotations

import logging

from flof_matrix.config.config_manager import ConfigManager

logger = logging.getLogger(__name__)


class FlofActorBase:
    """Base class for FLOF modules that need config and toggle access.

    Not a NautilusTrader Actor directly — provides the FLOF-specific
    functionality that wraps around any NT actor/strategy.
    """

    def __init__(self, config: ConfigManager) -> None:
        self._config = config

    def get_config(self, key: str, default=None):
        """Get config value using dot notation."""
        return self._config.get(key, default)

    def is_toggle_enabled(self, toggle_id: str) -> bool:
        """Check if a feature toggle is enabled (respects dependency chain)."""
        return self._config.is_toggle_enabled(toggle_id)

    def log_info(self, msg: str, *args) -> None:
        logger.info(f"[{self.__class__.__name__}] {msg}", *args)

    def log_warning(self, msg: str, *args) -> None:
        logger.warning(f"[{self.__class__.__name__}] {msg}", *args)

    def log_error(self, msg: str, *args) -> None:
        logger.error(f"[{self.__class__.__name__}] {msg}", *args)
