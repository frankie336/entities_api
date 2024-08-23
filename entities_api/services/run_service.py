from fastapi import HTTPException
from models.models import Run
from pydantic import parse_obj_as
from entities_api.services.identifier_service import IdentifierService
from entities_api.schemas import Tool
from entities_api.services.thread_service import ThreadService
from sqlalchemy.orm import Session
from typing import List
import time


class RunService:
    def __init__(self, db: Session):
        self.db = db
        self.thread_service = ThreadService(db)

    def create_run(self, run_data):
        run = Run(
            id=IdentifierService.generate_run_id(),
            assistant_id=run_data.assistant_id,
            created_at=int(time.time()),
            status="queued",
            thread_id=run_data.thread_id,
            # ... other fields ...
        )
        self.db.add(run)
        self.db.commit()
        self.db.refresh(run)
        return run

    def start_run(self, run_id: str):
        run = self.db.query(Run).filter(Run.id == run_id).first()
        if not run:
            raise HTTPException(status_code=404, detail="Run not found")
        if run.status != "queued":
            raise HTTPException(status_code=400, detail="Run is not in queued state")

        if self.thread_service.check_and_set_active_run(run.thread_id, run_id):
            run.status = "in_progress"
            run.started_at = int(time.time())
            self.db.commit()
            self.db.refresh(run)
            return run
        else:
            raise HTTPException(status_code=409, detail="Another run is already in progress for this thread")

    def complete_run(self, run_id: str):
        run = self.db.query(Run).filter(Run.id == run_id).first()
        if not run:
            raise HTTPException(status_code=404, detail="Run not found")
        if run.status != "in_progress":
            raise HTTPException(status_code=400, detail="Run is not in progress")

        run.status = "completed"
        run.completed_at = int(time.time())
        self.db.commit()
        self.db.refresh(run)
        return run

    def fail_run(self, run_id: str, error_message: str):
        run = self.db.query(Run).filter(Run.id == run_id).first()
        if not run:
            raise HTTPException(status_code=404, detail="Run not found")

        run.status = "failed"
        run.failed_at = int(time.time())
        run.last_error = error_message
        self.db.commit()
        self.db.refresh(run)
        return run

    def cancel_run(self, run_id: str):
        run = self.db.query(Run).filter(Run.id == run_id).first()
        if not run:
            raise HTTPException(status_code=404, detail="Run not found")
        if run.status not in ["queued", "in_progress"]:
            raise HTTPException(status_code=400, detail="Run cannot be cancelled in its current state")

        run.status = "cancelled"
        run.cancelled_at = int(time.time())
        self.db.commit()
        self.db.refresh(run)
        return run

    def expire_run(self, run_id: str):
        run = self.db.query(Run).filter(Run.id == run_id).first()
        if not run:
            raise HTTPException(status_code=404, detail="Run not found")
        if run.status != "in_progress":
            raise HTTPException(status_code=400, detail="Only in-progress runs can expire")

        run.status = "expired"
        run.expires_at = int(time.time())
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
                started_at=run.started_at,
                status=run.status,
                thread_id=run.thread_id,
                # ... other fields ...
            )
            return run_data
        return None

    def update_run_status(self, run_id: str, new_status: str):
        run = self.db.query(Run).filter(Run.id == run_id).first()
        if not run:
            raise HTTPException(status_code=404, detail="Run not found")

        if new_status not in ["queued", "in_progress", "completed", "failed", "cancelled", "expired"]:
            raise HTTPException(status_code=400, detail="Invalid status")

        if new_status == "in_progress":
            if not self.thread_service.check_and_set_active_run(run.thread_id, run_id):
                raise HTTPException(status_code=409, detail="Another run is already in progress for this thread")

        run.status = new_status
        self.db.commit()
        self.db.refresh(run)
        return run