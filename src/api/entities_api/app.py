from fastapi import FastAPI
from projectdavid_common import UtilsInterface
from sqlalchemy import text

# --- FIX APPLIED HERE ---
# Import the necessary objects from our new central database file and models.
from src.api.entities_api.db.database import engine, wait_for_databases
from src.api.entities_api.models.models import Base
from src.api.entities_api.routers import api_router

logging_utility = UtilsInterface.LoggingUtility()

# ─────────────────────────────────────────────────────────────
# Application startup
# ─────────────────────────────────────────────────────────────

# 1. Wait for the database(s) to be ready before proceeding.
# This function now lives in and is imported from database.py
wait_for_databases()


# 2. Define the app creation factory
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

    # This startup logic still uses the 'engine' but now it's imported
    # from the single source of truth.
    if init_db:
        logging_utility.info("Initializing database schema...")
        Base.metadata.create_all(bind=engine)
        try:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE messages MODIFY COLUMN content TEXT"))
        except Exception:
            pass

    return app


# 3. Create the final app instance
app = create_app()
