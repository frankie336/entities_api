# entities_api/services/sandbox_service.py
from datetime import time

from sqlalchemy.orm import Session
from fastapi import HTTPException
from models.models import Sandbox, User
from entities_api.schemas import SandboxCreate, SandboxRead, SandboxUpdate
from entities_api.services.identifier_service import IdentifierService
from entities_api.services.logging_service import LoggingUtility

logging_utility = LoggingUtility()


class SandboxService:
    def __init__(self, db: Session):
        self.db = db

    def create_sandbox(self, sandbox_data: SandboxCreate) -> SandboxRead:
        logging_utility.info(f"Creating sandbox for user_id: {sandbox_data.user_id}")

        # Verify that the user exists
        user = self.db.query(User).filter(User.id == sandbox_data.user_id).first()
        if not user:
            logging_utility.error(f"User not found with id: {sandbox_data.user_id}")
            raise HTTPException(status_code=404, detail="User not found")

        sandbox_id = IdentifierService.generate_sandbox_id()
        new_sandbox = Sandbox(
            id=sandbox_id,
            user_id=sandbox_data.user_id,
            name=sandbox_data.name,
            status="active",
            config=sandbox_data.config,
            created_at=int(time.time())
        )

        self.db.add(new_sandbox)
        self.db.commit()
        self.db.refresh(new_sandbox)

        logging_utility.info(f"Sandbox created with id: {sandbox_id}")
        return SandboxRead.model_validate(new_sandbox)

    def get_sandbox(self, sandbox_id: str) -> SandboxRead:
        logging_utility.info(f"Retrieving sandbox with id: {sandbox_id}")
        sandbox = self.db.query(Sandbox).filter(Sandbox.id == sandbox_id).first()
        if not sandbox:
            logging_utility.error(f"Sandbox not found with id: {sandbox_id}")
            raise HTTPException(status_code=404, detail="Sandbox not found")
        return SandboxRead.model_validate(sandbox)

    def update_sandbox(self, sandbox_id: str, sandbox_update: SandboxUpdate) -> SandboxRead:
        logging_utility.info(f"Updating sandbox with id: {sandbox_id}")
        sandbox = self.db.query(Sandbox).filter(Sandbox.id == sandbox_id).first()
        if not sandbox:
            logging_utility.error(f"Sandbox not found with id: {sandbox_id}")
            raise HTTPException(status_code=404, detail="Sandbox not found")

        update_data = sandbox_update.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(sandbox, key, value)

        self.db.commit()
        self.db.refresh(sandbox)

        logging_utility.info(f"Sandbox updated with id: {sandbox_id}")
        return SandboxRead.model_validate(sandbox)

    def delete_sandbox(self, sandbox_id: str) -> None:
        logging_utility.info(f"Deleting sandbox with id: {sandbox_id}")
        sandbox = self.db.query(Sandbox).filter(Sandbox.id == sandbox_id).first()
        if not sandbox:
            logging_utility.error(f"Sandbox not found with id: {sandbox_id}")
            raise HTTPException(status_code=404, detail="Sandbox not found")

        self.db.delete(sandbox)
        self.db.commit()
        logging_utility.info(f"Sandbox deleted with id: {sandbox_id}")

    def list_sandboxes_by_user(self, user_id: str) -> List[SandboxRead]:
        logging_utility.info(f"Listing sandboxes for user_id: {user_id}")
        sandboxes = self.db.query(Sandbox).filter(Sandbox.user_id == user_id).all()
        return [SandboxRead.model_validate(sandbox) for sandbox in sandboxes]
