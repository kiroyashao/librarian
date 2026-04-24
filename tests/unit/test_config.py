from __future__ import annotations

import os
from pathlib import Path
from typing import Optional
from unittest.mock import MagicMock, patch

import pytest
import yaml
from pydantic import ValidationError

from src.config.configurable import Configurable
from src.config.loader import ConfigLoader, _camel_to_snake, _convert_keys
from src.config.schema import (
    ApiConfig,
    CronjobConfig,
    CronjobsConfig,
    DatabaseConfig,
    LLMConfig,
    LibrarianConfig,
    LoggingConfig,
    SkillEvaluatorConfig,
    SkillSplitterConfig,
    SplitRule,
    ToolGuardianConfig,
    WorkerConfigBase,
    WorkersConfig,
)


VALID_YAML_MINIMAL: str = "{}"

VALID_YAML_FULL: str = """
llms:
  - name: primary
    model: gpt-4
    apiKey: sk-test-key
    apiBase: https://api.example.com
workers:
  skillEvaluator:
    llm: primary
    qualityThreshold: 0.85
    requireHumanReview: true
    categories:
      - search
      - analysis
  skillSplitter:
    llm: primary
    splitRule:
      maxLines: 500
      minLines: 50
  toolGuardian:
    llm: primary
    requireHumanReview: false
cronjobs:
  enabled: true
  jobs:
    cleanup:
      schedule: "0 3 * * *"
api:
  port: 8080
  host: "127.0.0.1"
database:
  path: "./data/test.db"
logging:
  level: DEBUG
  file: "./logs/test.log"
skillTriggerThreshold: 5
maxRejectionCount: 2
"""


class TestLLMConfig:
    """Tests for LLMConfig schema and resolve_defaults."""

    def test_create_with_all_fields(self) -> None:
        llm = LLMConfig(name="test", model="gpt-4", api_key="sk-key", api_base="https://api.test.com")
        assert llm.name == "test"
        assert llm.model == "gpt-4"
        assert llm.api_key == "sk-key"
        assert llm.api_base == "https://api.test.com"

    def test_create_with_name_only(self) -> None:
        llm = LLMConfig(name="minimal")
        assert llm.name == "minimal"
        assert llm.model is None
        assert llm.api_key is None
        assert llm.api_base is None

    def test_resolve_defaults_from_env(self) -> None:
        llm = LLMConfig(name="envtest")
        with patch.dict(os.environ, {
            "MODEL": "env-model",
            "API_KEY": "env-key",
            "API_BASE": "https://env.base",
        }):
            resolved = llm.resolve_defaults()
        assert resolved.model == "env-model"
        assert resolved.api_key == "env-key"
        assert resolved.api_base == "https://env.base"

    def test_resolve_defaults_preserves_existing_values(self) -> None:
        llm = LLMConfig(name="keep", model="my-model", api_key="my-key", api_base="https://my.base")
        with patch.dict(os.environ, {
            "MODEL": "env-model",
            "API_KEY": "env-key",
            "API_BASE": "https://env.base",
        }):
            resolved = llm.resolve_defaults()
        assert resolved.model == "my-model"
        assert resolved.api_key == "my-key"
        assert resolved.api_base == "https://my.base"

    def test_resolve_defaults_no_env_vars(self) -> None:
        llm = LLMConfig(name="noenv")
        with patch.dict(os.environ, {}, clear=True):
            resolved = llm.resolve_defaults()
        assert resolved.model is None
        assert resolved.api_key is None
        assert resolved.api_base is None

    def test_resolve_defaults_returns_new_instance(self) -> None:
        llm = LLMConfig(name="orig")
        resolved = llm.resolve_defaults()
        assert resolved is not llm


class TestSplitRule:
    """Tests for SplitRule validation."""

    def test_default_values(self) -> None:
        rule = SplitRule()
        assert rule.max_lines == 1000
        assert rule.min_lines == 100

    def test_valid_custom_values(self) -> None:
        rule = SplitRule(max_lines=500, min_lines=50)
        assert rule.max_lines == 500
        assert rule.min_lines == 50

    def test_max_lines_equal_min_lines_raises(self) -> None:
        with pytest.raises(ValidationError, match="max_lines.*must be greater than min_lines"):
            SplitRule(max_lines=100, min_lines=100)

    def test_max_lines_less_than_min_lines_raises(self) -> None:
        with pytest.raises(ValidationError, match="max_lines.*must be greater than min_lines"):
            SplitRule(max_lines=50, min_lines=100)

    def test_negative_max_lines_raises(self) -> None:
        with pytest.raises(ValidationError):
            SplitRule(max_lines=-1, min_lines=100)

    def test_negative_min_lines_raises(self) -> None:
        with pytest.raises(ValidationError):
            SplitRule(max_lines=1000, min_lines=-1)

    def test_zero_max_lines_raises(self) -> None:
        with pytest.raises(ValidationError):
            SplitRule(max_lines=0, min_lines=100)

    def test_zero_min_lines_raises(self) -> None:
        with pytest.raises(ValidationError):
            SplitRule(max_lines=1000, min_lines=0)


class TestSkillEvaluatorConfig:
    """Tests for SkillEvaluatorConfig validation."""

    def test_default_values(self) -> None:
        cfg = SkillEvaluatorConfig()
        assert cfg.quality_threshold == 0.7
        assert cfg.require_human_review is False
        assert cfg.categories == []
        assert cfg.llm is None

    def test_valid_custom_values(self) -> None:
        cfg = SkillEvaluatorConfig(
            llm="primary",
            quality_threshold=0.9,
            require_human_review=True,
            categories=["search", "analysis"],
        )
        assert cfg.llm == "primary"
        assert cfg.quality_threshold == 0.9
        assert cfg.require_human_review is True
        assert cfg.categories == ["search", "analysis"]

    def test_quality_threshold_above_one_raises(self) -> None:
        with pytest.raises(ValidationError):
            SkillEvaluatorConfig(quality_threshold=1.5)

    def test_quality_threshold_below_zero_raises(self) -> None:
        with pytest.raises(ValidationError):
            SkillEvaluatorConfig(quality_threshold=-0.1)

    def test_quality_threshold_boundary_zero(self) -> None:
        cfg = SkillEvaluatorConfig(quality_threshold=0.0)
        assert cfg.quality_threshold == 0.0

    def test_quality_threshold_boundary_one(self) -> None:
        cfg = SkillEvaluatorConfig(quality_threshold=1.0)
        assert cfg.quality_threshold == 1.0


class TestSkillSplitterConfig:
    """Tests for SkillSplitterConfig with nested SplitRule."""

    def test_default_split_rule(self) -> None:
        cfg = SkillSplitterConfig()
        assert cfg.split_rule.max_lines == 1000
        assert cfg.split_rule.min_lines == 100

    def test_custom_split_rule(self) -> None:
        cfg = SkillSplitterConfig(split_rule=SplitRule(max_lines=200, min_lines=20))
        assert cfg.split_rule.max_lines == 200
        assert cfg.split_rule.min_lines == 20


class TestToolGuardianConfig:
    """Tests for ToolGuardianConfig defaults."""

    def test_default_values(self) -> None:
        cfg = ToolGuardianConfig()
        assert cfg.require_human_review is True
        assert cfg.llm is None

    def test_custom_values(self) -> None:
        cfg = ToolGuardianConfig(llm="guard", require_human_review=False)
        assert cfg.llm == "guard"
        assert cfg.require_human_review is False


class TestWorkersConfig:
    """Tests for WorkersConfig with all 9 worker fields."""

    def test_default_values(self) -> None:
        cfg = WorkersConfig()
        assert isinstance(cfg.config_loader, WorkerConfigBase)
        assert isinstance(cfg.skill_router, WorkerConfigBase)
        assert isinstance(cfg.skill_evaluator, SkillEvaluatorConfig)
        assert isinstance(cfg.skill_deduplicator, WorkerConfigBase)
        assert isinstance(cfg.skill_splitter, SkillSplitterConfig)
        assert isinstance(cfg.skill_pruner, WorkerConfigBase)
        assert isinstance(cfg.skill_link_maintainer, WorkerConfigBase)
        assert isinstance(cfg.tool_synthesizer, WorkerConfigBase)
        assert isinstance(cfg.tool_guardian, ToolGuardianConfig)

    def test_nine_worker_fields(self) -> None:
        cfg = WorkersConfig()
        assert len(WorkersConfig.model_fields) == 9


class TestCronjobsConfig:
    """Tests for CronjobsConfig and CronjobConfig."""

    def test_default_values(self) -> None:
        cfg = CronjobsConfig()
        assert cfg.enabled is True
        assert cfg.jobs == {}

    def test_with_jobs(self) -> None:
        cfg = CronjobsConfig(
            enabled=False,
            jobs={"cleanup": CronjobConfig(schedule="0 3 * * *")},
        )
        assert cfg.enabled is False
        assert "cleanup" in cfg.jobs
        assert cfg.jobs["cleanup"].schedule == "0 3 * * *"


class TestApiConfig:
    """Tests for ApiConfig port validation."""

    def test_default_values(self) -> None:
        cfg = ApiConfig()
        assert cfg.port == 9112
        assert cfg.host == "0.0.0.0"

    def test_custom_values(self) -> None:
        cfg = ApiConfig(port=8080, host="127.0.0.1")
        assert cfg.port == 8080
        assert cfg.host == "127.0.0.1"

    def test_port_zero_raises(self) -> None:
        with pytest.raises(ValidationError):
            ApiConfig(port=0)

    def test_port_negative_raises(self) -> None:
        with pytest.raises(ValidationError):
            ApiConfig(port=-1)

    def test_port_too_large_raises(self) -> None:
        with pytest.raises(ValidationError):
            ApiConfig(port=70000)

    def test_port_boundary_one(self) -> None:
        cfg = ApiConfig(port=1)
        assert cfg.port == 1

    def test_port_boundary_65535(self) -> None:
        cfg = ApiConfig(port=65535)
        assert cfg.port == 65535


class TestDatabaseConfig:
    """Tests for DatabaseConfig defaults."""

    def test_default_values(self) -> None:
        cfg = DatabaseConfig()
        assert cfg.path == "./data/librarian.db"

    def test_custom_path(self) -> None:
        cfg = DatabaseConfig(path="/tmp/test.db")
        assert cfg.path == "/tmp/test.db"


class TestLoggingConfig:
    """Tests for LoggingConfig level validation."""

    def test_default_values(self) -> None:
        cfg = LoggingConfig()
        assert cfg.level == "INFO"
        assert cfg.file == "./logs/librarian.log"

    def test_all_valid_levels(self) -> None:
        for level in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
            cfg = LoggingConfig(level=level)
            assert cfg.level == level

    def test_invalid_level_raises(self) -> None:
        with pytest.raises(ValidationError):
            LoggingConfig(level="TRACE")

    def test_lowercase_level_raises(self) -> None:
        with pytest.raises(ValidationError):
            LoggingConfig(level="info")


class TestLibrarianConfig:
    """Tests for top-level LibrarianConfig validation."""

    def test_default_config(self) -> None:
        cfg = LibrarianConfig()
        assert cfg.llms == []
        assert cfg.skill_trigger_threshold == 10
        assert cfg.max_rejection_count == 3

    def test_valid_full_config(self) -> None:
        cfg = LibrarianConfig(
            llms=[LLMConfig(name="primary", model="gpt-4", api_key="key", api_base="https://api.test.com")],
            workers=WorkersConfig(
                skill_evaluator=SkillEvaluatorConfig(llm="primary", quality_threshold=0.85),
            ),
        )
        assert len(cfg.llms) == 1
        assert cfg.llms[0].name == "primary"
        assert cfg.workers.skill_evaluator.llm == "primary"

    def test_invalid_llm_ref_raises(self) -> None:
        with pytest.raises(ValidationError, match="Worker references LLM 'missing'"):
            LibrarianConfig(
                llms=[LLMConfig(name="primary", model="gpt-4")],
                workers=WorkersConfig(
                    skill_evaluator=SkillEvaluatorConfig(llm="missing"),
                ),
            )

    def test_resolve_defaults_applied(self) -> None:
        with patch.dict(os.environ, {
            "MODEL": "env-model",
            "API_KEY": "env-key",
            "API_BASE": "https://env.base",
        }):
            cfg = LibrarianConfig(
                llms=[LLMConfig(name="envtest")],
            )
        assert cfg.llms[0].model == "env-model"
        assert cfg.llms[0].api_key == "env-key"
        assert cfg.llms[0].api_base == "https://env.base"

    def test_get_llm_found(self) -> None:
        cfg = LibrarianConfig(
            llms=[
                LLMConfig(name="alpha", model="a"),
                LLMConfig(name="beta", model="b"),
            ],
        )
        result = cfg.get_llm("beta")
        assert result is not None
        assert result.name == "beta"

    def test_get_llm_not_found(self) -> None:
        cfg = LibrarianConfig(llms=[LLMConfig(name="alpha", model="a")])
        result = cfg.get_llm("nonexistent")
        assert result is None

    def test_collect_worker_llm_refs(self) -> None:
        cfg = LibrarianConfig(
            llms=[LLMConfig(name="primary", model="gpt-4")],
            workers=WorkersConfig(
                skill_evaluator=SkillEvaluatorConfig(llm="primary"),
                skill_router=WorkerConfigBase(llm="primary"),
                tool_guardian=ToolGuardianConfig(llm=None),
            ),
        )
        refs = cfg._collect_worker_llm_refs()
        assert refs == {"primary"}

    def test_skill_trigger_threshold_minimum(self) -> None:
        cfg = LibrarianConfig(skill_trigger_threshold=1)
        assert cfg.skill_trigger_threshold == 1

    def test_skill_trigger_threshold_zero_raises(self) -> None:
        with pytest.raises(ValidationError):
            LibrarianConfig(skill_trigger_threshold=0)

    def test_max_rejection_count_zero_raises(self) -> None:
        with pytest.raises(ValidationError):
            LibrarianConfig(max_rejection_count=0)


class TestCamelToSnake:
    """Tests for _camel_to_snake helper function."""

    def test_camel_case(self) -> None:
        assert _camel_to_snake("qualityThreshold") == "quality_threshold"

    def test_pascal_case(self) -> None:
        assert _camel_to_snake("QualityThreshold") == "quality_threshold"

    def test_already_snake_case(self) -> None:
        assert _camel_to_snake("quality_threshold") == "quality_threshold"

    def test_single_word_lowercase(self) -> None:
        assert _camel_to_snake("port") == "port"

    def test_single_word_uppercase(self) -> None:
        assert _camel_to_snake("Port") == "port"

    def test_multiple_capitals(self) -> None:
        assert _camel_to_snake("apiKey") == "api_key"

    def test_acronym_sequence(self) -> None:
        assert _camel_to_snake("apiBaseURL") == "api_base_url"

    def test_empty_string(self) -> None:
        assert _camel_to_snake("") == ""

    def test_consecutive_capitals(self) -> None:
        assert _camel_to_snake("HTMLParser") == "html_parser"

    def test_numeric_suffix(self) -> None:
        assert _camel_to_snake("version2Update") == "version2_update"


class TestConvertKeys:
    """Tests for _convert_keys recursive key conversion."""

    def test_flat_dict(self) -> None:
        data = {"qualityThreshold": 0.7, "requireHumanReview": True}
        result = _convert_keys(data)
        assert result == {"quality_threshold": 0.7, "require_human_review": True}

    def test_nested_dict(self) -> None:
        data = {"workers": {"skillEvaluator": {"qualityThreshold": 0.9}}}
        result = _convert_keys(data)
        assert result == {"workers": {"skill_evaluator": {"quality_threshold": 0.9}}}

    def test_list_of_dicts(self) -> None:
        data = {"items": [{"firstName": "a"}, {"firstName": "b"}]}
        result = _convert_keys(data)
        assert result == {"items": [{"first_name": "a"}, {"first_name": "b"}]}

    def test_scalar_passthrough(self) -> None:
        assert _convert_keys(42) == 42
        assert _convert_keys("hello") == "hello"
        assert _convert_keys(True) is True

    def test_empty_dict(self) -> None:
        assert _convert_keys({}) == {}

    def test_empty_list(self) -> None:
        assert _convert_keys([]) == []

    def test_deeply_nested(self) -> None:
        data = {"a": {"b": {"cKey": {"dValue": 1}}}}
        result = _convert_keys(data)
        assert result == {"a": {"b": {"c_key": {"d_value": 1}}}}

    def test_mixed_snake_and_camel(self) -> None:
        data = {"already_snake": 1, "camelCase": 2}
        result = _convert_keys(data)
        assert result == {"already_snake": 1, "camel_case": 2}


class TestConfigLoaderLoad:
    """Tests for ConfigLoader.load() with YAML file I/O."""

    @pytest.fixture()
    def tmp_config_dir(self, tmp_path: Path) -> Path:
        return tmp_path

    def _write_yaml(self, directory: Path, content: str, filename: str = "librarian.yaml") -> Path:
        path = directory / filename
        path.write_text(content, encoding="utf-8")
        return path

    def test_load_minimal_valid_yaml(self, tmp_config_dir: Path) -> None:
        config_path = self._write_yaml(tmp_config_dir, VALID_YAML_MINIMAL)
        loader = ConfigLoader(config_path=config_path, env_path=tmp_config_dir / ".env")
        config = loader.load()
        assert isinstance(config, LibrarianConfig)
        assert config.llms == []

    def test_load_full_valid_yaml(self, tmp_config_dir: Path) -> None:
        config_path = self._write_yaml(tmp_config_dir, VALID_YAML_FULL)
        loader = ConfigLoader(config_path=config_path, env_path=tmp_config_dir / ".env")
        config = loader.load()
        assert len(config.llms) == 1
        assert config.llms[0].name == "primary"
        assert config.llms[0].api_key == "sk-test-key"
        assert config.workers.skill_evaluator.quality_threshold == 0.85
        assert config.workers.skill_evaluator.require_human_review is True
        assert config.workers.skill_evaluator.categories == ["search", "analysis"]
        assert config.workers.skill_splitter.split_rule.max_lines == 500
        assert config.workers.skill_splitter.split_rule.min_lines == 50
        assert config.workers.tool_guardian.require_human_review is False
        assert config.api.port == 8080
        assert config.api.host == "127.0.0.1"
        assert config.database.path == "./data/test.db"
        assert config.logging.level == "DEBUG"
        assert config.logging.file == "./logs/test.log"
        assert config.skill_trigger_threshold == 5
        assert config.max_rejection_count == 2

    def test_load_file_not_found(self, tmp_config_dir: Path) -> None:
        loader = ConfigLoader(
            config_path=tmp_config_dir / "nonexistent.yaml",
            env_path=tmp_config_dir / ".env",
        )
        with pytest.raises(FileNotFoundError):
            loader.load()

    def test_load_invalid_yaml_syntax(self, tmp_config_dir: Path) -> None:
        config_path = self._write_yaml(tmp_config_dir, "{{invalid yaml: [")
        loader = ConfigLoader(config_path=config_path, env_path=tmp_config_dir / ".env")
        with pytest.raises(yaml.YAMLError):
            loader.load()

    def test_load_invalid_port_raises(self, tmp_config_dir: Path) -> None:
        yaml_content = "api:\n  port: 99999\n"
        config_path = self._write_yaml(tmp_config_dir, yaml_content)
        loader = ConfigLoader(config_path=config_path, env_path=tmp_config_dir / ".env")
        with pytest.raises(ValidationError):
            loader.load()

    def test_load_invalid_quality_threshold_raises(self, tmp_config_dir: Path) -> None:
        yaml_content = "workers:\n  skillEvaluator:\n    qualityThreshold: 5.0\n"
        config_path = self._write_yaml(tmp_config_dir, yaml_content)
        loader = ConfigLoader(config_path=config_path, env_path=tmp_config_dir / ".env")
        with pytest.raises(ValidationError):
            loader.load()

    def test_load_invalid_split_rule_raises(self, tmp_config_dir: Path) -> None:
        yaml_content = "workers:\n  skillSplitter:\n    splitRule:\n      maxLines: 10\n      minLines: 100\n"
        config_path = self._write_yaml(tmp_config_dir, yaml_content)
        loader = ConfigLoader(config_path=config_path, env_path=tmp_config_dir / ".env")
        with pytest.raises(ValidationError):
            loader.load()

    def test_load_invalid_llm_ref_raises(self, tmp_config_dir: Path) -> None:
        yaml_content = "workers:\n  skillEvaluator:\n    llm: nonexistent\n"
        config_path = self._write_yaml(tmp_config_dir, yaml_content)
        loader = ConfigLoader(config_path=config_path, env_path=tmp_config_dir / ".env")
        with pytest.raises(ValidationError, match="Worker references LLM"):
            loader.load()

    def test_load_with_env_file(self, tmp_config_dir: Path) -> None:
        env_path = tmp_config_dir / ".env"
        env_path.write_text("MODEL=env-model\nAPI_KEY=env-key\n", encoding="utf-8")
        yaml_content = "llms:\n  - name: test\n"
        config_path = self._write_yaml(tmp_config_dir, yaml_content)
        loader = ConfigLoader(config_path=config_path, env_path=env_path)
        config = loader.load()
        assert config.llms[0].model == "env-model"
        assert config.llms[0].api_key == "env-key"

    def test_get_config_before_load_raises(self, tmp_config_dir: Path) -> None:
        loader = ConfigLoader(
            config_path=tmp_config_dir / "librarian.yaml",
            env_path=tmp_config_dir / ".env",
        )
        with pytest.raises(RuntimeError, match="Configuration not loaded"):
            loader.get_config()

    def test_get_config_after_load(self, tmp_config_dir: Path) -> None:
        config_path = self._write_yaml(tmp_config_dir, VALID_YAML_MINIMAL)
        loader = ConfigLoader(config_path=config_path, env_path=tmp_config_dir / ".env")
        loaded = loader.load()
        retrieved = loader.get_config()
        assert retrieved is loaded


class TestConfigLoaderCallbacks:
    """Tests for ConfigLoader callback registration and unsubscription."""

    @pytest.fixture()
    def loader_with_config(self, tmp_path: Path) -> ConfigLoader:
        config_path = tmp_path / "librarian.yaml"
        config_path.write_text("{}", encoding="utf-8")
        loader = ConfigLoader(config_path=config_path, env_path=tmp_path / ".env")
        loader.load()
        return loader

    def test_register_callback(self, loader_with_config: ConfigLoader) -> None:
        callback = MagicMock()
        unsub = loader_with_config.on_change(callback)
        assert callback in loader_with_config._callbacks
        unsub()

    def test_unsubscribe_removes_callback(self, loader_with_config: ConfigLoader) -> None:
        callback = MagicMock()
        unsub = loader_with_config.on_change(callback)
        unsub()
        assert callback not in loader_with_config._callbacks

    def test_unsubscribe_idempotent(self, loader_with_config: ConfigLoader) -> None:
        callback = MagicMock()
        unsub = loader_with_config.on_change(callback)
        unsub()
        unsub()
        assert callback not in loader_with_config._callbacks

    def test_multiple_callbacks(self, loader_with_config: ConfigLoader) -> None:
        cb1 = MagicMock()
        cb2 = MagicMock()
        unsub1 = loader_with_config.on_change(cb1)
        loader_with_config.on_change(cb2)
        assert len(loader_with_config._callbacks) == 2
        unsub1()
        assert cb1 not in loader_with_config._callbacks
        assert cb2 in loader_with_config._callbacks


class TestConfigLoaderHotReload:
    """Tests for ConfigLoader hot-reload via watchdog file change handling."""

    @pytest.fixture()
    def loader_with_config(self, tmp_path: Path) -> ConfigLoader:
        config_path = tmp_path / "librarian.yaml"
        config_path.write_text("{}", encoding="utf-8")
        loader = ConfigLoader(config_path=config_path, env_path=tmp_path / ".env")
        loader.load()
        return loader

    def test_handle_file_change_triggers_callbacks(self, loader_with_config: ConfigLoader) -> None:
        callback = MagicMock()
        loader_with_config.on_change(callback)
        loader_with_config._handle_file_change()
        callback.assert_called_once()
        new_config = callback.call_args[0][0]
        assert isinstance(new_config, LibrarianConfig)

    def test_handle_file_change_reload_failure_no_callback(self, loader_with_config: ConfigLoader) -> None:
        callback = MagicMock()
        loader_with_config.on_change(callback)
        loader_with_config.config_path.write_text("invalid: {yaml: [", encoding="utf-8")
        loader_with_config._handle_file_change()
        callback.assert_not_called()

    def test_start_watching_creates_observer(self, loader_with_config: ConfigLoader) -> None:
        loader_with_config.start_watching()
        try:
            assert loader_with_config._observer is not None
            assert loader_with_config._observer.is_alive()
        finally:
            loader_with_config.stop_watching()

    def test_stop_watching_stops_observer(self, loader_with_config: ConfigLoader) -> None:
        loader_with_config.start_watching()
        loader_with_config.stop_watching()
        assert loader_with_config._observer is None

    def test_double_start_watching_raises(self, loader_with_config: ConfigLoader) -> None:
        loader_with_config.start_watching()
        try:
            with pytest.raises(RuntimeError, match="already running"):
                loader_with_config.start_watching()
        finally:
            loader_with_config.stop_watching()

    def test_stop_watching_without_start(self, loader_with_config: ConfigLoader) -> None:
        loader_with_config.stop_watching()


class TestConfigurable:
    """Tests for Configurable abstract base class behavior."""

    class _ConcreteConfigurable(Configurable):
        """Concrete implementation for testing."""

        def __init__(self) -> None:
            super().__init__()
            self.last_config: Optional[LibrarianConfig] = None

        def load_config(self, config: LibrarianConfig) -> None:
            self.last_config = config
            self._config_pending = True

    @pytest.fixture()
    def configurable(self) -> _ConcreteConfigurable:
        return self._ConcreteConfigurable()

    def test_initial_pending_is_false(self, configurable: _ConcreteConfigurable) -> None:
        assert configurable.has_pending_config() is False

    def test_load_config_sets_pending(self, configurable: _ConcreteConfigurable) -> None:
        config = LibrarianConfig()
        configurable.load_config(config)
        assert configurable.has_pending_config() is True
        assert configurable.last_config is config

    def test_mark_config_applied_clears_pending(self, configurable: _ConcreteConfigurable) -> None:
        config = LibrarianConfig()
        configurable.load_config(config)
        assert configurable.has_pending_config() is True
        configurable.mark_config_applied()
        assert configurable.has_pending_config() is False

    def test_cannot_instantiate_abstract(self) -> None:
        with pytest.raises(TypeError):
            Configurable()

    def test_pending_flag_cycle(self, configurable: _ConcreteConfigurable) -> None:
        assert configurable.has_pending_config() is False
        configurable.load_config(LibrarianConfig())
        assert configurable.has_pending_config() is True
        configurable.mark_config_applied()
        assert configurable.has_pending_config() is False
        configurable.load_config(LibrarianConfig())
        assert configurable.has_pending_config() is True
