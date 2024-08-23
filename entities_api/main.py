import os
from fastapi import FastAPI
from sqlalchemy import create_engine, text, inspect
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from models.models import Base
from entities_api.routers import router as api_router
from entities_api.services.loggin_service import LoggingUtility
from entities_api.services.run_monitor_service import RunMonitorService
from db.database import SessionLocal

# Initialize the logging utility
logging_utility = LoggingUtility()

# Update this with your actual database URL
DATABASE_URL = os.getenv("DATABASE_URL")

engine = create_engine(DATABASE_URL)

def drop_constraints():
    logging_utility.info("Dropping constraints")
    inspector = inspect(engine)
    with engine.connect() as connection:
        for table_name in inspector.get_table_names():
            foreign_keys = inspector.get_foreign_keys(table_name)
            for fk in foreign_keys:
                fk_name = fk['name']
                logging_utility.info("Dropping foreign key %s from table %s", fk_name, table_name)
                connection.execute(text(f"ALTER TABLE {table_name} DROP FOREIGN KEY {fk_name}"))

def drop_tables():
    logging_utility.info("Dropping all tables")
    Base.metadata.drop_all(bind=engine)

def create_tables():
    logging_utility.info("Creating all tables")
    Base.metadata.create_all(bind=engine)

def update_messages_content_column():
    logging_utility.info("Updating messages.content column to TEXT")
    with engine.connect() as connection:
        try:
            connection.execute(text("ALTER TABLE messages MODIFY COLUMN content TEXT;"))
            logging_utility.info("Successfully updated messages.content column to TEXT")
        except Exception as e:
            logging_utility.error(f"Error updating messages.content column: {str(e)}")

def run_monitor_job():
    db = SessionLocal()
    try:
        monitor = RunMonitorService(db)
        monitor.check_and_update_runs()
    finally:
        db.close()

def create_app(init_db=True):
    logging_utility.info("Creating FastAPI app")
    app = FastAPI()

    # Include API routers
    app.include_router(api_router, prefix="/v1")

    @app.get("/")
    def read_root():
        logging_utility.info("Root endpoint accessed")
        return {"message": "Welcome to the API!"}

    if init_db:
        logging_utility.info("Initializing database")
        # Create database tables
        create_tables()
        # Update messages.content column
        update_messages_content_column()

    @app.on_event("startup")
    def start_scheduler():
        scheduler = BackgroundScheduler()
        scheduler.add_job(
            run_monitor_job,
            IntervalTrigger(minutes=5),
            id="run_monitor_job",
            name="Check and update expired runs",
            replace_existing=True,
        )
        scheduler.start()

    return app


app = create_app()


def create_test_app():
    logging_utility.info("Creating test app")
    # Drop constraints, drop tables, and recreate tables for a clean test environment
    drop_constraints()
    drop_tables()
    create_tables()
    update_messages_content_column()
    return create_app(init_db=False)