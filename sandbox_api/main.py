from fastapi import FastAPI
from sandbox_api.routers import ws_router
from sandbox_api.services.logging_service import LoggingUtility

# Initialize the logging utility
logging_utility = LoggingUtility()

def create_app():
    logging_utility.info("Creating FastAPI app")
    app = FastAPI()

    app.include_router(ws_router, prefix="/ws")

    @app.get("/")
    def read_root():
        logging_utility.info("Root endpoint accessed")
        return {"message": "Welcome to the API!"}

    return app

app = create_app()