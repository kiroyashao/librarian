from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from langchain_openai import ChatOpenAI

from src.config.configurable import Configurable
from src.config.schema import LibrarianConfig, LLMConfig


class BaseWorker(Configurable, ABC):
    """Abstract base class for all worker nodes in the Librarian system.

    Combines the Configurable interface for hot-reload support with
    lazy initialization of LLM connections. Workers are not instantiated
    until first needed.

    Attributes:
        _llm: The LangChain ChatOpenAI instance, lazily initialized.
        _llm_config: The LLM configuration reference name.
        _initialized: Whether the worker has been fully initialized.
    """

    def __init__(self) -> None:
        """Initialize the BaseWorker with no LLM connection yet."""
        super().__init__()
        self._llm: ChatOpenAI | None = None
        self._llm_config_name: str | None = None
        self._initialized: bool = False

    def ensure_initialized(self, config: LibrarianConfig) -> None:
        """Lazily initialize the worker if not already done.

        Creates the LLM connection from the config and calls
        the subclass _on_initialize hook.

        Args:
            config: The current LibrarianConfig to read LLM settings from.
        """
        if self._initialized:
            if self.has_pending_config():
                self.load_config(config)
                self.mark_config_applied()
            return
        self.load_config(config)
        self._on_initialize(config)
        self._initialized = True
        self.mark_config_applied()

    def _create_llm(self, llm_config: LLMConfig) -> ChatOpenAI:
        """Create a ChatOpenAI instance from an LLMConfig.

        Args:
            llm_config: The LLM configuration to use.

        Returns:
            A configured ChatOpenAI instance.
        """
        kwargs: dict[str, Any] = {"model": llm_config.model or "gpt-4o-mini"}
        if llm_config.api_key:
            kwargs["api_key"] = llm_config.api_key
        if llm_config.api_base:
            kwargs["base_url"] = llm_config.api_base
        return ChatOpenAI(**kwargs)

    @abstractmethod
    def _on_initialize(self, config: LibrarianConfig) -> None:
        """Hook for subclasses to perform initialization logic.

        Called once when the worker is first used.

        Args:
            config: The current LibrarianConfig.
        """
        ...

    @abstractmethod
    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        """Execute the worker's task.

        Args:
            state: The current workflow state dict.

        Returns:
            An updated state dict with the worker's results.
        """
        ...
