"""ConfigManager — 3-layer TOML config with deep merge, dot-notation access, and toggle support."""

from __future__ import annotations

import copy
import sys
from pathlib import Path
from typing import Any

from flof_matrix.config.toggle_registry import ToggleRegistry

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib


def _deep_merge(base: dict, override: dict) -> dict:
    """Deep merge override into base (last wins). Returns new dict."""
    result = copy.deepcopy(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def _get_nested(d: dict, dotted_key: str, default: Any = None) -> Any:
    """Get a value from a nested dict using dot notation."""
    parts = dotted_key.split(".")
    current = d
    for part in parts:
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return default
    return current


def _set_nested(d: dict, dotted_key: str, value: Any) -> None:
    """Set a value in a nested dict using dot notation."""
    parts = dotted_key.split(".")
    current = d
    for part in parts[:-1]:
        current = current.setdefault(part, {})
    current[parts[-1]] = value


class ConfigManager:
    """Singleton config manager with 3-layer TOML merge and toggle support.

    Merge order (last wins): base → profile → instrument
    """

    _instance: ConfigManager | None = None

    def __new__(cls) -> ConfigManager:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self._config: dict[str, Any] = {}
        self._base_path: Path | None = None
        self._profile: str | None = None
        self._instrument: str | None = None
        self._toggle_registry: ToggleRegistry | None = None
        self._initialized = True

    @classmethod
    def reset(cls) -> None:
        """Reset singleton (for testing)."""
        cls._instance = None

    def load(
        self,
        base_path: str | Path,
        profile: str | None = None,
        instrument: str | None = None,
    ) -> None:
        """Load and merge config layers.

        Args:
            base_path: Path to flof_base.toml
            profile: Profile name (e.g. 'futures') — loads profile_{name}.toml
            instrument: Instrument override file (future use)
        """
        self._base_path = Path(base_path)
        self._profile = profile
        self._instrument = instrument

        # Layer 1: Base
        self._config = self._load_toml(self._base_path)

        # Layer 2: Profile override
        if profile:
            profile_path = self._base_path.parent / "profiles" / f"profile_{profile}.toml"
            if profile_path.exists():
                profile_config = self._load_toml(profile_path)
                self._config = _deep_merge(self._config, profile_config)

        # Layer 3: Instrument override (future use)
        if instrument:
            instrument_path = (
                self._base_path.parent / "instruments" / f"constants.{instrument}.toml"
            )
            if instrument_path.exists():
                instrument_config = self._load_toml(instrument_path)
                self._config = _deep_merge(self._config, instrument_config)

        # Initialize toggle registry
        live_mode = self.get("system.live_mode", False)
        self._toggle_registry = ToggleRegistry(self.get, live_mode=live_mode)

        # Enforce safety locks
        if live_mode:
            self._toggle_registry.enforce_safety_locks(self._config)

    def _load_toml(self, path: Path) -> dict[str, Any]:
        with open(path, "rb") as f:
            return tomllib.load(f)

    def get(self, dotted_key: str, default: Any = None) -> Any:
        """Get config value using dot notation. E.g. get('scoring.tier1.gate_minimum')."""
        return _get_nested(self._config, dotted_key, default)

    def is_toggle_enabled(self, toggle_id: str) -> bool:
        """Check if a toggle is enabled, respecting dependency chain and safety locks."""
        if self._toggle_registry is None:
            raise RuntimeError("ConfigManager not loaded. Call load() first.")
        return self._toggle_registry.is_enabled(toggle_id)

    def validate_toggles(self) -> list[str]:
        """Return list of toggle validation errors."""
        if self._toggle_registry is None:
            raise RuntimeError("ConfigManager not loaded. Call load() first.")
        return self._toggle_registry.validate()

    def enforce_safety_locks(self) -> None:
        """Force safety toggles ON when live_mode=true."""
        if self._toggle_registry is None:
            raise RuntimeError("ConfigManager not loaded. Call load() first.")
        self._toggle_registry.enforce_safety_locks(self._config)

    def reload(self) -> None:
        """Hot-reload config. Only allowed when live_mode=false."""
        if self.get("system.live_mode", False):
            raise RuntimeError("Hot-reload is disabled in live mode.")
        if self._base_path is not None:
            self.load(self._base_path, self._profile, self._instrument)

    @property
    def raw(self) -> dict[str, Any]:
        """Access the raw merged config dict."""
        return self._config
