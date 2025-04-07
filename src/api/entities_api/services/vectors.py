# entities_api/services/vectors.py

import time
from typing import List, Optional

# Import common validation models and StatusEnum
from entities_common import UtilsInterface, ValidationInterface

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

# Get the logger instance
logging_utility = UtilsInterface.LoggingUtility() # Or use standard logging: logger = logging.getLogger(__name__)


# --- Define Service-Level Exceptions ---
class VectorStoreDBError(Exception): pass
class VectorStoreNotFoundError(VectorStoreDBError): pass
class VectorStoreFileError(VectorStoreDBError): pass
class VectorStoreFileNotFoundError(VectorStoreFileError): pass
class AssistantNotFoundError(VectorStoreDBError): pass
class DatabaseConflictError(VectorStoreDBError): pass


# --- Updated Service Class ---

class VectorStoreDBService:
    def __init__(self, db: Session):
        self.db = db

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
        new_store = VectorStore(
            id=shared_id, name=name, user_id=user_id, collection_name=shared_id,
            vector_size=vector_size, distance_metric=distance_metric, config=config or {},
            created_at=int(time.time()), status=StatusEnum.active, file_count=0
        )
        self.db.add(new_store)
        try:
            self.db.commit(); self.db.refresh(new_store)
            return ValidationInterface.VectorStoreRead.model_validate(new_store)
        except IntegrityError as e:
            self.db.rollback()
            if "Duplicate entry" in str(e.orig) or "violates unique constraint" in str(e.orig): raise DatabaseConflictError(f"Store ID '{shared_id}' exists.") from e
            else: raise VectorStoreDBError(f"DB error creating store: {e}") from e
        except Exception as e:
            self.db.rollback()
            logging_utility.error(f"Unexpected error creating vector store or validating result: {e}")
            raise VectorStoreDBError(f"Unexpected error creating vector store: {e}") from e

    def mark_vector_store_deleted(self, vector_store_id: str) -> ValidationInterface.VectorStoreRead:
        """Soft deletes a vector store record by ID."""
        store = self.db.get(VectorStore, vector_store_id)
        if not store: raise VectorStoreNotFoundError(f"Store ID '{vector_store_id}' not found.")
        if store.status == StatusEnum.deleted: return ValidationInterface.VectorStoreRead.model_validate(store)
        store.status = StatusEnum.deleted; store.updated_at = int(time.time())
        try:
            self.db.commit(); self.db.refresh(store)
            return ValidationInterface.VectorStoreRead.model_validate(store)
        except Exception as e: self.db.rollback(); raise VectorStoreDBError(f"DB error marking store deleted: {e}") from e

    def permanently_delete_vector_store(self, vector_store_id: str) -> bool:
        """Permanently deletes a vector store record."""
        store = self.db.get(VectorStore, vector_store_id)
        if not store: raise VectorStoreNotFoundError(f"Store ID '{vector_store_id}' not found.")
        try: self.db.delete(store); self.db.commit(); return True
        except Exception as e: self.db.rollback(); raise VectorStoreDBError(f"DB error permanently deleting store: {e}") from e

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
        stores = self.db.query(VectorStore).filter(VectorStore.user_id == user_id, VectorStore.status != StatusEnum.deleted).all()
        return [ValidationInterface.VectorStoreRead.model_validate(store) for store in stores]

    # --- VectorStoreFile Management ---

    def create_vector_store_file(
        self,
        vector_store_id: str,
        file_id: str,
        file_name: str,
        file_path: str,
        status: StatusEnum = StatusEnum.completed,
        meta_data: Optional[dict] = None # Input parameter uses underscore
    ) -> ValidationInterface.VectorStoreFileRead:
        """
        Creates a VectorStoreFile database record and increments the store's file count.
        Relies on direct Pydantic validation from ORM object.
        """
        store = self.db.get(VectorStore, vector_store_id)
        if not store or store.status == StatusEnum.deleted:
            raise VectorStoreNotFoundError(f"Vector store '{vector_store_id}' not found or is deleted.")

        # Ensure input meta_data is dict or None
        if meta_data is not None and not isinstance(meta_data, dict):
             logging_utility.warning(f"Input meta_data for file '{file_id}' is not a dict (type: {type(meta_data)}). Using empty dict.")
             meta_data = {}

        db_file_record = VectorStoreFile(
            id=file_id,
            vector_store_id=vector_store_id,
            file_name=file_name,
            file_path=file_path,
            status=status,
            meta_data=meta_data or {}, # Assign to DB column 'meta_data'
            processed_at=int(time.time()) if status == StatusEnum.completed else None,
        )
        store.file_count = VectorStore.file_count + 1
        store.updated_at = int(time.time())

        self.db.add(db_file_record)
        validation_error = None
        try:
            self.db.commit()
            self.db.refresh(db_file_record)

            # Optional Debugging:
            # metadata_value = getattr(db_file_record, 'meta_data', 'AttributeMissing')
            # logging_utility.debug(f"Attempting direct validation for file ID {db_file_record.id}. meta_data type: {type(metadata_value)}, value: {metadata_value!r}")

            # Direct Validation Attempt
            try:
                # Pydantic model VectorStoreFileRead now expects 'meta_data' attribute
                validated_model = ValidationInterface.VectorStoreFileRead.model_validate(db_file_record)
                return validated_model
            except Exception as e:
                 validation_error = e
                 logging_utility.error(f"Pydantic validation failed for VectorStoreFileRead on file ID {db_file_record.id}: {validation_error}")
                 raise validation_error # Re-raise to be caught below

        except IntegrityError as e:
            self.db.rollback()
            if "Duplicate entry" in str(e.orig) or "violates unique constraint" in str(e.orig): raise DatabaseConflictError(f"File ID '{file_id}' exists.") from e
            else: raise VectorStoreDBError(f"DB error creating file record: {e}") from e
        except Exception as e:
            self.db.rollback()
            if validation_error: raise VectorStoreDBError(f"Validation failed for created file record: {str(validation_error)}") from validation_error
            else: raise VectorStoreDBError(f"Unexpected error creating file record: {str(e)}") from e

    def delete_vector_store_file_by_path(self, vector_store_id: str, file_path: str) -> bool:
        """Deletes a VectorStoreFile record by path and decrements file count."""
        store = self.db.get(VectorStore, vector_store_id)
        if not store: raise VectorStoreNotFoundError(f"Store '{vector_store_id}' not found.")
        file_to_delete = self.db.query(VectorStoreFile).filter(VectorStoreFile.vector_store_id == vector_store_id, VectorStoreFile.file_path == file_path).first()
        if not file_to_delete: raise VectorStoreFileNotFoundError(f"File path '{file_path}' not found in store '{vector_store_id}'.")
        store.file_count = VectorStore.file_count - 1
        if store.file_count < 0: store.file_count = 0
        store.updated_at = int(time.time())
        try: self.db.delete(file_to_delete); self.db.commit(); return True
        except Exception as e: self.db.rollback(); raise VectorStoreDBError(f"DB error deleting file record: {e}") from e

    def list_vector_store_files(self, vector_store_id: str) -> List[ValidationInterface.VectorStoreFileRead]:
        """Lists all non-deleted files associated with a vector store."""
        store = self.db.get(VectorStore, vector_store_id)
        if not store or store.status == StatusEnum.deleted: return []
        files = store.files.filter(VectorStoreFile.status != StatusEnum.deleted).all()
        validated_files = []
        for f in files:
             try:
                  # Direct validation now uses model with 'meta_data'
                  validated_files.append(ValidationInterface.VectorStoreFileRead.model_validate(f))
             except Exception as e:
                  logging_utility.error(f"Pydantic validation failed for file ID {f.id} during list: {e}")
                  continue
        return validated_files

    def update_vector_store_file_status(
        self, file_id: str, status: StatusEnum, error_message: Optional[str] = None
    ) -> ValidationInterface.VectorStoreFileRead:
        """Updates the status and potentially error message of a file record."""
        file_record = self.db.get(VectorStoreFile, file_id)
        if not file_record: raise VectorStoreFileNotFoundError(f"File ID '{file_id}' not found.")
        file_record.status = status; file_record.error_message = error_message
        if status in [StatusEnum.completed, StatusEnum.failed]: file_record.processed_at = int(time.time())
        if file_record.vector_store: file_record.vector_store.updated_at = int(time.time())
        try:
            self.db.commit(); self.db.refresh(file_record)
            # Direct validation now uses model with 'meta_data'
            return ValidationInterface.VectorStoreFileRead.model_validate(file_record)
        except Exception as e: self.db.rollback(); raise VectorStoreDBError(f"DB error updating file status: {e}") from e

    # --- Assistant Attachment ---

    def attach_vector_store_to_assistant(self, vector_store_id: str, assistant_id: str) -> bool:
        """Attaches a vector store to an assistant."""
        vector_store = self.db.get(VectorStore, vector_store_id)
        if not vector_store or vector_store.status == StatusEnum.deleted: raise VectorStoreNotFoundError(f"Store '{vector_store_id}' not found/deleted.")
        assistant = self.db.get(Assistant, assistant_id)
        if not assistant: raise AssistantNotFoundError(f"Assistant '{assistant_id}' not found.")
        if vector_store in assistant.vector_stores: return True
        assistant.vector_stores.append(vector_store)
        try: self.db.commit(); return True
        except Exception as e: self.db.rollback(); raise VectorStoreDBError(f"DB error attaching store: {e}") from e

    def detach_vector_store_from_assistant(self, vector_store_id: str, assistant_id: str) -> bool:
        """Detaches a vector store from an assistant."""
        assistant = self.db.query(Assistant).options(joinedload(Assistant.vector_stores)).filter(Assistant.id == assistant_id).first()
        if not assistant: raise AssistantNotFoundError(f"Assistant '{assistant_id}' not found.")
        vector_store_to_remove = next((vs for vs in assistant.vector_stores if vs.id == vector_store_id), None)
        if vector_store_to_remove:
            assistant.vector_stores.remove(vector_store_to_remove)
            try: self.db.commit(); return True
            except Exception as e: self.db.rollback(); raise VectorStoreDBError(f"DB error detaching store: {e}") from e
        else: return True # Idempotent

    def get_vector_stores_for_assistant(self, assistant_id: str) -> List[ValidationInterface.VectorStoreRead]:
        """Retrieves all non-deleted vector stores attached to an assistant."""
        assistant = self.db.query(Assistant).options(joinedload(Assistant.vector_stores)).filter(Assistant.id == assistant_id).first()
        if not assistant: return []
        active_stores = [vs for vs in assistant.vector_stores if vs.status != StatusEnum.deleted]
        # Direct validation assumes VectorStoreRead handles its fields correctly
        return [ValidationInterface.VectorStoreRead.model_validate(vs) for vs in active_stores]
