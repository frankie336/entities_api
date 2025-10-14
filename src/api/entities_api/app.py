import os
import time
from pathlib import Path

from fastapi import FastAPI
from projectdavid_common import UtilsInterface
from sqlalchemy import create_engine, text

from src.api.entities_api.models.models import Base
from src.api.entities_api.routers import api_router

logging_utility = UtilsInterface.LoggingUtility()

# ─────────────────────────────────────────────────────────────
# Raw envs (do not touch; other scripts may rely on these)
# ─────────────────────────────────────────────────────────────
DATABASE_URL = os.getenv("DATABASE_URL")
SPECIAL_DB_URL = os.getenv("SPECIAL_DB_URL")  # keep this exactly as provided
WAIT_FOR_SPECIAL_DB = os.getenv("WAIT_FOR_SPECIAL_DB", "0") in ("1", "true", "True")


# ─────────────────────────────────────────────────────────────
# Container-aware resolver (runtime only)
# ─────────────────────────────────────────────────────────────
def running_in_docker() -> bool:
    """Detect if running inside a Docker container."""
    return os.getenv("RUNNING_IN_DOCKER") == "1" or Path("/.dockerenv").exists()


def resolve_special_db_runtime_url(special_raw: str | None) -> str | None:
    """
    Inside Docker: reuse DATABASE_URL so Special DB uses the container-safe DSN.
    Outside Docker: keep the original SPECIAL_DB_URL for scripts that need it.
    """
    if running_in_docker():
        logging_utility.info(
            "[Special DB] Using DATABASE_URL for runtime connection inside Docker"
        )
        return DATABASE_URL
    return special_raw or None


SPECIAL_DB_RUNTIME_URL = resolve_special_db_runtime_url(SPECIAL_DB_URL)


# ─────────────────────────────────────────────────────────────
# Engines
# ─────────────────────────────────────────────────────────────
engine = create_engine(
    DATABASE_URL,
    echo=True,
    pool_size=20,
    max_overflow=40,
    pool_timeout=30,
    pool_recycle=280,
)

special_engine = (
    create_engine(
        SPECIAL_DB_RUNTIME_URL,
        echo=True,
        pool_size=10,
        max_overflow=20,
        pool_timeout=30,
        pool_recycle=280,
    )
    if SPECIAL_DB_RUNTIME_URL
    else None
)


# ─────────────────────────────────────────────────────────────
# Wait logic
# ─────────────────────────────────────────────────────────────
def _wait_for_engine(engine_to_check, db_name, logger, retries=30, delay=3):
    if not engine_to_check:
        logger.info(f"Database '{db_name}' is not configured, skipping wait.")
        return

    host_hint = str(engine_to_check.url).split("@")[-1]
    logger.info(f"Waiting for database '{db_name}' to be available... [{host_hint}]")

    for i in range(retries):
        try:
            with engine_to_check.connect() as connection:
                connection.execute(text("SELECT 1"))
            logger.info(f"✅ Database '{db_name}' is connected!")
            return
        except Exception as e:
            logger.warning(
                f"Attempt {i+1}/{retries}: DB '{db_name}' not ready. Error: {e}"
            )
            if i < retries - 1:
                logger.info(f"Retrying in {delay} seconds...")
                time.sleep(delay)
            else:
                logger.error(
                    f"Could not connect to database '{db_name}' after {retries} attempts."
                )
                raise


def wait_for_databases():
    if not DATABASE_URL:
        logging_utility.error("FATAL: DATABASE_URL environment variable is not set.")
        raise ValueError("DATABASE_URL not set")

    _wait_for_engine(engine, "Main DB", logging_utility)

    # Only wait for Special DB if we both have a runtime URL and the flag is on
    if special_engine and WAIT_FOR_SPECIAL_DB:
        _wait_for_engine(special_engine, "Special DB", logging_utility)
    elif SPECIAL_DB_URL and not WAIT_FOR_SPECIAL_DB:
        logging_utility.info(
            "Special DB URL is set, but WAIT_FOR_SPECIAL_DB=0; skipping wait."
        )


# ─────────────────────────────────────────────────────────────
# Application startup
# ─────────────────────────────────────────────────────────────
wait_for_databases()


def create_app(init_db: bool = True) -> FastAPI:
    logging_utility.info("Creating FastAPI app")
    app = FastAPI(
        title="Entities",
        description="API for AI inference",
        version="1.0.0",
        docs_url="/mydocs",
        redoc_url="/altredoc",
        openapi_url="/openapi.json",
    )

    app.include_router(api_router, prefix="/v1")

    @app.get("/")
    def read_root():
        logging_utility.info("Root endpoint accessed")
        return {"message": "Welcome to the API!"}

    if init_db:
        logging_utility.info("Initializing database schema...")
        Base.metadata.create_all(bind=engine)
        try:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE messages MODIFY COLUMN content TEXT"))
        except Exception:
            # Ignore errors if column already has correct type
            pass

    return app


app = create_app()
