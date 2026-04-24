from __future__ import annotations

import os
from typing import Optional

from pydantic import BaseModel, Field, model_validator


class LLMConfig(BaseModel):
    """Configuration for a single LLM provider.

    Attributes:
        name: Unique identifier for this LLM, used as reference key in workers.
        model: Model identifier. Falls back to MODEL env var if not set.
        api_key: API key for authentication. Falls back to API_KEY env var if not set.
        api_base: API base URL. Falls back to API_BASE env var if not set.
    """

    name: str
    model: Optional[str] = None
    api_key: Optional[str] = None
    api_base: Optional[str] = None

    def resolve_defaults(self) -> LLMConfig:
        """Fill in missing fields from environment variables.

        Returns:
            A new LLMConfig with env var defaults applied for any missing fields.
        """
        return LLMConfig(
            name=self.name,
            model=self.model or os.getenv("MODEL"),
            api_key=self.api_key or os.getenv("API_KEY"),
            api_base=self.api_base or os.getenv("API_BASE"),
        )


class SplitRule(BaseModel):
    """Rules for splitting skill files into smaller chunks.

    Attributes:
        max_lines: Maximum number of lines per chunk.
        min_lines: Minimum number of lines per chunk.
    """

    max_lines: int = Field(default=1000, gt=0)
    min_lines: int = Field(default=100, gt=0)

    @model_validator(mode="after")
    def _validate_range(self) -> SplitRule:
        """Ensure max_lines is greater than min_lines.

        Returns:
            The validated SplitRule instance.

        Raises:
            ValueError: If max_lines is not greater than min_lines.
        """
        if self.max_lines <= self.min_lines:
            raise ValueError(
                f"max_lines ({self.max_lines}) must be greater than min_lines ({self.min_lines})"
            )
        return self


class WorkerConfigBase(BaseModel):
    """Base configuration shared by all worker nodes.

    Attributes:
        llm: Name reference to an LLM defined in the top-level llms list.
    """

    llm: Optional[str] = None


class SkillEvaluatorConfig(WorkerConfigBase):
    """Configuration for the SkillEvaluator worker.

    Attributes:
        quality_threshold: Minimum quality score (0.0-1.0) for a skill to be accepted.
        require_human_review: Whether human review is required before accepting.
        categories: List of valid skill categories.
    """

    quality_threshold: float = Field(default=0.7, ge=0.0, le=1.0)
    require_human_review: bool = False
    categories: list[str] = Field(default_factory=list)


class SkillSplitterConfig(WorkerConfigBase):
    """Configuration for the SkillSplitter worker.

    Attributes:
        split_rule: Rules governing how skills are split into chunks.
    """

    split_rule: SplitRule = Field(default_factory=SplitRule)


class ToolGuardianConfig(WorkerConfigBase):
    """Configuration for the ToolGuardian worker.

    Attributes:
        require_human_review: Whether human review is required before tool approval.
    """

    require_human_review: bool = True


class WorkersConfig(BaseModel):
    """Configuration for all worker nodes in the system.

    Attributes:
        config_loader: ConfigLoader worker settings.
        skill_router: SkillRouter worker settings.
        skill_evaluator: SkillEvaluator worker settings.
        skill_deduplicator: SkillDeduplicator worker settings.
        skill_splitter: SkillSplitter worker settings.
        skill_pruner: SkillPruner worker settings.
        skill_link_maintainer: SkillLinkMaintainer worker settings.
        tool_synthesizer: ToolSynthesizer worker settings.
        tool_guardian: ToolGuardian worker settings.
    """

    config_loader: WorkerConfigBase = Field(default_factory=WorkerConfigBase)
    skill_router: WorkerConfigBase = Field(default_factory=WorkerConfigBase)
    skill_evaluator: SkillEvaluatorConfig = Field(default_factory=SkillEvaluatorConfig)
    skill_deduplicator: WorkerConfigBase = Field(default_factory=WorkerConfigBase)
    skill_splitter: SkillSplitterConfig = Field(default_factory=SkillSplitterConfig)
    skill_pruner: WorkerConfigBase = Field(default_factory=WorkerConfigBase)
    skill_link_maintainer: WorkerConfigBase = Field(default_factory=WorkerConfigBase)
    tool_synthesizer: WorkerConfigBase = Field(default_factory=WorkerConfigBase)
    tool_guardian: ToolGuardianConfig = Field(default_factory=ToolGuardianConfig)


class CronjobConfig(BaseModel):
    """Configuration for a single cronjob.

    Attributes:
        schedule: Cron expression defining the job schedule.
    """

    schedule: str


class CronjobsConfig(BaseModel):
    """Configuration for the cronjob scheduler.

    Attributes:
        enabled: Whether cronjobs are active.
        jobs: Mapping of job names to their configurations.
    """

    enabled: bool = True
    jobs: dict[str, CronjobConfig] = Field(default_factory=dict)


class ApiConfig(BaseModel):
    """Configuration for the FastAPI server.

    Attributes:
        port: Port number the API server listens on (1-65535).
        host: Host address the API server binds to.
    """

    port: int = Field(default=9112, ge=1, le=65535)
    host: str = "0.0.0.0"


class DatabaseConfig(BaseModel):
    """Configuration for the SQLite database.

    Attributes:
        path: File path to the SQLite database file.
    """

    path: str = "./data/librarian.db"


class LoggingConfig(BaseModel):
    """Configuration for the logging system.

    Attributes:
        level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL).
        file: File path for the log output.
    """

    level: str = Field(default="INFO", pattern=r"^(DEBUG|INFO|WARNING|ERROR|CRITICAL)$")
    file: str = "./logs/librarian.log"


class LibrarianConfig(BaseModel):
    """Top-level configuration for the Librarian Skills management system.

    Validates the entire config structure including LLM reference integrity
    and applies environment variable defaults for LLM credentials.

    Attributes:
        llms: List of available LLM configurations.
        workers: Configuration for all worker nodes.
        cronjobs: Cronjob scheduler configuration.
        skill_trigger_threshold: Minimum trigger count before skill processing.
        max_rejection_count: Maximum times a skill can be rejected before discarding.
        api: FastAPI server configuration.
        database: Database configuration.
        logging: Logging configuration.
    """

    llms: list[LLMConfig] = Field(default_factory=list)
    workers: WorkersConfig = Field(default_factory=WorkersConfig)
    cronjobs: CronjobsConfig = Field(default_factory=CronjobsConfig)
    skill_trigger_threshold: int = Field(default=10, ge=1)
    max_rejection_count: int = Field(default=3, ge=1)
    api: ApiConfig = Field(default_factory=ApiConfig)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)

    @model_validator(mode="after")
    def _resolve_and_validate(self) -> LibrarianConfig:
        """Resolve LLM env-var defaults and validate worker LLM references.

        Returns:
            The validated LibrarianConfig with resolved LLM defaults.

        Raises:
            ValueError: If a worker references an LLM name not defined in the llms list.
        """
        resolved_llms: list[LLMConfig] = []
        for llm in self.llms:
            resolved_llms.append(llm.resolve_defaults())
        self.llms = resolved_llms

        llm_names = {llm.name for llm in self.llms}
        worker_llm_refs = self._collect_worker_llm_refs()
        for ref in worker_llm_refs:
            if ref not in llm_names:
                raise ValueError(
                    f"Worker references LLM '{ref}' which is not defined in llms. "
                    f"Available: {sorted(llm_names)}"
                )
        return self

    def _collect_worker_llm_refs(self) -> set[str]:
        """Collect all non-None LLM name references from worker configs.

        Returns:
            Set of LLM name strings referenced by workers.
        """
        refs: set[str] = set()
        workers = self.workers
        for field_name in workers.__class__.model_fields:
            worker_cfg = getattr(workers, field_name)
            if isinstance(worker_cfg, WorkerConfigBase) and worker_cfg.llm is not None:
                refs.add(worker_cfg.llm)
        return refs

    def get_llm(self, name: str) -> Optional[LLMConfig]:
        """Look up an LLM configuration by name.

        Args:
            name: The unique name identifier of the LLM.

        Returns:
            The matching LLMConfig, or None if no LLM with that name exists.
        """
        for llm in self.llms:
            if llm.name == name:
                return llm
        return None
