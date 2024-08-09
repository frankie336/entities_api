from fastapi import HTTPException

from models.models import Run  # Ensure Run is imported
from pydantic import parse_obj_as
from services.identifier_service import IdentifierService
from api.v1.schemas import Tool
from sqlalchemy.orm import Session
from typing import List
import time


class RunService:
    def __init__(self, db: Session):
        self.db = db

    def create_run(self, run_data):
        run = Run(
            id=IdentifierService.generate_run_id(),
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
            status=run_data.status,
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

        run.status = new_status
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
                tools=parse_obj_as(List[Tool], run.tools),
                truncation_strategy=run.truncation_strategy,
                usage=run.usage,
                temperature=run.temperature,
                top_p=run.top_p,
                tool_resources=run.tool_resources
            )
            return run_data
        return None
