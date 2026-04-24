from __future__ import annotations

import logging
import os
import re
import threading
from pathlib import Path
from typing import Any, Callable

import yaml
from dotenv import load_dotenv

from src.config.schema import LibrarianConfig

logger = logging.getLogger(__name__)

ConfigCallback = Callable[[LibrarianConfig], None]


def _camel_to_snake(name: str) -> str:
    """Convert a camelCase or PascalCase string to snake_case.

    Args:
        name: The camelCase or PascalCase string to convert.

    Returns:
        The snake_case equivalent of the input string.
    """
    s1 = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", name)
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s1).lower()


def _convert_keys(data: Any) -> Any:
    """Recursively convert all dictionary keys from camelCase to snake_case.

    Args:
        data: The data structure to convert. Can be a dict, list, or scalar.

    Returns:
        A new data structure with all dict keys converted to snake_case.
    """
    if isinstance(data, dict):
        return {_camel_to_snake(k): _convert_keys(v) for k, v in data.items()}
    if isinstance(data, list):
        return [_convert_keys(item) for item in data]
    return data


class ConfigLoader:
    """Loads, validates, and hot-reloads the librarian.yaml configuration.

    Watches the config file for changes using modification-time polling
    and notifies registered callbacks when the configuration is updated.

    Attributes:
        config_path: Path to the librarian.yaml file.
        env_path: Path to the .env file for LLM credential defaults.
    """

    _POLL_INTERVAL: float = 5.0

    def __init__(self, config_path: str | Path = "librarian.yaml", env_path: str | Path | None = None) -> None:
        """Initialize the ConfigLoader.

        Args:
            config_path: Path to the YAML configuration file.
            env_path: Optional path to the .env file. If None, looks for .env
                in the same directory as config_path.
        """
        self.config_path = Path(config_path)
        self.env_path = Path(env_path) if env_path else self.config_path.parent / ".env"
        self._config: LibrarianConfig | None = None
        self._last_mtime: float = 0.0
        self._callbacks: list[ConfigCallback] = []
        self._watcher_thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    def load(self) -> LibrarianConfig:
        """Load and validate the configuration from the YAML file.

        Also loads .env file for LLM credential defaults.

        Returns:
            The validated LibrarianConfig instance.

        Raises:
            FileNotFoundError: If the config file does not exist.
            pydantic.ValidationError: If the config data fails validation.
            yaml.YAMLError: If the YAML is malformed.
        """
        if self.env_path.exists():
            load_dotenv(self.env_path)

        raw = self._read_yaml()
        converted = _convert_keys(raw)
        self._config = LibrarianConfig.model_validate(converted)
        self._last_mtime = self.config_path.stat().st_mtime
        logger.info("Configuration loaded from %s", self.config_path)
        return self._config

    def get_config(self) -> LibrarianConfig:
        """Return the current validated configuration.

        Returns:
            The current LibrarianConfig instance.

        Raises:
            RuntimeError: If the configuration has not been loaded yet.
        """
        if self._config is None:
            raise RuntimeError("Configuration not loaded. Call load() first.")
        return self._config

    def on_change(self, callback: ConfigCallback) -> Callable[[], None]:
        """Register a callback to be invoked when the config file changes.

        Args:
            callback: A callable that receives the new LibrarianConfig when
                a change is detected.

        Returns:
            A unsubscribe function that removes the callback when called.
        """
        self._callbacks.append(callback)

        def unsubscribe() -> None:
            """Remove the previously registered callback."""
            try:
                self._callbacks.remove(callback)
            except ValueError:
                pass

        return unsubscribe

    def start_watching(self) -> None:
        """Start watching the config file for changes in a background thread.

        Polls the file modification time every 5 seconds. When a change is
        detected, the config is reloaded and all registered callbacks are
        notified.

        Raises:
            RuntimeError: If watching is already in progress.
        """
        if self._watcher_thread is not None and self._watcher_thread.is_alive():
            raise RuntimeError("Config watcher is already running.")

        self._stop_event.clear()
        self._watcher_thread = threading.Thread(
            target=self._watch_loop,
            name="config-watcher",
            daemon=True,
        )
        self._watcher_thread.start()
        logger.info("Started watching %s for changes", self.config_path)

    def stop_watching(self) -> None:
        """Stop the background config file watcher.

        Blocks until the watcher thread has fully stopped.
        """
        self._stop_event.set()
        if self._watcher_thread is not None:
            self._watcher_thread.join(timeout=self._POLL_INTERVAL + 1.0)
            self._watcher_thread = None
        logger.info("Stopped watching %s", self.config_path)

    def _read_yaml(self) -> dict[str, Any]:
        """Read and parse the YAML config file.

        Returns:
            The parsed YAML data as a dictionary.

        Raises:
            FileNotFoundError: If the config file does not exist.
        """
        if not self.config_path.exists():
            raise FileNotFoundError(f"Config file not found: {self.config_path}")
        with open(self.config_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return data if isinstance(data, dict) else {}

    def _watch_loop(self) -> None:
        """Background loop that polls for config file changes.

        Checks the file modification time at regular intervals and triggers
        a reload when a change is detected.
        """
        while not self._stop_event.is_set():
            self._stop_event.wait(timeout=self._POLL_INTERVAL)
            if self._stop_event.is_set():
                break
            try:
                self._check_for_changes()
            except Exception:
                logger.exception("Error checking for config changes")

    def _check_for_changes(self) -> None:
        """Check if the config file has been modified and reload if so.

        Notifies all registered callbacks with the new configuration when
        a change is detected.
        """
        if not self.config_path.exists():
            return

        current_mtime = self.config_path.stat().st_mtime
        if current_mtime == self._last_mtime:
            return

        logger.info("Config change detected (mtime: %s -> %s)", self._last_mtime, current_mtime)
        try:
            new_config = self.load()
        except Exception:
            logger.exception("Failed to reload config; keeping previous version")
            self._last_mtime = current_mtime
            return

        for callback in self._callbacks:
            try:
                callback(new_config)
            except Exception:
                logger.exception("Config change callback raised an error")
