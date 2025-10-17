import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from fastapi import HTTPException
from projectdavid_common import UtilsInterface, ValidationInterface
from projectdavid_common.utilities.logging_service import LoggingUtility
from projectdavid_common.validation import StatusEnum
from pydantic import parse_obj_as
from sqlalchemy.orm import Session

# --- FIX: Step 1 ---
# Import the SessionLocal factory.
from src.api.entities_api.db.database import SessionLocal
from src.api.entities_api.models.models import Run
from src.api.entities_api.models.models import Run as RunModel

validator = ValidationInterface()


class RunService:
    # --- FIX: Step 2 ---
    # The constructor no longer accepts or stores a database session.
    # The service is now stateless regarding its DB connection.
    def __init__(self) -> None:
        self.logger = LoggingUtility()

    # -----------------------------------
    # Helpers
    # -----------------------------------
    @staticmethod
    def _to_epoch(value: Optional[Any]) -> Optional[int]:
        """
        Normalize value to epoch seconds.
        Accepts: None, int, float, datetime, or stringified int.
        """
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return int(value)
        if isinstance(value, datetime):
            return int(value.timestamp())
        try:
            return int(str(value))
        except Exception:
            return None

    @staticmethod
    def _ensure_dict(value: Any) -> Dict[str, Any]:
        """
        Coerce JSON-ish values to dict; tolerates None / str (legacy) / other types.
        """
        if value is None:
            return {}
        if isinstance(value, dict):
            return value
        if isinstance(value, str):
            try:
                import json

                v = json.loads(value)
                return v if isinstance(v, dict) else {}
            except Exception:
                return {}
        # Anything else (list, number, etc.) → {}
        return {}

    # --- FIX: Step 3 ---
    # Helper methods that need a session must now accept it as a parameter.
    def _get_run_or_404(self, run_id: str, db: Session) -> RunModel:
        run = db.query(RunModel).filter(RunModel.id == run_id).first()
        if not run:
            raise HTTPException(status_code=404, detail="Run not found")
        return run

    def _to_read(self, r: RunModel) -> validator.Run:
        """
        Normalize an ORM Run → shared Pydantic 'Run' (as used in envelopes).
        All timestamps are returned as epoch seconds (ints or None).
        """
        return validator.Run(
            id=r.id,
            user_id=r.user_id,
            assistant_id=r.assistant_id,
            cancelled_at=self._to_epoch(r.cancelled_at),
            completed_at=self._to_epoch(r.completed_at),
            created_at=int(r.created_at) if r.created_at is not None else None,
            expires_at=int(r.expires_at) if r.expires_at is not None else 0,
            failed_at=self._to_epoch(r.failed_at),
            incomplete_details=r.incomplete_details,
            instructions=r.instructions or "",
            last_error=r.last_error,
            max_completion_tokens=r.max_completion_tokens,
            max_prompt_tokens=r.max_prompt_tokens,
            meta_data=self._ensure_dict(r.meta_data),
            model=r.model or "",
            object=r.object or "run",
            parallel_tool_calls=bool(r.parallel_tool_calls),
            required_action=r.required_action,
            response_format=r.response_format or "text",
            started_at=self._to_epoch(r.started_at),
            status=(r.status.value if hasattr(r.status, "value") else r.status),
            thread_id=r.thread_id,
            tool_choice=r.tool_choice or "none",
            tools=(r.tools or []),
            truncation_strategy=r.truncation_strategy,
            usage=r.usage,
            temperature=r.temperature if r.temperature is not None else 0.7,
            top_p=r.top_p if r.top_p is not None else 0.9,
            tool_resources=self._ensure_dict(r.tool_resources),
        )

    # -----------------------------------
    # CRUD
    # -----------------------------------
    def create_run(self, run_data: validator.RunCreate, *, user_id: str) -> Run:
        """
        Persist a new run tied to the given user_id.
        """
        # --- FIX: Step 4 ---
        # Each method now creates and manages its own session.
        with SessionLocal() as db:
            ts_kwargs = {}
            if run_data.truncation_strategy is not None:
                ts_value = getattr(
                    run_data.truncation_strategy, "value", run_data.truncation_strategy
                )
                ts_kwargs["truncation_strategy"] = ts_value

            new_run = Run(
                id=UtilsInterface.IdentifierService.generate_run_id(),
                user_id=user_id,
                assistant_id=run_data.assistant_id,
                cancelled_at=self._to_epoch(run_data.cancelled_at),
                completed_at=self._to_epoch(run_data.completed_at),
                created_at=int(time.time()),
                expires_at=int(time.time() + 3600),
                failed_at=self._to_epoch(run_data.failed_at),
                started_at=self._to_epoch(run_data.started_at),
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
                status=StatusEnum.queued,
                thread_id=run_data.thread_id,
                tool_choice=run_data.tool_choice,
                tools=[tool.dict() for tool in run_data.tools],
                usage=run_data.usage,
                temperature=run_data.temperature,
                top_p=run_data.top_p,
                tool_resources=run_data.tool_resources,
                **ts_kwargs,
            )
            self.logger.info(
                "Persisting run (user_id=%s, assistant_id=%s, thread_id=%s)",
                user_id,
                run_data.assistant_id,
                run_data.thread_id,
            )
            db.add(new_run)
            db.commit()
            db.refresh(new_run)
            self.logger.info("Run created successfully: %s", new_run.id)
            return new_run

    def update_run_status(self, run_id: str, new_status: str) -> Run:
        with SessionLocal() as db:
            run: Optional[Run] = db.query(Run).filter(Run.id == run_id).first()
            if not run:
                raise HTTPException(status_code=404, detail="Run not found")
            try:
                run.status = StatusEnum(new_status)
            except ValueError:
                raise HTTPException(
                    status_code=400, detail=f"Invalid status: {new_status}"
                )
            db.commit()
            db.refresh(run)
            return run

    def retrieve_run(self, run_id: str) -> Optional[validator.RunReadDetailed]:
        with SessionLocal() as db:
            run: Optional[Run] = db.query(Run).filter(Run.id == run_id).first()
            if not run:
                return None
            return validator.RunReadDetailed(
                id=run.id,
                user_id=run.user_id,
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
                status=(
                    run.status.value
                    if isinstance(run.status, StatusEnum)
                    else run.status
                ),
                thread_id=run.thread_id,
                tool_choice=run.tool_choice,
                tools=parse_obj_as(List[validator.ToolRead], run.tools),
                truncation_strategy=run.truncation_strategy,
                usage=run.usage,
                temperature=run.temperature,
                top_p=run.top_p,
                tool_resources=run.tool_resources,
                actions=[],
            )

    def list_runs(
        self,
        *,
        user_id: str,
        limit: int = 20,
        order: str = "asc",
        thread_id: Optional[str] = None,
    ) -> Tuple[List[validator.Run], bool]:
        with SessionLocal() as db:
            q = db.query(Run).filter(Run.user_id == user_id)
            if thread_id:
                q = q.filter(Run.thread_id == thread_id)

            if order == "asc":
                q = q.order_by(Run.created_at.asc(), Run.id.asc())
            else:
                q = q.order_by(Run.created_at.desc(), Run.id.desc())

            rows = q.limit(limit + 1).all()
            has_more = len(rows) > limit
            rows = rows[:limit]

            out: List[validator.Run] = [self._to_read(r) for r in rows]
            return out, has_more

    def update_run(
        self,
        run_id: str,
        new_metadata: Dict[str, Any],
        *,
        user_id: Optional[str] = None,
    ) -> validator.Run:
        with SessionLocal() as db:
            self.logger.info("Updating metadata for run %s", run_id)
            run = self._get_run_or_404(run_id, db)

            if user_id and run.user_id != user_id:
                raise HTTPException(status_code=404, detail="Run not found")

            current = self._ensure_dict(run.meta_data)
            current.update(self._ensure_dict(new_metadata))
            run.meta_data = current
            db.commit()
            db.refresh(run)
            self.logger.info("Run %s metadata updated", run_id)
            return self._to_read(run)

    def cancel_run(self, run_id: str) -> Run:
        with SessionLocal() as db:
            self.logger.info("Attempting to cancel run %s", run_id)
            run: Optional[Run] = db.query(Run).filter(Run.id == run_id).first()
            if not run:
                self.logger.error("Run %s not found", run_id)
                raise HTTPException(status_code=404, detail="Run not found")
            if run.status in {StatusEnum.completed, StatusEnum.cancelled}:
                raise HTTPException(
                    status_code=400,
                    detail="Cannot cancel a completed or already cancelled run",
                )

            run.status = StatusEnum.cancelling
            db.commit()

            run.status = StatusEnum.cancelled
            run.cancelled_at = int(time.time())
            db.commit()
            db.refresh(run)

            self.logger.info("Run %s successfully cancelled", run_id)
            return run
