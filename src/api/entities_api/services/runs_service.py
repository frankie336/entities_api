import time
from typing import List, Optional
from fastapi import HTTPException
from pydantic import parse_obj_as
from sqlalchemy.orm import Session

from projectdavid_common import UtilsInterface, ValidationInterface
from projectdavid_common.utilities.logging_service import LoggingUtility

from entities_api.models.models import Run, StatusEnum

# --------------------------------------------------------------------------- #
#  Pydantic validator shortcut
# --------------------------------------------------------------------------- #
validator = ValidationInterface()

# --------------------------------------------------------------------------- #
#  Service
# --------------------------------------------------------------------------- #
class RunService:
    def __init__(self, db: Session) -> None:
        self.db: Session = db
        self.logger = LoggingUtility()

    # ───────────────────────────────────────────────────────────────────── #
    #  CREATE
    # ───────────────────────────────────────────────────────────────────── #
    def create_run(
        self,
        run_data: validator.RunCreate,
        *,
        user_id: str,
    ) -> Run:
        """
        Persist a new run tied to the given user_id.
        The caller must already be authenticated and provide the user_id
        (taken from the API‑key or session).
        """
        new_run = Run(
            id=UtilsInterface.IdentifierService.generate_run_id(),
            user_id=user_id,  # Required for all runs
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
            status=StatusEnum.queued,  # Set initial state
            thread_id=run_data.thread_id,
            tool_choice=run_data.tool_choice,
            tools=[tool.dict() for tool in run_data.tools],
            truncation_strategy=run_data.truncation_strategy,
            usage=run_data.usage,
            temperature=run_data.temperature,
            top_p=run_data.top_p,
            tool_resources=run_data.tool_resources,
        )

        self.logger.info(
            "Persisting run (user_id=%s, assistant_id=%s, thread_id=%s)",
            user_id, run_data.assistant_id, run_data.thread_id
        )

        self.db.add(new_run)
        self.db.commit()
        self.db.refresh(new_run)

        self.logger.info("Run created successfully: %s", new_run.id)

        return new_run

    # ───────────────────────────────────────────────────────────────────── #
    #  UPDATE STATUS
    # ───────────────────────────────────────────────────────────────────── #
    def update_run_status(self, run_id: str, new_status: str) -> Run:
        run: Optional[Run] = (
            self.db.query(Run).filter(Run.id == run_id).first()
        )
        if not run:
            raise HTTPException(status_code=404, detail="Run not found")

        try:
            run.status = StatusEnum(new_status)
        except ValueError:
            raise HTTPException(
                status_code=400, detail=f"Invalid status: {new_status}"
            )

        self.db.commit()
        self.db.refresh(run)
        return run

    # ───────────────────────────────────────────────────────────────────── #
    #  READ
    # ───────────────────────────────────────────────────────────────────── #
    def get_run(self, run_id: str) -> Optional[validator.RunReadDetailed]:
        run: Optional[Run] = (
            self.db.query(Run).filter(Run.id == run_id).first()
        )
        if not run:
            return None

        # Map SQLAlchemy → Pydantic
        return validator.RunReadDetailed(
            id=run.id,
            user_id=run.user_id,                         # ← NEW
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
            status=run.status.value
            if isinstance(run.status, StatusEnum)
            else run.status,
            thread_id=run.thread_id,
            tool_choice=run.tool_choice,
            tools=parse_obj_as(List[validator.ToolRead], run.tools),
            truncation_strategy=run.truncation_strategy,
            usage=run.usage,
            temperature=run.temperature,
            top_p=run.top_p,
            tool_resources=run.tool_resources,
            actions=[],  # lazy‑loaded elsewhere if needed
        )

    # ───────────────────────────────────────────────────────────────────── #
    #  CANCEL
    # ───────────────────────────────────────────────────────────────────── #
    def cancel_run(self, run_id: str) -> Run:
        self.logger.info("Attempting to cancel run %s", run_id)
        run: Optional[Run] = (
            self.db.query(Run).filter(Run.id == run_id).first()
        )
        if not run:
            self.logger.error("Run %s not found", run_id)
            raise HTTPException(status_code=404, detail="Run not found")

        if run.status in {StatusEnum.completed, StatusEnum.cancelled}:
            raise HTTPException(
                status_code=400,
                detail="Cannot cancel a completed or already cancelled run",
            )

        # mark cancelling → cancelled
        run.status = StatusEnum.cancelling
        self.db.commit()
        run.status = StatusEnum.cancelled
        self.db.commit()
        self.db.refresh(run)

        self.logger.info("Run %s successfully cancelled", run_id)
        return run
