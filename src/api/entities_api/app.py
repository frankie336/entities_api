import os
import time

from fastapi import FastAPI
from projectdavid_common import UtilsInterface
from sqlalchemy import create_engine, text

# Assuming the refactoring script was run, these imports are now correct
from src.api.entities_api.models.models import Base
from src.api.entities_api.routers import api_router

# --- Setup ---
logging_utility = UtilsInterface.LoggingUtility()

# --- Database Configuration ---
DATABASE_URL = os.getenv("DATABASE_URL")
SPECIAL_DB_URL = os.getenv("SPECIAL_DB_URL")

# Main DB Engine
engine = create_engine(
    DATABASE_URL,
    echo=True,
    pool_size=20,
    max_overflow=40,
    pool_timeout=30,
    pool_recycle=280,
)

# Create the special engine ONLY if the URL is provided. Otherwise, it's None.
special_engine = (
    create_engine(
        SPECIAL_DB_URL,
        echo=True,
        pool_size=10,
        max_overflow=20,
        pool_timeout=30,
        pool_recycle=280,
    )
    if SPECIAL_DB_URL
    else None
)


# --- Wait Logic ---
def _wait_for_engine(engine_to_check, db_name, logger, retries=30, delay=3):
    """A helper function to wait for a single database engine to be ready."""
    if not engine_to_check:
        logger.info(f"Database '{db_name}' is not configured, skipping wait.")
        return

    logger.info(f"Waiting for database '{db_name}' to be available...")
    for i in range(retries):
        try:
            with engine_to_check.connect() as connection:
                connection.execute(text("SELECT 1"))
            logger.info(f"✅ Database '{db_name}' is connected!")
            return
        except Exception as e:  # Catch a broader exception for robustness
            logger.warning(
                f"Attempt {i + 1}/{retries}: DB '{db_name}' not ready. Error: {e}"
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
    """Waits for all configured databases to be ready before proceeding."""
    if not DATABASE_URL:
        logging_utility.error("FATAL: DATABASE_URL environment variable is not set.")
        raise ValueError("DATABASE_URL not set")

    _wait_for_engine(engine, "Main DB", logging_utility)

    # This check now correctly handles the case where special_engine is None
    if special_engine:
        _wait_for_engine(special_engine, "Special DB", logging_utility)


# --- Application Startup ---
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
        # This inline migration might be better handled by Alembic, but we'll leave it for now.
        try:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE messages MODIFY COLUMN content TEXT"))
        except Exception:
            # Fails silently if the column is already the right type, which is fine.
            pass
    return app


app = create_app()
