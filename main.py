from __future__ import annotations

import logging
import sys
from pathlib import Path

import uvicorn
from dotenv import load_dotenv

from src.api.app import create_app
from src.config.loader import ConfigLoader
from src.config.schema import LibrarianConfig
from src.db.manager import DatabaseManager
from src.git_manager.manager import GitManager
from src.git_manager.tmp_manager import TmpManager
from src.workflows.human_review import HumanReviewManager
from src.workflows.scheduler import SchedulerManager


def setup_logging(config: LibrarianConfig) -> None:
    """Configure logging based on the Librarian configuration.

    Args:
        config: The Librarian configuration with logging settings.
    """
    log_path = Path(config.logging.file)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    logging.basicConfig(
        level=getattr(logging, config.logging.level, logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(config.logging.file, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )


def main() -> None:
    """Main entry point for the Librarian Skills management system."""
    load_dotenv()

    config_loader = ConfigLoader(
        config_path="librarian.yaml",
        env_path=".env",
    )
    config = config_loader.load()

    setup_logging(config)

    logger = logging.getLogger(__name__)
    logger.info("Librarian starting up")

    base_dir = Path(".")
    skills_dir = base_dir / "skills"
    tools_dir = base_dir / "tools"
    skills_dir.mkdir(exist_ok=True)
    tools_dir.mkdir(exist_ok=True)

    db = DatabaseManager(config.database.path)
    db.initialize()
    logger.info("Database initialized at %s", config.database.path)

    git_manager = GitManager(base_dir)
    if not git_manager.is_repo():
        git_manager.init()
        logger.info("Git repository initialized")
    else:
        logger.info("Git repository found")

    tmp_manager = TmpManager(base_dir)
    human_review_manager = HumanReviewManager()

    shared_state: dict = {
        "db": db,
        "skills_dir": str(skills_dir),
        "tools_dir": str(tools_dir),
        "git_manager": git_manager,
        "tmp_manager": tmp_manager,
    }

    scheduler = SchedulerManager(config)
    scheduler.start(shared_state)
    logger.info("Scheduler started")

    config_loader.start_watching()
    logger.info("Config hot-reload watching started")

    app = create_app(
        config=config,
        config_loader=config_loader,
        db=db,
        git_manager=git_manager,
        tmp_manager=tmp_manager,
        human_review_manager=human_review_manager,
        skills_dir=skills_dir,
        tools_dir=tools_dir,
    )

    logger.info("Starting API server on %s:%s", config.api.host, config.api.port)
    try:
        uvicorn.run(
            app,
            host=config.api.host,
            port=config.api.port,
            log_level=config.logging.level.lower(),
        )
    except KeyboardInterrupt:
        logger.info("Shutting down")
    finally:
        scheduler.stop()
        config_loader.stop_watching()
        db.close()
        logger.info("Librarian shut down complete")


if __name__ == "__main__":
    main()
