from fastapi import FastAPI
from sandbox.routers.v1 import v1_router
from sandbox.services.logging_service import LoggingUtility

logging_utility = LoggingUtility()


def create_app():
    app = FastAPI()
    app.include_router(v1_router, prefix="/ws")

    @app.get("/")
    def read_root():
        logging_utility.info("Root endpoint accessed")
        return {"message": "Welcome to the API!"}

    return app


app = create_app()


@app.on_event("startup")
async def startup_event():
    logging_utility.info("Starting FastAPI App")


@app.on_event("shutdown")
async def shutdown_event():
    logging_utility.info("Shutting down FastAPI App")
