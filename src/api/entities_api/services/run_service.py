import time
from typing import List
from entities_common import ValidationInterface, UtilsInterface
from fastapi import HTTPException
from pydantic import parse_obj_as
from sqlalchemy.orm import Session
from entities_api.models.models import Run, StatusEnum  # Ensure Run is imported
from entities_api.services.logging_service import LoggingUtility

validator = ValidationInterface()

class RunService:
    def __init__(self, db: Session):

        self.db = db
        self.logger = LoggingUtility()

    def create_run(self, run_data):
        run = Run(
            id=UtilsInterface.IdentifierService.generate_run_id(),
            assistant_id=run_data.assistant_id,
            cancelled_at=run_data.cancelled_at,
            completed_at=run_data.completed_at,
            created_at=int(time.time()),
            expires_at=run_data.expires_at,
            failed_at=run_data.failed_at,
            incomplete_details=run_data.incomplete_details,
            instructions=run_data.instructions,
            last_error=run_data.last_error,
            max_completion_tokens=run_data.max_completion_tokens,
            max_prompt_tokens=run_data.max_prompt_tokens,
            meta_data=run_data.meta_data,
            model=run_data.model,
            object=run_data.object,
            parallel_tool_calls=run_data.parallel_tool_calls,
            required_action=run_data.required_action,
            response_format=run_data.response_format,
            started_at=run_data.started_at,
            status="queued",  # Set the initial status to "queued"
            thread_id=run_data.thread_id,
            tool_choice=run_data.tool_choice,
            tools=[tool.dict() for tool in run_data.tools],
            truncation_strategy=run_data.truncation_strategy,
            usage=run_data.usage,
            temperature=run_data.temperature,
            top_p=run_data.top_p,
            tool_resources=run_data.tool_resources
        )
        self.db.add(run)
        self.db.commit()
        self.db.refresh(run)
        return run


    def update_run_status(self, run_id: str, new_status: str):
        run = self.db.query(Run).filter(Run.id == run_id).first()
        if not run:
            raise HTTPException(status_code=404, detail="Run not found")

        try:
            # Convert the string to the StatusEnum type
            run.status = validator.StatusEnum(new_status)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid status: {new_status}")

        self.db.commit()
        self.db.refresh(run)
        return run

    def get_run(self, run_id):
        run = self.db.query(Run).filter(Run.id == run_id).first()
        if run:
            run_data = Run(
                id=run.id,
                assistant_id=run.assistant_id,
                cancelled_at=run.cancelled_at,
                completed_at=run.completed_at,
                created_at=run.created_at,
                expires_at=run.expires_at,
                failed_at=run.failed_at,
                incomplete_details=run.incomplete_details,
                instructions=run.instructions,
                last_error=run.last_error,
                max_completion_tokens=run.max_completion_tokens,
                max_prompt_tokens=run.max_prompt_tokens,
                meta_data=run.meta_data,
                model=run.model,
                object=run.object,
                parallel_tool_calls=run.parallel_tool_calls,
                required_action=run.required_action,
                response_format=run.response_format,
                started_at=run.started_at,
                status=run.status,
                thread_id=run.thread_id,
                tool_choice=run.tool_choice,
                tools=parse_obj_as(List[validator.Tool], run.tools),
                truncation_strategy=run.truncation_strategy,
                usage=run.usage,
                temperature=run.temperature,
                top_p=run.top_p,
                tool_resources=run.tool_resources
            )
            return run_data
        return None

    def cancel_run(self, run_id: str):
        self.logger.info("Attempting to cancel run with ID: %s", run_id)

        try:
            # Fetch the run object from the database
            run = self.db.query(Run).filter(Run.id == run_id).first()
            if not run:
                self.logger.error("Run with ID %s not found", run_id)
                raise HTTPException(status_code=404, detail="Run not found")

            self.logger.info("Run with ID %s found. Current status: %s", run_id, run.status)

            # Check if the run can be cancelled
            if run.status in [StatusEnum.completed, StatusEnum.cancelled]:
                self.logger.warning("Cannot cancel run with ID %s because it is already %s", run_id, run.status)
                raise HTTPException(status_code=400, detail="Cannot cancel a completed or already cancelled run")

            # Set the status to 'cancelling'
            self.logger.info("Setting status to 'cancelling' for run ID %s", run_id)
            run.status = StatusEnum.cancelling
            self.db.commit()
            self.db.refresh(run)
            self.logger.info("Run ID %s status set to 'cancelling'", run_id)

            # Now, set the status to 'cancelled'
            self.logger.info("Setting status to 'cancelled' for run ID %s", run_id)
            run.status = StatusEnum.cancelled

            # run.cancelled_at = datetime.utcnow()  # Use datetime object instead of Unix timestamp

            self.db.commit()
            self.db.refresh(run)
            self.logger.info("Run ID %s successfully cancelled", run_id)

            return run

        except Exception as e:
            self.logger.error("Failed to cancel run with ID %s. Error: %s", run_id, str(e))
            self.db.rollback()  # Rollback in case of error
            raise HTTPException(status_code=500, detail=f"Failed to cancel run: {str(e)}")


