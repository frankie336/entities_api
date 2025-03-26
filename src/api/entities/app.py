#!/usr/bin/env python
import os
from fastapi import FastAPI
from sqlalchemy import create_engine, text

from entities.models.models import Base
from entities.routers import api_router  # This central router includes all decoupled routers
from entities.services.logging_service import LoggingUtility

# Initialize the logging utility
logging_utility = LoggingUtility()

# Database configuration
DATABASE_URL = os.getenv("DATABASE_URL")
engine = create_engine(DATABASE_URL, echo=True)

SPECIAL_DB_URL = os.getenv("SPECIAL_DB_URL")
special_engine = create_engine(SPECIAL_DB_URL, echo=True) if SPECIAL_DB_URL else None

def create_app(init_db=True):
    logging_utility.info("Creating FastAPI app")
    app = FastAPI(
        title="Entities",
        description="API for AI inference",
        version="1.0.0",
        docs_url="/mydocs",       # Change Swagger UI URL
        redoc_url="/altredoc",    # Change ReDoc URL
        openapi_url="/openapi.json"  # Change OpenAPI JSON URL
    )

    # Include the central API router with all decoupled routers under the /v1 prefix
    app.include_router(api_router, prefix="/v1")

    @app.get("/")
    def read_root():
        logging_utility.info("Root endpoint accessed")
        return {"message": "Welcome to the API!"}

    if init_db:
        logging_utility.info("Initializing database")
        Base.metadata.create_all(bind=engine)
        with engine.connect() as connection:
            # This alters the 'content' column of the messages table; adjust as needed
            connection.execute(text("ALTER TABLE messages MODIFY COLUMN content TEXT"))

    return app

app = create_app()
