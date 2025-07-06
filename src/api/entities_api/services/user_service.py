from datetime import datetime
from typing import List, Optional

from fastapi import HTTPException, status
from projectdavid_common import UtilsInterface, ValidationInterface
from sqlalchemy.orm import Session

from src.api.entities_api.models.models import User


class UserService:

    def __init__(self, db: Session):
        self.db = db

    def create_user(
        self, user_create: ValidationInterface.UserCreate
    ) -> ValidationInterface.UserRead:
        """
        Creates a new user directly from provided details (e.g., manual creation).
        For OAuth users, prefer using find_or_create_oauth_user.
        """
        if user_create.email:
            existing_user = (
                self.db.query(User).filter(User.email == user_create.email).first()
            )
            if existing_user:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"User with email {user_create.email} already exists.",
                )
        new_user = User(
            id=UtilsInterface.IdentifierService.generate_user_id(),
            email=user_create.email,
            email_verified=user_create.email_verified or False,
            full_name=user_create.full_name,
            given_name=user_create.given_name,
            family_name=user_create.family_name,
            picture_url=user_create.picture_url,
            oauth_provider=user_create.oauth_provider or "local",
            provider_user_id=user_create.provider_user_id,
        )
        self.db.add(new_user)
        self.db.commit()
        self.db.refresh(new_user)
        return ValidationInterface.UserRead.model_validate(new_user)

    def find_or_create_oauth_user(
        self,
        provider: str,
        provider_user_id: str,
        email: Optional[str],
        email_verified: Optional[bool],
        full_name: Optional[str],
        given_name: Optional[str],
        family_name: Optional[str],
        picture_url: Optional[str],
    ) -> ValidationInterface.UserRead:
        """
        Finds a user by OAuth provider and ID, or optionally by verified email.
        If found, updates profile info. If not found, creates a new user.
        """
        user = (
            self.db.query(User)
            .filter(
                User.oauth_provider == provider,
                User.provider_user_id == provider_user_id,
            )
            .first()
        )
        if not user and email and email_verified:
            potential_user = self.db.query(User).filter(User.email == email).first()
            if potential_user and (
                not potential_user.oauth_provider
                or potential_user.oauth_provider == provider
            ):
                user = potential_user
                user.oauth_provider = provider
                user.provider_user_id = provider_user_id
        if user:
            update_occurred = False
            if full_name is not None and user.full_name != full_name:
                user.full_name = full_name
                update_occurred = True
            if given_name is not None and user.given_name != given_name:
                user.given_name = given_name
                update_occurred = True
            if family_name is not None and user.family_name != family_name:
                user.family_name = family_name
                update_occurred = True
            if picture_url is not None and user.picture_url != picture_url:
                user.picture_url = picture_url
                update_occurred = True
            if email is not None and user.email != email:
                user.email = email
                user.email_verified = email_verified or False
                update_occurred = True
            elif email_verified is not None and user.email_verified != email_verified:
                user.email_verified = email_verified
                update_occurred = True
            if update_occurred:
                user.updated_at = datetime.utcnow()
            self.db.commit()
            self.db.refresh(user)
        else:
            user = User(
                id=UtilsInterface.IdentifierService.generate_user_id(),
                email=email,
                email_verified=email_verified or False,
                full_name=full_name,
                given_name=given_name,
                family_name=family_name,
                picture_url=picture_url,
                oauth_provider=provider,
                provider_user_id=provider_user_id,
            )
            self.db.add(user)
            self.db.commit()
            self.db.refresh(user)
        return ValidationInterface.UserRead.model_validate(user)

    def get_user(self, user_id: str) -> ValidationInterface.UserRead:
        """Gets a user by their internal ID."""
        user = self.db.query(User).filter(User.id == user_id).first()
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
            )
        return ValidationInterface.UserRead.model_validate(user)

    def get_user_by_email(self, email: str) -> Optional[ValidationInterface.UserRead]:
        """Gets a user by their email address."""
        user = self.db.query(User).filter(User.email == email).first()
        if not user:
            return None
        return ValidationInterface.UserRead.model_validate(user)

    def get_users(
        self, skip: int = 0, limit: int = 100
    ) -> List[ValidationInterface.UserRead]:
        """Gets a list of users with pagination."""
        users = self.db.query(User).offset(skip).limit(limit).all()
        return [ValidationInterface.UserRead.model_validate(user) for user in users]

    def update_user(
        self, user_id: str, user_update: ValidationInterface.UserUpdate
    ) -> ValidationInterface.UserRead:
        """Updates user fields based on the UserUpdate model."""
        db_user = self.db.query(User).filter(User.id == user_id).first()
        if not db_user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
            )
        update_data = user_update.model_dump(exclude_unset=True)
        updated = False
        for key, value in update_data.items():
            if hasattr(db_user, key) and getattr(db_user, key) != value:
                setattr(db_user, key, value)
                updated = True
        if updated:
            db_user.updated_at = datetime.utcnow()
            self.db.commit()
            self.db.refresh(db_user)
        return ValidationInterface.UserRead.model_validate(db_user)

    def delete_user(self, user_id: str) -> None:
        """Deletes a user by their internal ID."""
        db_user = self.db.query(User).filter(User.id == user_id).first()
        if not db_user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
            )
        self.db.delete(db_user)
        self.db.commit()

    def get_or_create_user(
        self, user_id: Optional[str] = None
    ) -> ValidationInterface.UserRead:
        """
        DEPRECATED (potentially): This is ambiguous with the new model.
        Gets a user by ID if provided. If ID is not provided or user not found,
        creates a new 'local' user with minimal details.
        Consider using create_user or find_or_create_oauth_user directly.
        """
        if user_id:
            user = self.db.query(User).filter(User.id == user_id).first()
            if user:
                return ValidationInterface.UserRead.model_validate(user)
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"User with ID {user_id} not found",
            )
        minimal_user_data = ValidationInterface.UserCreate(oauth_provider="local")
        return self.create_user(minimal_user_data)

    def list_assistants_by_user(
        self, user_id: str
    ) -> List[ValidationInterface.AssistantRead]:
        """
        Retrieve the list of assistants associated with a specific user.
        (Logic remains the same, relies on relationships)
        """
        user = self.db.query(User).options().filter(User.id == user_id).first()
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
            )
        return [
            ValidationInterface.AssistantRead.model_validate(assistant)
            for assistant in user.assistants
        ]
