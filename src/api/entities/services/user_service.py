from sqlalchemy.orm import Session
from entities.models.models import User
from entities.schemas.users import UserCreate, UserRead, UserUpdate
from entities.schemas.assistants import AssistantRead
from entities.services.identifier_service import IdentifierService
from typing import List
from fastapi import HTTPException


class UserService:
    def __init__(self, db: Session):
        self.db = db

    def create_user(self, user: UserCreate = None) -> UserRead:
        if user is None:
            user = UserCreate()

        new_user = User(
            id=IdentifierService.generate_user_id(),
            name=user.name
        )
        self.db.add(new_user)
        self.db.commit()
        self.db.refresh(new_user)
        return UserRead.from_orm(new_user)

    def get_user(self, user_id: str) -> UserRead:
        user = self.db.query(User).filter(User.id == user_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        return UserRead.from_orm(user)

    def get_users(self) -> List[UserRead]:
        users = self.db.query(User).all()
        return [UserRead.from_orm(user) for user in users]

    def update_user(self, user_id: str, user_update: UserUpdate) -> UserRead:
        db_user = self.db.query(User).filter(User.id == user_id).first()
        if not db_user:
            raise HTTPException(status_code=404, detail="User not found")

        update_data = user_update.dict(exclude_unset=True)
        for key, value in update_data.items():
            setattr(db_user, key, value)

        self.db.commit()
        self.db.refresh(db_user)
        return UserRead.from_orm(db_user)

    def delete_user(self, user_id: str) -> None:
        db_user = self.db.query(User).filter(User.id == user_id).first()
        if not db_user:
            raise HTTPException(status_code=404, detail="User not found")

        self.db.delete(db_user)
        self.db.commit()

    def get_or_create_user(self, user_id: str = None) -> UserRead:
        if user_id:
            try:
                return self.get_user(user_id)
            except HTTPException:
                pass

        return self.create_user()

    def list_assistants_by_user(self, user_id: str) -> List[AssistantRead]:
        """
        Retrieve the list of assistants associated with a specific user.
        """
        user = self.db.query(User).filter(User.id == user_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        return [AssistantRead.from_orm(assistant) for assistant in user.assistants]
