from __future__ import annotations

from abc import ABC, abstractmethod

from src.config.schema import LibrarianConfig


class Configurable(ABC):
    """Abstract base class for components that support hot-reloadable configuration.

    Workers and other components that need to react to configuration changes
    should inherit from this class. When the ConfigLoader detects a config
    file change, it calls ``load_config`` on each registered Configurable,
    which sets the internal ``_config_pending`` flag. Workers should check
    this flag before executing tasks and apply the pending configuration.

    Attributes:
        _config_pending: Flag indicating that a new configuration has been
            delivered but not yet applied by the worker.
    """

    def __init__(self) -> None:
        """Initialize the Configurable with no pending configuration."""
        self._config_pending: bool = False

    @abstractmethod
    def load_config(self, config: LibrarianConfig) -> None:
        """Receive a new configuration from the config hot-reload system.

        Implementations should extract the fields they need from the global
        config and store them locally. They must also set
        ``_config_pending = True`` so that the worker knows to apply the
        new settings before its next task execution.

        Args:
            config: The newly loaded and validated LibrarianConfig.
        """

    def has_pending_config(self) -> bool:
        """Check whether a new configuration is waiting to be applied.

        Returns:
            True if ``load_config`` has been called more recently than
            the configuration was last applied.
        """
        return self._config_pending

    def mark_config_applied(self) -> None:
        """Mark the pending configuration as having been applied.

        Call this after the worker has finished applying the new
        configuration during its task execution cycle.
        """
        self._config_pending = False
