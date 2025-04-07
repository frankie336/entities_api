import time
from typing import List, Optional

# Import common validation models and StatusEnum
from entities_common import ValidationInterface
from entities_common.schemas.enums import StatusEnum
from sqlalchemy.exc import IntegrityError  # To catch duplicate key errors
# Import SQLAlchemy components
from sqlalchemy.orm import joinedload, Session

from entities_api.models.models import VectorStore, Assistant, VectorStoreFile


# --- Define Service-Level Exceptions ---
# These help decouple the service logic from HTTP-specific exceptions


class VectorStoreDBError(Exception):
    """Base exception for VectorStoreDBService errors."""

    pass


class VectorStoreNotFoundError(VectorStoreDBError):
    """Raised when a requested vector store is not found."""

    pass


class VectorStoreFileError(VectorStoreDBError):
    """Base exception for file-related errors within a vector store."""

    pass


class VectorStoreFileNotFoundError(VectorStoreFileError):
    """Raised when a requested file within a vector store is not found."""

    pass


class AssistantNotFoundError(VectorStoreDBError):
    """Raised when a requested assistant is not found."""

    pass


class DatabaseConflictError(VectorStoreDBError):
    """Raised for database conflicts like unique constraint violations."""

    pass


# --- Updated Service Class ---


class VectorStoreDBService:
    def __init__(self, db: Session):
        self.db = db

    def create_vector_store(
        self,
        shared_id: str,  # This is the VectorStore.id and VectorStore.collection_name
        name: str,
        user_id: str,
        vector_size: int,
        distance_metric: str,
        config: Optional[dict] = None,
    ) -> ValidationInterface.VectorStoreRead:
        """
        Creates the VectorStore metadata record in the database.

        Args:
            shared_id: The unique ID (also collection_name) for the store.
            name: The user-visible name of the store.
            user_id: The ID of the owning user.
            vector_size: Dimension of vectors stored.
            distance_metric: Distance metric used (e.g., 'COSINE').
            config: Optional configuration dictionary.

        Returns:
            A Pydantic model of the created vector store.

        Raises:
            DatabaseConflictError: If a vector store with the same shared_id already exists.
            VectorStoreDBError: For other database errors during creation.
        """
        new_store = VectorStore(
            id=shared_id,
            name=name,
            user_id=user_id,
            collection_name=shared_id,
            vector_size=vector_size,
            distance_metric=distance_metric,
            config=config or {},
            created_at=int(time.time()),
            status=ValidationInterface.StatusEnum.active,
            file_count=0,
        )
        self.db.add(new_store)
        try:
            self.db.commit()
            self.db.refresh(new_store)
            return ValidationInterface.VectorStoreRead.model_validate(new_store)
        except IntegrityError as e:
            self.db.rollback()
            # Check if it's specifically a duplicate key error on 'id' or 'collection_name'
            # The exact error message/code might vary by DB backend (MySQL, PostgreSQL)
            # This is a basic check; more robust parsing might be needed for production
            if "Duplicate entry" in str(e.orig) or "violates unique constraint" in str(e.orig):
                raise DatabaseConflictError(
                    f"Vector store with ID/collection name '{shared_id}' already exists."
                ) from e
            else:
                raise VectorStoreDBError(f"Database error creating vector store: {str(e)}") from e
        except Exception as e:
            self.db.rollback()
            raise VectorStoreDBError(f"Unexpected error creating vector store: {str(e)}") from e

    def mark_vector_store_deleted(
        self, vector_store_id: str
    ) -> ValidationInterface.VectorStoreRead:
        """
        Soft deletes a vector store record by ID by setting its status to 'deleted'.

        Args:
            vector_store_id: The ID of the vector store to soft delete.

        Returns:
            A Pydantic model of the updated (soft-deleted) vector store.

        Raises:
            VectorStoreNotFoundError: If the vector store with the given ID is not found.
            VectorStoreDBError: For other database errors.
        """
        store = self.db.get(VectorStore, vector_store_id)
        if not store:
            raise VectorStoreNotFoundError(f"Vector store ID '{vector_store_id}' not found.")

        if store.status == ValidationInterface.StatusEnum.deleted:
            # Already deleted, return current state
            return ValidationInterface.VectorStoreRead.model_validate(store)

        store.status = ValidationInterface.StatusEnum.deleted
        store.updated_at = int(time.time())
        try:
            self.db.commit()
            self.db.refresh(store)
            return ValidationInterface.VectorStoreRead.model_validate(store)
        except Exception as e:
            self.db.rollback()
            raise VectorStoreDBError(
                f"Database error marking vector store '{vector_store_id}' as deleted: {str(e)}"
            ) from e

    def permanently_delete_vector_store(self, vector_store_id: str) -> bool:
        """
        Permanently deletes a vector store record and its associated files via cascade.

        Args:
            vector_store_id: The ID of the vector store to permanently delete.

        Returns:
            True if deletion was successful.

        Raises:
            VectorStoreNotFoundError: If the vector store with the given ID is not found.
            VectorStoreDBError: For other database errors during deletion.
        """
        store = self.db.get(VectorStore, vector_store_id)
        if not store:
            raise VectorStoreNotFoundError(f"Vector store ID '{vector_store_id}' not found.")

        # Detach the object from the session before deletion if needed,
        # especially if there are related objects that might cause issues during cascade.
        # make_transient(store) # Optional, usually cascade handles this

        try:
            # Note: cascade="all, delete-orphan" on VectorStore.files handles VectorStoreFile deletion
            self.db.delete(store)
            self.db.commit()
            return True  # Indicate successful deletion
        except Exception as e:
            self.db.rollback()
            raise VectorStoreDBError(
                f"Database error permanently deleting vector store '{vector_store_id}': {str(e)}"
            ) from e

    def get_vector_store_by_id(
        self, vector_store_id: str
    ) -> Optional[ValidationInterface.VectorStoreRead]:
        """
        Retrieves a vector store by its primary ID.

        Args:
            vector_store_id: The ID of the vector store.

        Returns:
            A Pydantic model of the vector store, or None if not found.
            (API layer should handle converting None to 404).
        """
        store = self.db.get(VectorStore, vector_store_id)
        if not store:
            return None
        return ValidationInterface.VectorStoreRead.model_validate(store)

    def get_vector_store_by_collection_name(
        self, collection_name: str
    ) -> Optional[ValidationInterface.VectorStoreRead]:
        """
        Retrieves a vector store by its unique collection name.

        Args:
            collection_name: The unique collection name to search for.

        Returns:
            A Pydantic model of the vector store, or None if not found.
        """
        store = (
            self.db.query(VectorStore)
            .filter(VectorStore.collection_name == collection_name)
            .first()
        )
        if not store:
            return None
        return ValidationInterface.VectorStoreRead.model_validate(store)

    def get_stores_by_user(self, user_id: str) -> List[ValidationInterface.VectorStoreRead]:
        """
        Retrieves all non-deleted vector stores owned by a specific user.

        Args:
            user_id: The ID of the user.

        Returns:
            A list of Pydantic models representing the user's vector stores.
        """
        stores = (
            self.db.query(VectorStore)
            .filter(
                VectorStore.user_id == user_id,
                VectorStore.status != ValidationInterface.StatusEnum.deleted,  # Exclude soft-deleted
            )
            .all()
        )
        return [ValidationInterface.VectorStoreRead.model_validate(store) for store in stores]

    # --- VectorStoreFile Management ---

    def create_vector_store_file(
        self,
        vector_store_id: str,
        file_id: str,
        file_name: str,
        file_path: str,
        status: StatusEnum = ValidationInterface.StatusEnum.completed,
        meta_data: Optional[dict] = None,
    ) -> ValidationInterface.VectorStoreFileRead:
        """
        Creates a VectorStoreFile record and increments the store's file count.

        Args:
            vector_store_id: The ID of the parent vector store.
            file_id: The unique ID for this file record.
            file_name: The original name of the file.
            file_path: Path identifier used for backend filtering.
            status: Initial status of the file record.
            meta_data: Optional metadata dictionary.

        Returns:
            A Pydantic model of the created file record.

        Raises:
            VectorStoreNotFoundError: If the parent vector store is not found or deleted.
            DatabaseConflictError: If a file record with the same file_id already exists.
            VectorStoreDBError: For other database errors.
        """
        store = self.db.get(VectorStore, vector_store_id)
        if not store or store.status == StatusEnum.deleted:
            raise VectorStoreNotFoundError(
                f"Vector store '{vector_store_id}' not found or is deleted."
            )

        new_file = ValidationInterface.VectorStoreFileCreate(
            id=file_id,
            vector_store_id=vector_store_id,
            file_name=file_name,
            file_path=file_path,
            status=status,
            meta_data=meta_data or {},
            processed_at=int(time.time()) if status == StatusEnum.completed else None,
        )
        # Use SQLAlchemy attribute expression for safe increment
        store.file_count = VectorStore.file_count + 1
        store.updated_at = int(time.time())

        self.db.add(new_file)
        try:
            self.db.commit()
            self.db.refresh(new_file)
            return ValidationInterface.VectorStoreFileRead.model_validate(new_file)
        except IntegrityError as e:
            self.db.rollback()
            if "Duplicate entry" in str(e.orig) or "violates unique constraint" in str(e.orig):
                raise DatabaseConflictError(
                    f"Vector store file with ID '{file_id}' already exists."
                ) from e
            else:
                raise VectorStoreDBError(f"Database error creating file record: {str(e)}") from e
        except Exception as e:
            self.db.rollback()
            raise VectorStoreDBError(f"Unexpected error creating file record: {str(e)}") from e

    def delete_vector_store_file_by_path(self, vector_store_id: str, file_path: str) -> bool:
        """
        Deletes a VectorStoreFile record by path and decrements file count.

        Args:
            vector_store_id: The ID of the parent vector store.
            file_path: The path identifier of the file to delete.

        Returns:
            True if the file was found and deleted.

        Raises:
            VectorStoreNotFoundError: If the parent store is not found.
            VectorStoreFileNotFoundError: If the file with the specified path is not found in that store.
            VectorStoreDBError: For other database errors.
        """
        store = self.db.get(VectorStore, vector_store_id)
        if not store:
            raise VectorStoreNotFoundError(f"Vector store '{vector_store_id}' not found.")

        file_to_delete = (
            self.db.query(VectorStoreFile)
            .filter(
                VectorStoreFile.vector_store_id == vector_store_id,
                VectorStoreFile.file_path == file_path,
            )
            .first()
        )

        if not file_to_delete:
            raise VectorStoreFileNotFoundError(
                f"File with path '{file_path}' not found in store '{vector_store_id}'."
            )

        # Use SQLAlchemy attribute expression for safe decrement
        store.file_count = VectorStore.file_count - 1
        # Ensure count doesn't go below zero (though ideally should match actual deletion)
        if store.file_count < 0:
            store.file_count = 0
        store.updated_at = int(time.time())

        try:
            self.db.delete(file_to_delete)
            self.db.commit()
            return True
        except Exception as e:
            self.db.rollback()
            raise VectorStoreDBError(
                f"Database error deleting file record '{file_path}' from store '{vector_store_id}': {str(e)}"
            ) from e

    def list_vector_store_files(
        self, vector_store_id: str
    ) -> List[ValidationInterface.VectorStoreFileRead]:
        """
        Lists all non-deleted files associated with a vector store.

        Args:
            vector_store_id: The ID of the vector store.

        Returns:
            A list of Pydantic models for the files. Returns empty list if store not found.
        """
        store = self.db.get(VectorStore, vector_store_id)
        if not store or store.status == StatusEnum.deleted:
            # Consistent with returning empty list if parent not found/deleted
            return []

        # Use the dynamic relationship query, filtering by status
        files = store.files.filter(VectorStoreFile.status != StatusEnum.deleted).all()

        return [ValidationInterface.VectorStoreFileRead.model_validate(f) for f in files]

    def update_vector_store_file_status(
        self, file_id: str, status: StatusEnum, error_message: Optional[str] = None
    ) -> ValidationInterface.VectorStoreFileRead:
        """
        Updates the status and potentially error message of a file record.

        Args:
            file_id: The unique ID of the VectorStoreFile record.
            status: The new status enum value.
            error_message: Optional error message if status is 'failed'.

        Returns:
            A Pydantic model of the updated file record.

        Raises:
            VectorStoreFileNotFoundError: If the file record with the given ID is not found.
            VectorStoreDBError: For other database errors.
        """
        file_record = self.db.get(VectorStoreFile, file_id)
        if not file_record:
            raise VectorStoreFileNotFoundError(f"File record with ID '{file_id}' not found.")

        file_record.status = status
        file_record.error_message = error_message
        # Update timestamp based on status
        if status in [StatusEnum.completed, StatusEnum.failed]:
            file_record.processed_at = int(time.time())
        # Optionally clear processed_at if moving back to a processing state?
        # elif status in [StatusEnum.queued, StatusEnum.processing]:
        #     file_record.processed_at = None

        # Also update the parent VectorStore's updated_at timestamp if possible
        if file_record.vector_store:  # Check if relationship is loaded/available
            file_record.vector_store.updated_at = int(time.time())

        try:
            self.db.commit()
            self.db.refresh(file_record)
            return ValidationInterface.VectorStoreFileRead.model_validate(file_record)
        except Exception as e:
            self.db.rollback()
            raise VectorStoreDBError(
                f"Database error updating status for file record '{file_id}': {str(e)}"
            ) from e

    # --- Assistant Attachment ---

    def attach_vector_store_to_assistant(self, vector_store_id: str, assistant_id: str) -> bool:
        """
        Attaches a vector store to an assistant.

        Args:
            vector_store_id: ID of the vector store.
            assistant_id: ID of the assistant.

        Returns:
            True if attached successfully or already attached.

        Raises:
            VectorStoreNotFoundError: If the vector store is not found or deleted.
            AssistantNotFoundError: If the assistant is not found.
            VectorStoreDBError: For other database errors.
        """
        # Fetch both to ensure they exist
        vector_store = self.db.get(VectorStore, vector_store_id)
        if not vector_store or vector_store.status == StatusEnum.deleted:
            raise VectorStoreNotFoundError(
                f"Vector store '{vector_store_id}' not found or is deleted."
            )

        assistant = self.db.get(Assistant, assistant_id)
        if not assistant:
            raise AssistantNotFoundError(f"Assistant '{assistant_id}' not found.")

        # Check if already attached to avoid unnecessary DB write/potential errors
        # This requires loading the relationship. Consider if lazy loading is acceptable.
        # If performance is critical, a direct check on the association table might be faster.
        if vector_store in assistant.vector_stores:
            return True  # Already attached

        assistant.vector_stores.append(vector_store)
        try:
            self.db.commit()
            return True
        except Exception as e:
            self.db.rollback()
            raise VectorStoreDBError(
                f"Database error attaching store '{vector_store_id}' to assistant '{assistant_id}': {str(e)}"
            ) from e

    def detach_vector_store_from_assistant(self, vector_store_id: str, assistant_id: str) -> bool:
        """
        Detaches a vector store from an assistant.

        Args:
            vector_store_id: ID of the vector store.
            assistant_id: ID of the assistant.

        Returns:
            True if detached successfully or was already detached.

        Raises:
            AssistantNotFoundError: If the assistant is not found.
            VectorStoreDBError: For other database errors.
        """
        # Eager load the stores relationship for efficient removal check
        assistant = (
            self.db.query(Assistant)
            .options(joinedload(Assistant.vector_stores))
            .filter(Assistant.id == assistant_id)
            .first()
        )

        if not assistant:
            raise AssistantNotFoundError(f"Assistant '{assistant_id}' not found.")

        # Find the store within the loaded relationship list
        vector_store_to_remove = next(
            (vs for vs in assistant.vector_stores if vs.id == vector_store_id), None
        )

        if vector_store_to_remove:
            assistant.vector_stores.remove(vector_store_to_remove)
            try:
                self.db.commit()
                return True  # Successfully removed
            except Exception as e:
                self.db.rollback()
                raise VectorStoreDBError(
                    f"Database error detaching store '{vector_store_id}' from assistant '{assistant_id}': {str(e)}"
                ) from e
        else:
            return True  # Indicate success even if it wasn't attached (idempotency)

    def get_vector_stores_for_assistant(
        self, assistant_id: str
    ) -> List[ValidationInterface.VectorStoreRead]:
        """
        Retrieves all non-deleted vector stores attached to an assistant.

        Args:
            assistant_id: The ID of the assistant.

        Returns:
            A list of Pydantic models representing the attached, active vector stores.
        """
        assistant = (
            self.db.query(Assistant)
            .options(joinedload(Assistant.vector_stores))  # Eager load associated stores
            .filter(Assistant.id == assistant_id)
            .first()
        )

        if not assistant:
            # Return empty list if assistant not found, API layer can handle 404 if needed
            return []

        # Filter out any potentially soft-deleted stores
        active_stores = [vs for vs in assistant.vector_stores if vs.status != StatusEnum.deleted]
        return [ValidationInterface.VectorStoreRead.model_validate(vs) for vs in active_stores]
