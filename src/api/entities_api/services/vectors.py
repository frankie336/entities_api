"""
fixed_vector_store_api.py

This file includes the complete code for the vector store service, API endpoints,
and validation models with the fixes applied to update the file count correctly.
"""

import time
from typing import List, Optional, Dict, Any
import logging

# Import common validation models and StatusEnum
from entities_common import UtilsInterface, ValidationInterface

StatusEnum = ValidationInterface.StatusEnum  # Use the one from ValidationInterface

from sqlalchemy.exc import IntegrityError  # To catch duplicate key errors
from sqlalchemy.orm import Session, joinedload

# Import specific DB Models
from entities_api.models.models import (
    VectorStore,
    Assistant,
    VectorStoreFile,
)

# Get the logger instance
logging_utility = UtilsInterface.LoggingUtility()

# --- Define Service-Level Exceptions ---
class VectorStoreDBError(Exception):
    pass


class VectorStoreNotFoundError(VectorStoreDBError):
    pass


class VectorStoreFileError(VectorStoreDBError):
    pass


class VectorStoreFileNotFoundError(VectorStoreFileError):
    pass


class AssistantNotFoundError(VectorStoreDBError):
    pass


class DatabaseConflictError(VectorStoreDBError):
    pass


# --- Service Class ---
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
        config: Optional[dict] = None,
    ) -> ValidationInterface.VectorStoreRead:
        """Creates the VectorStore metadata record in the database."""
        new_store = VectorStore(
            id=shared_id,
            name=name,
            user_id=user_id,
            collection_name=shared_id,
            vector_size=vector_size,
            distance_metric=distance_metric,
            config=config or {},
            created_at=int(time.time()),
            status=StatusEnum.active,
            file_count=0,
        )
        self.db.add(new_store)
        try:
            self.db.commit()
            self.db.refresh(new_store)
            return ValidationInterface.VectorStoreRead.model_validate(new_store)
        except IntegrityError as e:
            self.db.rollback()
            if "Duplicate entry" in str(e.orig) or "violates unique constraint" in str(e.orig):
                raise DatabaseConflictError(f"Store ID '{shared_id}' exists.") from e
            else:
                raise VectorStoreDBError(f"DB error creating store: {e}") from e
        except Exception as e:
            self.db.rollback()
            logging_utility.error(
                f"Unexpected error creating vector store or validating result: {e}"
            )
            raise VectorStoreDBError(f"Unexpected error creating vector store: {e}") from e

    def mark_vector_store_deleted(
        self, vector_store_id: str
    ) -> ValidationInterface.VectorStoreRead:
        """Soft deletes a vector store record by ID."""
        store = self.db.get(VectorStore, vector_store_id)
        if not store:
            raise VectorStoreNotFoundError(f"Store ID '{vector_store_id}' not found.")
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
            raise VectorStoreDBError(f"DB error marking store deleted: {e}") from e

    def permanently_delete_vector_store(self, vector_store_id: str) -> bool:
        """Permanently deletes a vector store record."""
        store = self.db.get(VectorStore, vector_store_id)
        if not store:
            raise VectorStoreNotFoundError(f"Store ID '{vector_store_id}' not found.")
        try:
            self.db.delete(store)
            self.db.commit()
            return True
        except Exception as e:
            self.db.rollback()
            raise VectorStoreDBError(f"DB error permanently deleting store: {e}") from e

    def get_vector_store_by_id(
        self, vector_store_id: str
    ) -> Optional[ValidationInterface.VectorStoreRead]:
        """Retrieves a vector store by its primary ID."""
        store = self.db.get(VectorStore, vector_store_id)
        return ValidationInterface.VectorStoreRead.model_validate(store) if store else None

    def get_vector_store_by_collection_name(
        self, collection_name: str
    ) -> Optional[ValidationInterface.VectorStoreRead]:
        """Retrieves a vector store by its unique collection name."""
        store = (
            self.db.query(VectorStore)
            .filter(VectorStore.collection_name == collection_name)
            .first()
        )
        return ValidationInterface.VectorStoreRead.model_validate(store) if store else None

    def get_stores_by_user(self, user_id: str) -> List[ValidationInterface.VectorStoreRead]:
        """Retrieves all non-deleted vector stores owned by a specific user."""
        stores = (
            self.db.query(VectorStore)
            .filter(VectorStore.user_id == user_id, VectorStore.status != StatusEnum.deleted)
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
        status: StatusEnum = StatusEnum.completed,
        meta_data: Optional[dict] = None,
    ) -> ValidationInterface.VectorStoreFileRead:
        """
        Creates a VectorStoreFile database record and increments the store's file count.
        """
        store = self.db.get(VectorStore, vector_store_id)
        if not store or store.status == StatusEnum.deleted:
            raise VectorStoreNotFoundError(
                f"Vector store '{vector_store_id}' not found or is deleted."
            )

        if meta_data is not None and not isinstance(meta_data, dict):
            logging_utility.warning(
                f"Input meta_data for file '{file_id}' is not a dict (type: {type(meta_data)}). Using empty dict."
            )
            meta_data = {}

        db_file_record = VectorStoreFile(
            id=file_id,
            vector_store_id=vector_store_id,
            file_name=file_name,
            file_path=file_path,
            status=status,
            meta_data=meta_data or {},
            processed_at=int(time.time()) if status == StatusEnum.completed else None,
        )
        # FIX: update the instance's file_count instead of referencing the class attribute
        store.file_count += 1
        store.updated_at = int(time.time())

        self.db.add(db_file_record)
        validation_error = None
        try:
            self.db.commit()
            self.db.refresh(db_file_record)
            try:
                validated_model = ValidationInterface.VectorStoreFileRead.model_validate(db_file_record)
                return validated_model
            except Exception as e:
                validation_error = e
                logging_utility.error(
                    f"Pydantic validation failed for VectorStoreFileRead on file ID {db_file_record.id}: {validation_error}"
                )
                raise validation_error
        except IntegrityError as e:
            self.db.rollback()
            if "Duplicate entry" in str(e.orig) or "violates unique constraint" in str(e.orig):
                raise DatabaseConflictError(f"File ID '{file_id}' exists.") from e
            else:
                raise VectorStoreDBError(f"DB error creating file record: {e}") from e
        except Exception as e:
            self.db.rollback()
            if validation_error:
                raise VectorStoreDBError(
                    f"Validation failed for created file record: {str(validation_error)}"
                ) from validation_error
            else:
                raise VectorStoreDBError(f"Unexpected error creating file record: {str(e)}") from e

    def delete_vector_store_file_by_path(self, vector_store_id: str, file_path: str) -> bool:
        """Deletes a VectorStoreFile record by path and decrements file count."""
        store = self.db.get(VectorStore, vector_store_id)
        if not store:
            raise VectorStoreNotFoundError(f"Store '{vector_store_id}' not found.")
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
                f"File path '{file_path}' not found in store '{vector_store_id}'."
            )
        # FIX: decrement the file_count on the instance safely
        store.file_count = max(store.file_count - 1, 0)
        store.updated_at = int(time.time())
        try:
            self.db.delete(file_to_delete)
            self.db.commit()
            return True
        except Exception as e:
            self.db.rollback()
            raise VectorStoreDBError(f"DB error deleting file record: {e}") from e

    def list_vector_store_files(
        self, vector_store_id: str
    ) -> List[ValidationInterface.VectorStoreFileRead]:
        """Lists all non-deleted files associated with a vector store."""
        store = self.db.get(VectorStore, vector_store_id)
        if not store or store.status == StatusEnum.deleted:
            return []
        files = store.files.filter(VectorStoreFile.status != StatusEnum.deleted).all()
        validated_files = []
        for f in files:
            try:
                validated_files.append(ValidationInterface.VectorStoreFileRead.model_validate(f))
            except Exception as e:
                logging_utility.error(
                    f"Pydantic validation failed for file ID {f.id} during list: {e}"
                )
                continue
        return validated_files

    def update_vector_store_file_status(
        self, file_id: str, status: StatusEnum, error_message: Optional[str] = None
    ) -> ValidationInterface.VectorStoreFileRead:
        """Updates the status and potentially error message of a file record."""
        file_record = self.db.get(VectorStoreFile, file_id)
        if not file_record:
            raise VectorStoreFileNotFoundError(f"File ID '{file_id}' not found.")
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
            raise VectorStoreDBError(f"DB error updating file status: {e}") from e

    # --- Assistant Attachment ---

    def attach_vector_store_to_assistant(self, vector_store_id: str, assistant_id: str) -> bool:
        """Attaches a vector store to an assistant."""
        vector_store = self.db.get(VectorStore, vector_store_id)
        if not vector_store or vector_store.status == StatusEnum.deleted:
            raise VectorStoreNotFoundError(f"Store '{vector_store_id}' not found/deleted.")
        assistant = self.db.get(Assistant, assistant_id)
        if not assistant:
            raise AssistantNotFoundError(f"Assistant '{assistant_id}' not found.")
        if vector_store in assistant.vector_stores:
            return True
        assistant.vector_stores.append(vector_store)
        try:
            self.db.commit()
            return True
        except Exception as e:
            self.db.rollback()
            raise VectorStoreDBError(f"DB error attaching store: {e}") from e

    def detach_vector_store_from_assistant(self, vector_store_id: str, assistant_id: str) -> bool:
        """Detaches a vector store from an assistant."""
        assistant = (
            self.db.query(Assistant)
            .options(joinedload(Assistant.vector_stores))
            .filter(Assistant.id == assistant_id)
            .first()
        )
        if not assistant:
            raise AssistantNotFoundError(f"Assistant '{assistant_id}' not found.")
        vector_store_to_remove = next(
            (vs for vs in assistant.vector_stores if vs.id == vector_store_id), None
        )
        if vector_store_to_remove:
            assistant.vector_stores.remove(vector_store_to_remove)
            try:
                self.db.commit()
                return True
            except Exception as e:
                self.db.rollback()
                raise VectorStoreDBError(f"DB error detaching store: {e}") from e
        else:
            return True  # Idempotent

    def get_vector_stores_for_assistant(
        self, assistant_id: str
    ) -> List[ValidationInterface.VectorStoreRead]:
        """Retrieves all non-deleted vector stores attached to an assistant."""
        assistant = (
            self.db.query(Assistant)
            .options(joinedload(Assistant.vector_stores))
            .filter(Assistant.id == assistant_id)
            .first()
        )
        if not assistant:
            return []
        active_stores = [vs for vs in assistant.vector_stores if vs.status != StatusEnum.deleted]
        return [ValidationInterface.VectorStoreRead.model_validate(vs) for vs in active_stores]


# --- API Endpoints ---
from fastapi import APIRouter, Depends, HTTPException, Query, Path as FastApiPath
from entities_api.dependencies import get_db

router = APIRouter()

@router.post(
    "/vector-stores",
    response_model=ValidationInterface.VectorStoreRead,
    status_code=201,
    summary="Create Vector Store",
    description="Creates a new vector store metadata record in the database.",
)
def create_vector_store_endpoint(
    vector_store_data: ValidationInterface.VectorStoreCreateWithSharedId,
    db: Session = Depends(get_db),
):
    vector_service = VectorStoreDBService(db)
    logging_utility.info(
        f"Received request to create vector store: Name='{vector_store_data.name}', "
        f"ID='{vector_store_data.shared_id}'"
    )
    try:
        store = vector_service.create_vector_store(
            shared_id=vector_store_data.shared_id,
            name=vector_store_data.name,
            user_id=vector_store_data.user_id,
            vector_size=vector_store_data.vector_size,
            distance_metric=vector_store_data.distance_metric,
            config=vector_store_data.config,
        )
        logging_utility.info(f"Successfully created vector store record in DB: {store.id}")
        return store
    except DatabaseConflictError as e:
        logging_utility.warning(f"Conflict creating vector store ID {vector_store_data.shared_id}: {e}")
        raise HTTPException(status_code=409, detail=str(e))
    except VectorStoreDBError as e:
        logging_utility.error(
            f"Error creating vector store DB record for ID {vector_store_data.shared_id}: {str(e)}"
        )
        raise HTTPException(
            status_code=500, detail=f"Internal server error during vector store creation: {str(e)}"
        )
    except Exception as e:
        logging_utility.exception(
            f"Unexpected error creating vector store DB record for ID {vector_store_data.shared_id}: {str(e)}"
        )
        raise HTTPException(status_code=500, detail="An unexpected internal server error occurred.")


@router.delete(
    "/vector-stores/{vector_store_id}",
    status_code=204,
    summary="Delete Vector Store",
    description="Deletes or marks a vector store record as deleted.",
)
def delete_vector_store_endpoint(
    vector_store_id: str = FastApiPath(..., description="The ID of the vector store to delete."),
    permanent: bool = Query(
        False, description="Permanently delete the record and associated data via cascade."
    ),
    db: Session = Depends(get_db),
):
    vector_service = VectorStoreDBService(db)
    logging_utility.info(
        f"Request to {'permanently' if permanent else 'soft'} delete vector store: {vector_store_id}"
    )
    try:
        if permanent:
            _ = vector_service.permanently_delete_vector_store(vector_store_id)
        else:
            _ = vector_service.mark_vector_store_deleted(vector_store_id)
        logging_utility.info(
            f"Successfully {'permanently' if permanent else 'soft'} deleted vector store: {vector_store_id}"
        )
        return None
    except VectorStoreNotFoundError as e:
        logging_utility.warning(f"Delete failed: {e}")
        raise HTTPException(status_code=404, detail=str(e))
    except VectorStoreDBError as e:
        logging_utility.error(
            f"Error during deletion of vector store record '{vector_store_id}': {str(e)}"
        )
        raise HTTPException(
            status_code=500, detail=f"Failed to delete vector store record: {str(e)}"
        )
    except Exception as e:
        logging_utility.exception(
            f"Unexpected error deleting vector store '{vector_store_id}': {str(e)}"
        )
        raise HTTPException(status_code=500, detail="An unexpected internal server error occurred.")


@router.get(
    "/vector-stores/{vector_store_id}",
    response_model=ValidationInterface.VectorStoreRead,
    summary="Get Vector Store",
    description="Retrieves metadata for a specific vector store by its ID.",
)
def get_vector_store_endpoint(
    vector_store_id: str = FastApiPath(..., description="The ID of the vector store to retrieve."),
    db: Session = Depends(get_db),
):
    vector_service = VectorStoreDBService(db)
    store = vector_service.get_vector_store_by_id(vector_store_id)
    if not store:
        raise HTTPException(status_code=404, detail=f"Vector store '{vector_store_id}' not found.")
    return store


@router.get(
    "/vector-stores/lookup/collection",
    response_model=ValidationInterface.VectorStoreRead,
    summary="Get Vector Store by Collection Name",
    description="Retrieves vector store metadata using its unique collection name.",
)
def retrieve_vector_store_by_collection_endpoint(
    name: str = Query(..., description="The unique collection name (usually the vector store ID) to look up."),
    db: Session = Depends(get_db),
):
    vector_service = VectorStoreDBService(db)
    store = vector_service.get_vector_store_by_collection_name(name)
    if not store:
        raise HTTPException(status_code=404, detail=f"Vector store with collection name '{name}' not found.")
    return store


@router.get(
    "/users/{user_id}/vector-stores",
    response_model=List[ValidationInterface.VectorStoreRead],
    summary="List User's Vector Stores",
    description="Retrieves a list of non-deleted vector stores owned by a specific user.",
)
def get_stores_by_user_endpoint(
    user_id: str = FastApiPath(..., description="The ID of the user whose vector stores to list."),
    db: Session = Depends(get_db),
):
    vector_service = VectorStoreDBService(db)
    try:
        stores = vector_service.get_stores_by_user(user_id)
        return stores
    except Exception as e:
        logging_utility.error(f"Error fetching stores for user {user_id}: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to fetch vector stores")


@router.post(
    "/vector-stores/{vector_store_id}/files",
    response_model=ValidationInterface.VectorStoreFileRead,
    status_code=201,
    summary="Add File Record to Vector Store",
    description="Registers a file's metadata associated with a specific vector store.",
)
def add_file_to_vector_store_endpoint(
    file_data: ValidationInterface.VectorStoreFileCreate,
    vector_store_id: str = FastApiPath(
        ..., description="The ID of the vector store to add the file record to."
    ),
    db: Session = Depends(get_db),
):
    vector_service = VectorStoreDBService(db)
    logging_utility.info(
        f"Request to add file record '{file_data.file_name}' (ID: {file_data.file_id}, "
        f"Path: {file_data.file_path}) to store {vector_store_id}"
    )
    try:
        file_record = vector_service.create_vector_store_file(
            vector_store_id=vector_store_id,
            file_id=file_data.file_id,
            file_name=file_data.file_name,
            file_path=file_data.file_path,
            status=file_data.status or ValidationInterface.StatusEnum.completed,
            meta_data=file_data.metadata,
        )
        logging_utility.info(
            f"Successfully created file record {file_record.id} for store {vector_store_id}"
        )
        return file_record
    except VectorStoreNotFoundError as e:
        logging_utility.warning(f"Cannot add file record: {e}")
        raise HTTPException(status_code=404, detail=str(e))
    except DatabaseConflictError as e:
        logging_utility.warning(f"Conflict creating file record: {e}")
        raise HTTPException(status_code=409, detail=str(e))
    except VectorStoreDBError as e:
        logging_utility.error(f"Error creating file record for store '{vector_store_id}': {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to create file record: {str(e)}")
    except Exception as e:
        logging_utility.exception(
            f"Unexpected error creating file record for store '{vector_store_id}': {str(e)}"
        )
        raise HTTPException(status_code=500, detail="An unexpected internal server error occurred.")


@router.get(
    "/vector-stores/{vector_store_id}/files",
    response_model=List[ValidationInterface.VectorStoreFileRead],
    summary="List Files in Vector Store",
    description="Retrieves metadata for all non-deleted files associated with a vector store.",
)
def list_files_in_vector_store_endpoint(
    vector_store_id: str = FastApiPath(..., description="The ID of the vector store whose files to list."),
    db: Session = Depends(get_db),
):
    vector_service = VectorStoreDBService(db)
    try:
        files = vector_service.list_vector_store_files(vector_store_id)
        return files
    except Exception as e:
        logging_utility.error(f"Error listing files for store '{vector_store_id}': {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to list files: {str(e)}")


@router.delete(
    "/vector-stores/{vector_store_id}/files",
    status_code=204,
    summary="Delete File Record from Vector Store",
    description="Deletes a file's metadata record associated with a vector store, identified by file path.",
)
def delete_file_from_vector_store_endpoint(
    vector_store_id: str = FastApiPath(..., description="The ID of the vector store containing the file record."),
    file_path: str = Query(..., description="The file path identifier used when adding the file."),
    db: Session = Depends(get_db),
):
    vector_service = VectorStoreDBService(db)
    logging_utility.info(
        f"Request to delete file record with path '{file_path}' from store {vector_store_id}"
    )
    try:
        _ = vector_service.delete_vector_store_file_by_path(vector_store_id, file_path)
        logging_utility.info(
            f"Successfully deleted file record with path '{file_path}' from store {vector_store_id}"
        )
        return None
    except (VectorStoreNotFoundError, VectorStoreFileNotFoundError) as e:
        logging_utility.warning(f"Delete file record failed: {e}")
        raise HTTPException(status_code=404, detail=str(e))
    except VectorStoreDBError as e:
        logging_utility.error(
            f"Error deleting file record '{file_path}' from store '{vector_store_id}': {str(e)}"
        )
        raise HTTPException(status_code=500, detail=f"Failed to delete file record: {str(e)}")
    except Exception as e:
        logging_utility.exception(
            f"Unexpected error deleting file record '{file_path}' from store '{vector_store_id}': {str(e)}"
        )
        raise HTTPException(status_code=500, detail="An unexpected internal server error occurred.")


@router.patch(
    "/vector-stores/{vector_store_id}/files/{file_id}",
    response_model=ValidationInterface.VectorStoreFileRead,
    summary="Update Vector Store File Status",
    description="Updates the processing status and optionally the error message for a file record.",
)
def update_vector_store_file_status_endpoint(
    file_id: str = FastApiPath(..., description="The ID of the file record to update."),
    vector_store_id: str = FastApiPath(..., description="The ID of the vector store owning the file record."),
    file_status: ValidationInterface.VectorStoreFileUpdateStatus = ...,
    db: Session = Depends(get_db),
):
    vector_service = VectorStoreDBService(db)
    try:
        updated_file = vector_service.update_vector_store_file_status(
            file_id, file_status.status, file_status.error_message
        )
        return updated_file
    except VectorStoreFileNotFoundError as e:
        logging_utility.warning(f"Update file status failed: {e}")
        raise HTTPException(status_code=404, detail=str(e))
    except VectorStoreDBError as e:
        logging_utility.error(f"Error updating file status for file '{file_id}': {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to update file status: {str(e)}")
    except Exception as e:
        logging_utility.exception(f"Unexpected error updating file status for file '{file_id}': {str(e)}")
        raise HTTPException(status_code=500, detail="An unexpected internal server error occurred.")


@router.post(
    "/assistants/{assistant_id}/vector-stores/{vector_store_id}/attach",
    status_code=200,
    response_model=Dict[str, bool],
    summary="Attach Vector Store to Assistant",
    description="Creates an association between an assistant and a vector store.",
)
def attach_vector_store_to_assistant_endpoint(
    assistant_id: str = FastApiPath(..., description="The ID of the assistant."),
    vector_store_id: str = FastApiPath(..., description="The ID of the vector store to attach."),
    db: Session = Depends(get_db),
):
    vector_service = VectorStoreDBService(db)
    logging_utility.info(
        f"Request to attach vector store '{vector_store_id}' to assistant '{assistant_id}'."
    )
    try:
        _ = vector_service.attach_vector_store_to_assistant(vector_store_id, assistant_id)
        logging_utility.info(
            f"Attach successful for store '{vector_store_id}' to assistant '{assistant_id}'."
        )
        return {"success": True}
    except (VectorStoreNotFoundError, AssistantNotFoundError) as e:
        logging_utility.warning(f"Attach failed: {e}")
        raise HTTPException(status_code=404, detail=str(e))
    except VectorStoreDBError as e:
        logging_utility.error(
            f"Error attaching store '{vector_store_id}' to assistant '{assistant_id}': {str(e)}"
        )
        raise HTTPException(status_code=500, detail=f"Failed to attach vector store: {str(e)}")
    except Exception as e:
        logging_utility.exception(
            f"Unexpected error attaching store '{vector_store_id}' to assistant '{assistant_id}': {str(e)}"
        )
        raise HTTPException(status_code=500, detail="An unexpected internal server error occurred.")


@router.delete(
    "/assistants/{assistant_id}/vector-stores/{vector_store_id}/detach",
    status_code=200,
    response_model=Dict[str, bool],
    summary="Detach Vector Store from Assistant",
    description="Removes the association between an assistant and a vector store.",
)
def detach_vector_store_from_assistant_endpoint(
    assistant_id: str = FastApiPath(..., description="The ID of the assistant."),
    vector_store_id: str = FastApiPath(..., description="The ID of the vector store to detach."),
    db: Session = Depends(get_db),
):
    vector_service = VectorStoreDBService(db)
    logging_utility.info(
        f"Request to detach vector store '{vector_store_id}' from assistant '{assistant_id}'."
    )
    try:
        _ = vector_service.detach_vector_store_from_assistant(vector_store_id, assistant_id)
        logging_utility.info(
            f"Detach successful for store '{vector_store_id}' from assistant '{assistant_id}'."
        )
        return {"success": True}
    except AssistantNotFoundError as e:
        logging_utility.warning(f"Detach failed: {e}")
        raise HTTPException(status_code=404, detail=str(e))
    except VectorStoreDBError as e:
        logging_utility.error(
            f"Error detaching store '{vector_store_id}' from assistant '{assistant_id}': {str(e)}"
        )
        raise HTTPException(status_code=500, detail=f"Failed to detach vector store: {str(e)}")
    except Exception as e:
        logging_utility.exception(
            f"Unexpected error detaching store '{vector_store_id}' from assistant '{assistant_id}': {str(e)}"
        )
        raise HTTPException(status_code=500, detail="An unexpected internal server error occurred.")


@router.get(
    "/assistants/{assistant_id}/vector-stores",
    response_model=List[ValidationInterface.VectorStoreRead],
    summary="List Assistant's Vector Stores",
    description="Retrieves a list of vector stores currently attached to an assistant.",
)
def get_vector_stores_for_assistant_endpoint(
    assistant_id: str = FastApiPath(..., description="The ID of the assistant whose stores to list."),
    db: Session = Depends(get_db),
):
    vector_service = VectorStoreDBService(db)
    try:
        stores = vector_service.get_vector_stores_for_assistant(assistant_id)
        return stores
    except Exception as e:
        logging_utility.error(f"Error fetching stores for assistant {assistant_id}: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to fetch assistant's vector stores")
