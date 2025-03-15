from fastapi import FastAPI
from src.sandbox_api.routers import api_router
from src.sandbox_api.services.logging_service import LoggingUtility

# Initialize the logging utility
logging_utility = LoggingUtility()

def create_app(init_db=True):
    logging_utility.info("Creating FastAPI app")
    app = FastAPI()

    # Include routers
    app.include_router(api_router, prefix="/ws")  # Prefix applied here

    @app.get("/")
    def read_root():
        logging_utility.info("Root endpoint accessed")
        return {"message": "Welcome to the API!"}

    return app

app = create_app()