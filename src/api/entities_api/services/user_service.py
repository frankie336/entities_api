# src/api/entities_api/services/user_service.py

from datetime import datetime  # Added for updated_at logic
from typing import List, Optional

from fastapi import HTTPException, status  # Added status
from projectdavid_common import UtilsInterface, ValidationInterface
from sqlalchemy import or_  # Added for querying
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import \
    NoResultFound  # Optional: for specific exception handling

# Assume models are correctly imported
from entities_api.models.models import (  # Added Assistant if not implicitly imported via User relationship
    Assistant, User)


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
        # Optional: Check if email already exists if provided
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
            # Map fields from the updated UserCreate model
            email=user_create.email,
            email_verified=user_create.email_verified
            or False,  # Default to False if not provided
            full_name=user_create.full_name,
            given_name=user_create.given_name,
            family_name=user_create.family_name,
            picture_url=user_create.picture_url,
            oauth_provider=user_create.oauth_provider
            or "local",  # Default to 'local' if not specified
            provider_user_id=user_create.provider_user_id,
            # created_at and updated_at have defaults in the model
        )
        self.db.add(new_user)
        self.db.commit()
        self.db.refresh(new_user)
        # Ensure UserRead is updated in ValidationInterface to handle the new fields
        return ValidationInterface.UserRead.model_validate(
            new_user
        )  # Use model_validate for Pydantic v2

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
        # 1. Try finding by Provider and Provider User ID
        user = (
            self.db.query(User)
            .filter(
                User.oauth_provider == provider,
                User.provider_user_id == provider_user_id,
            )
            .first()
        )

        # 2. If not found by Provider ID, try finding by verified Email (if provided)
        #    Avoid linking if email exists but belongs to a *different* provider or is local
        if not user and email and email_verified:
            potential_user = self.db.query(User).filter(User.email == email).first()
            # Link only if the existing user doesn't have conflicting provider info
            # or if you decide OAuth linking should override local accounts. Be careful here.
            # Example: Only link if the user found via email has NO provider info OR matches the current provider.
            if potential_user and (
                not potential_user.oauth_provider
                or potential_user.oauth_provider == provider
            ):
                user = potential_user
                # If found via email, update the provider details
                user.oauth_provider = provider
                user.provider_user_id = provider_user_id

        # 3. If User is found (either by ID or email), update their info
        if user:
            update_occurred = False
            # Update fields only if new data is provided and different
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
            # Update email verification status if provider confirms it
            if (
                email is not None and user.email != email
            ):  # Handle email changes if necessary
                user.email = email
                user.email_verified = email_verified or False
                update_occurred = True
            elif email_verified is not None and user.email_verified != email_verified:
                user.email_verified = email_verified
                update_occurred = True

            # If any fields were updated, mark the user object for update
            if update_occurred:
                user.updated_at = datetime.utcnow()  # Explicitly update timestamp

            self.db.commit()
            self.db.refresh(user)

        # 4. If User is still not found, create a new one
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

        # Ensure UserRead reflects the new model structure
        return ValidationInterface.UserRead.model_validate(user)  # Use model_validate

    def get_user(self, user_id: str) -> ValidationInterface.UserRead:
        """Gets a user by their internal ID."""
        user = self.db.query(User).filter(User.id == user_id).first()
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
            )
        # Assumes UserRead Pydantic model is updated
        return ValidationInterface.UserRead.model_validate(user)

    def get_user_by_email(self, email: str) -> Optional[ValidationInterface.UserRead]:
        """Gets a user by their email address."""
        user = self.db.query(User).filter(User.email == email).first()
        if not user:
            return None
            # Or raise HTTPException if email *must* exist for the caller
            # raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User with this email not found")
        return ValidationInterface.UserRead.model_validate(user)

    def get_users(
        self, skip: int = 0, limit: int = 100
    ) -> List[ValidationInterface.UserRead]:
        """Gets a list of users with pagination."""
        users = self.db.query(User).offset(skip).limit(limit).all()
        # Assumes UserRead Pydantic model is updated
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

        # Ensure UserUpdate Pydantic model has the correct fields
        update_data = user_update.model_dump(
            exclude_unset=True
        )  # Use model_dump for Pydantic v2

        # Optional: Prevent changing certain fields via this generic update, like provider info
        # update_data.pop('oauth_provider', None)
        # update_data.pop('provider_user_id', None)
        # update_data.pop('email', None) # Maybe require a separate verification flow for email changes

        updated = False
        for key, value in update_data.items():
            if hasattr(db_user, key) and getattr(db_user, key) != value:
                setattr(db_user, key, value)
                updated = True

        if updated:
            db_user.updated_at = datetime.utcnow()  # Update timestamp
            self.db.commit()
            self.db.refresh(db_user)

        # Assumes UserRead Pydantic model is updated
        return ValidationInterface.UserRead.model_validate(db_user)

    def delete_user(self, user_id: str) -> None:
        """Deletes a user by their internal ID."""
        db_user = self.db.query(User).filter(User.id == user_id).first()
        if not db_user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
            )

        # Consider implications: deleting a user might require cleanup of related entities
        # depending on cascade rules or business logic.
        # For example, API keys are set to cascade delete. What about Threads, Assistants etc.?
        # Add more cleanup logic here if needed before deleting the user.

        self.db.delete(db_user)
        self.db.commit()
        # No return needed for delete operations typically

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
            # If ID provided but not found, should we proceed to create? Or raise error?
            # Let's raise for clarity if an ID was given but invalid.
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"User with ID {user_id} not found",
            )

        # If no user_id provided, create a minimal 'local' user
        # Assume UserCreate can be called with no arguments for default fields
        # Or define what a minimal user means here.
        minimal_user_data = ValidationInterface.UserCreate(
            oauth_provider="local"  # Explicitly set provider if creating bare user
            # Add other defaults if needed/required by UserCreate
        )
        return self.create_user(minimal_user_data)

    def list_assistants_by_user(
        self, user_id: str
    ) -> List[ValidationInterface.AssistantRead]:
        """
        Retrieve the list of assistants associated with a specific user.
        (Logic remains the same, relies on relationships)
        """
        # Use joinedload to potentially optimize fetching assistants if it's common
        user = (
            self.db.query(User)
            .options(
                # Consider joinedload only if AssistantRead needs details usually lazy-loaded
                # from sqlalchemy.orm import joinedload
                # joinedload(User.assistants)
            )
            .filter(User.id == user_id)
            .first()
        )

        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
            )

        # Ensure AssistantRead is compatible with the Assistant model
        return [
            ValidationInterface.AssistantRead.model_validate(assistant)
            for assistant in user.assistants  # Access the relationship
        ]
