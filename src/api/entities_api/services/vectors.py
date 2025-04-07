# entities_api/services/vectors.py

import time
from typing import List, Optional

# Import common validation models and StatusEnum
from entities_common import ValidationInterface
# Assuming StatusEnum is defined in ValidationInterface now
# from entities_common.schemas.enums import StatusEnum # Remove if defined in ValidationInterface
StatusEnum = ValidationInterface.StatusEnum # Use the one from ValidationInterface

from sqlalchemy.exc import IntegrityError  # To catch duplicate key errors
# Import SQLAlchemy components
from sqlalchemy.orm import Session, joinedload

# Import specific DB Models
from entities_api.models.models import (
    VectorStore,
    Assistant,
    VectorStoreFile,
    # StatusEnum as ModelStatusEnum # Only needed if DB Enum differs from Validation one
)


# --- Define Service-Level Exceptions ---

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
        # Optional: Add assertion if needed, but prefer using same enum source
        # from entities_api.models.models import StatusEnum as ModelStatusEnum
        # assert ModelStatusEnum == ValidationInterface.StatusEnum, \
        #    "SQLAlchemy StatusEnum doesn't match ValidationInterface.StatusEnum"


    def create_vector_store(
        self,
        shared_id: str,
        name: str,
        user_id: str,
        vector_size: int,
        distance_metric: str,
        config: Optional[dict] = None
    ) -> ValidationInterface.VectorStoreRead:
        """Creates the VectorStore metadata record in the database."""
        new_store = VectorStore( # Use SQLAlchemy Model
            id=shared_id,
            name=name,
            user_id=user_id,
            collection_name=shared_id,
            vector_size=vector_size,
            distance_metric=distance_metric,
            config=config or {},
            created_at=int(time.time()),
            status=StatusEnum.active, # Use the imported StatusEnum
            file_count=0
        )
        self.db.add(new_store)
        try:
            self.db.commit()
            self.db.refresh(new_store)
            return ValidationInterface.VectorStoreRead.model_validate(new_store)
        except IntegrityError as e:
            self.db.rollback()
            if "Duplicate entry" in str(e.orig) or "violates unique constraint" in str(e.orig):
                 raise DatabaseConflictError(f"Vector store with ID/collection name '{shared_id}' already exists.") from e
            else:
                 raise VectorStoreDBError(f"Database error creating vector store: {str(e)}") from e
        except Exception as e:
            self.db.rollback()
            raise VectorStoreDBError(f"Unexpected error creating vector store: {str(e)}") from e

    def mark_vector_store_deleted(self, vector_store_id: str) -> ValidationInterface.VectorStoreRead:
        """Soft deletes a vector store record by ID."""
        store = self.db.get(VectorStore, vector_store_id)
        if not store:
            raise VectorStoreNotFoundError(f"Vector store ID '{vector_store_id}' not found.")

        if store.status == StatusEnum.deleted:
             return ValidationInterface.VectorStoreRead.model_validate(store)

        store.status = StatusEnum.deleted
        store.updated_at = int(time.time())
        try:
            self.db.commit()
            self.db.refresh(store)
            return ValidationInterface.VectorStoreRead.model_validate(store)
        except Exception as e:
            self.db.rollback()
            raise VectorStoreDBError(f"Database error marking vector store '{vector_store_id}' as deleted: {str(e)}") from e

    def permanently_delete_vector_store(self, vector_store_id: str) -> bool:
        """Permanently deletes a vector store record."""
        store = self.db.get(VectorStore, vector_store_id)
        if not store:
             raise VectorStoreNotFoundError(f"Vector store ID '{vector_store_id}' not found.")
        try:
            self.db.delete(store)
            self.db.commit()
            return True
        except Exception as e:
            self.db.rollback()
            raise VectorStoreDBError(f"Database error permanently deleting vector store '{vector_store_id}': {str(e)}") from e

    def get_vector_store_by_id(self, vector_store_id: str) -> Optional[ValidationInterface.VectorStoreRead]:
        """Retrieves a vector store by its primary ID."""
        store = self.db.get(VectorStore, vector_store_id)
        return ValidationInterface.VectorStoreRead.model_validate(store) if store else None

    def get_vector_store_by_collection_name(self, collection_name: str) -> Optional[ValidationInterface.VectorStoreRead]:
        """Retrieves a vector store by its unique collection name."""
        store = self.db.query(VectorStore).filter(VectorStore.collection_name == collection_name).first()
        return ValidationInterface.VectorStoreRead.model_validate(store) if store else None

    def get_stores_by_user(self, user_id: str) -> List[ValidationInterface.VectorStoreRead]:
        """Retrieves all non-deleted vector stores owned by a specific user."""
        stores = self.db.query(VectorStore).filter(
            VectorStore.user_id == user_id,
            VectorStore.status != StatusEnum.deleted
        ).all()
        return [ValidationInterface.VectorStoreRead.model_validate(store) for store in stores]

    # --- VectorStoreFile Management ---

    # --- !!! CORRECTED METHOD !!! ---
    def create_vector_store_file(
        self,
        vector_store_id: str,
        file_id: str,  # This is the unique ID for the VectorStoreFile record
        file_name: str,
        file_path: str,
        status: StatusEnum = StatusEnum.completed, # Use validation enum for input consistency
        meta_data: Optional[dict] = None
    ) -> ValidationInterface.VectorStoreFileRead: # Return the Pydantic Read model
        """
        Creates a VectorStoreFile database record and increments the store's file count.
        """
        store = self.db.get(VectorStore, vector_store_id)
        if not store or store.status == StatusEnum.deleted: # Use validation enum
            raise VectorStoreNotFoundError(
                f"Vector store '{vector_store_id}' not found or is deleted."
            )

        # --- Instantiate the SQLAlchemy Model ---
        db_file_record = VectorStoreFile( # Use the DB model class
            id=file_id,                # Map 'file_id' input to the 'id' DB column
            vector_store_id=vector_store_id,
            file_name=file_name,
            file_path=file_path,
            status=status,             # Use the StatusEnum value directly
            meta_data=meta_data or {}, # Map 'meta_data' input to 'meta_data' column
            processed_at=int(time.time()) if status == StatusEnum.completed else None,
        )
        # --- END CORRECTION ---

        # Update parent store count and timestamp
        store.file_count = VectorStore.file_count + 1
        store.updated_at = int(time.time())

        # Add the SQLAlchemy model instance to the session
        self.db.add(db_file_record) # Add the DB model instance

        try:
            self.db.commit()
            # Refresh the SQLAlchemy model instance
            self.db.refresh(db_file_record) # Refresh the DB model instance
            # Validate the refreshed DB model instance into the Pydantic Read model
            return ValidationInterface.VectorStoreFileRead.model_validate(db_file_record)
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
    # --- !!! END CORRECTED METHOD !!! ---


    def delete_vector_store_file_by_path(self, vector_store_id: str, file_path: str) -> bool:
        """Deletes a VectorStoreFile record by path and decrements file count."""
        store = self.db.get(VectorStore, vector_store_id)
        if not store:
            raise VectorStoreNotFoundError(f"Vector store '{vector_store_id}' not found.")

        file_to_delete = self.db.query(VectorStoreFile).filter(
            VectorStoreFile.vector_store_id == vector_store_id,
            VectorStoreFile.file_path == file_path
        ).first()

        if not file_to_delete:
             raise VectorStoreFileNotFoundError(f"File with path '{file_path}' not found in store '{vector_store_id}'.")

        store.file_count = VectorStore.file_count - 1
        if store.file_count < 0: store.file_count = 0
        store.updated_at = int(time.time())

        try:
            self.db.delete(file_to_delete)
            self.db.commit()
            return True
        except Exception as e:
            self.db.rollback()
            raise VectorStoreDBError(f"Database error deleting file record '{file_path}' from store '{vector_store_id}': {str(e)}") from e

    def list_vector_store_files(
        self, vector_store_id: str
    ) -> List[ValidationInterface.VectorStoreFileRead]:
        """Lists all non-deleted files associated with a vector store."""
        store = self.db.get(VectorStore, vector_store_id)
        if not store or store.status == StatusEnum.deleted:
             return []

        files = store.files.filter(VectorStoreFile.status != StatusEnum.deleted).all()
        return [ValidationInterface.VectorStoreFileRead.model_validate(f) for f in files]

    def update_vector_store_file_status(
        self,
        file_id: str,
        status: StatusEnum,
        error_message: Optional[str] = None
    ) -> ValidationInterface.VectorStoreFileRead:
        """Updates the status and potentially error message of a file record."""
        file_record = self.db.get(VectorStoreFile, file_id)
        if not file_record:
            raise VectorStoreFileNotFoundError(f"File record with ID '{file_id}' not found.")

        file_record.status = status
        file_record.error_message = error_message
        if status in [StatusEnum.completed, StatusEnum.failed]:
            file_record.processed_at = int(time.time())

        if file_record.vector_store:
            file_record.vector_store.updated_at = int(time.time())

        try:
            self.db.commit()
            self.db.refresh(file_record)
            return ValidationInterface.VectorStoreFileRead.model_validate(file_record)
        except Exception as e:
            self.db.rollback()
            raise VectorStoreDBError(f"Database error updating status for file record '{file_id}': {str(e)}") from e

    # --- Assistant Attachment ---

    def attach_vector_store_to_assistant(self, vector_store_id: str, assistant_id: str) -> bool:
        """Attaches a vector store to an assistant."""
        vector_store = self.db.get(VectorStore, vector_store_id)
        if not vector_store or vector_store.status == StatusEnum.deleted:
            raise VectorStoreNotFoundError(f"Vector store '{vector_store_id}' not found or is deleted.")

        assistant = self.db.get(Assistant, assistant_id)
        if not assistant:
             raise AssistantNotFoundError(f"Assistant '{assistant_id}' not found.")

        if vector_store in assistant.vector_stores:
            return True # Already attached

        assistant.vector_stores.append(vector_store)
        try:
            self.db.commit()
            return True
        except Exception as e:
            self.db.rollback()
            raise VectorStoreDBError(f"Database error attaching store '{vector_store_id}' to assistant '{assistant_id}': {str(e)}") from e

    def detach_vector_store_from_assistant(self, vector_store_id: str, assistant_id: str) -> bool:
        """Detaches a vector store from an assistant."""
        assistant = self.db.query(Assistant).options(
            joinedload(Assistant.vector_stores)
        ).filter(Assistant.id == assistant_id).first()

        if not assistant:
             raise AssistantNotFoundError(f"Assistant '{assistant_id}' not found.")

        vector_store_to_remove = next((vs for vs in assistant.vector_stores if vs.id == vector_store_id), None)

        if vector_store_to_remove:
            assistant.vector_stores.remove(vector_store_to_remove)
            try:
                self.db.commit()
                return True
            except Exception as e:
                self.db.rollback()
                raise VectorStoreDBError(f"Database error detaching store '{vector_store_id}' from assistant '{assistant_id}': {str(e)}") from e
        else:
            return True # Idempotent: Already detached


    def get_vector_stores_for_assistant(
        self, assistant_id: str
    ) -> List[ValidationInterface.VectorStoreRead]:
        """Retrieves all non-deleted vector stores attached to an assistant."""
        assistant = self.db.query(Assistant).options(
            joinedload(Assistant.vector_stores)
        ).filter(Assistant.id == assistant_id).first()

        if not assistant:
            return []

        active_stores = [vs for vs in assistant.vector_stores if vs.status != StatusEnum.deleted]
        return [ValidationInterface.VectorStoreRead.model_validate(vs) for vs in active_stores]
