# entities_api/main.py

import os
from fastapi import FastAPI
from sqlalchemy import create_engine, text, inspect
from entities_api.models.models import Base
from entities_api.routers import api_router  # Importing the combined API router
from entities_api.services.initialization_service import AssistantInitializationService
from entities_api.services.logging_service import LoggingUtility

# Initialize the logging utility
logging_utility = LoggingUtility()

# Update this with your actual database URL
DATABASE_URL = os.getenv("DATABASE_URL")
engine = create_engine(DATABASE_URL, echo=True)

# Secondary Engine for a Specific Use Case
SPECIAL_DB_URL = os.getenv("SPECIAL_DB_URL")  # Define this in your environment
special_engine = create_engine(SPECIAL_DB_URL, echo=True) if SPECIAL_DB_URL else None



def drop_constraints():
    logging_utility.info("Dropping constraints")
    inspector = inspect(engine)
    with engine.connect() as connection:
        for table_name in inspector.get_table_names():
            foreign_keys = inspector.get_foreign_keys(table_name)
            for fk in foreign_keys:
                connection.execute(text(f"ALTER TABLE {table_name} DROP FOREIGN KEY {fk['name']}"))

def drop_tables():
    logging_utility.info("Dropping all tables")
    Base.metadata.drop_all(bind=engine)

def create_tables():
    logging_utility.info("Creating all tables")
    Base.metadata.create_all(bind=engine)

def update_messages_content_column():
    logging_utility.info("Updating messages.content column to TEXT")
    with engine.connect() as connection:
        connection.execute(text("ALTER TABLE messages MODIFY COLUMN content TEXT"))

def create_app(init_db=True):
    logging_utility.info("Creating FastAPI app")
    app = FastAPI()

    # Include API routers
    app.include_router(api_router, prefix="/v1")  # All routes under /v1

    @app.get("/")
    def read_root():
        logging_utility.info("Root endpoint accessed")
        return {"message": "Welcome to the API!"}

    if init_db:
        logging_utility.info("Initializing database")
        create_tables()
        update_messages_content_column()

    return app

app = create_app()

def create_test_app():
    logging_utility.info("Creating test app")
    drop_constraints()
    drop_tables()
    create_tables()
    update_messages_content_column()
    return create_app(init_db=False)
