from __future__ import annotations

import logging
from typing import Any

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from src.config.schema import LibrarianConfig
from src.workflows.workflows import Case2Workflow, Case3Workflow

logger = logging.getLogger(__name__)


class SchedulerManager:
    """Manages periodic cron jobs for cleanup and merge operations.

    Uses APScheduler to run Case2 (merge) and Case3 (cleanup) workflows
    on configurable cron schedules.

    Attributes:
        config: The Librarian configuration.
        scheduler: The APScheduler BackgroundScheduler instance.
        case2_workflow: The merge check workflow.
        case3_workflow: The cleanup check workflow.
    """

    def __init__(self, config: LibrarianConfig) -> None:
        """Initialize the SchedulerManager.

        Args:
            config: The Librarian configuration with cronjob settings.
        """
        self.config = config
        self.scheduler = BackgroundScheduler()
        self.case2_workflow = Case2Workflow(config)
        self.case3_workflow = Case3Workflow(config)

    def start(self, shared_state: dict[str, Any]) -> None:
        """Start the scheduler with configured cron jobs.

        Args:
            shared_state: Shared state dict passed to workflow executions.
        """
        if not self.config.cronjobs.enabled:
            logger.info("Cronjobs are disabled in configuration")
            return

        jobs = self.config.cronjobs.jobs

        if "cleaner" in jobs:
            trigger = CronTrigger.from_crontab(jobs["cleaner"].schedule)
            self.scheduler.add_job(
                self._run_cleanup,
                trigger=trigger,
                args=[shared_state],
                id="cleaner",
                name="Skill Cleanup Job",
            )
            logger.info("Scheduled cleaner job: %s", jobs["cleaner"].schedule)

        if "merger" in jobs:
            trigger = CronTrigger.from_crontab(jobs["merger"].schedule)
            self.scheduler.add_job(
                self._run_merge,
                trigger=trigger,
                args=[shared_state],
                id="merger",
                name="Skill Merge Job",
            )
            logger.info("Scheduled merger job: %s", jobs["merger"].schedule)

        self.scheduler.start()
        logger.info("Scheduler started")

    def stop(self) -> None:
        """Stop the scheduler gracefully."""
        if self.scheduler.running:
            self.scheduler.shutdown(wait=True)
            logger.info("Scheduler stopped")

    def _run_cleanup(self, shared_state: dict[str, Any]) -> None:
        """Execute the Case3 cleanup workflow.

        Args:
            shared_state: Shared state dict for the workflow.
        """
        try:
            graph = self.case3_workflow.build_graph()
            state = {**shared_state}
            result = graph.invoke(state)
            expired = result.get("expired_skills", [])
            logger.info("Cleanup completed, expired skills: %s", expired)
        except Exception:
            logger.exception("Cleanup job failed")

    def _run_merge(self, shared_state: dict[str, Any]) -> None:
        """Execute the Case2 merge workflow.

        Args:
            shared_state: Shared state dict for the workflow.
        """
        try:
            graph = self.case2_workflow.build_graph()
            state = {**shared_state}
            result = graph.invoke(state)
            groups = result.get("merge_groups", [])
            logger.info("Merge check completed, groups: %s", groups)
        except Exception:
            logger.exception("Merge job failed")
