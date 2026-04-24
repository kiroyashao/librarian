from __future__ import annotations

from unittest.mock import MagicMock, patch

from src.config.schema import LibrarianConfig
from src.workflows.scheduler import SchedulerManager


class TestSchedulerManager:
    def test_start_disabled(self) -> None:
        config = LibrarianConfig()
        config.cronjobs.enabled = False
        mgr = SchedulerManager(config)
        mgr.start({})
        assert not mgr.scheduler.running

    def test_start_stop(self) -> None:
        config = LibrarianConfig()
        config.cronjobs.enabled = True
        config.cronjobs.jobs = {}
        mgr = SchedulerManager(config)
        mgr.start({})
        assert mgr.scheduler.running
        mgr.stop()
        assert not mgr.scheduler.running

    def test_stop_when_not_running(self) -> None:
        config = LibrarianConfig()
        mgr = SchedulerManager(config)
        mgr.stop()
