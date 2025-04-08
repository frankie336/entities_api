#! entities_api/routers/vectors.py
from typing import Dict, List

from fastapi import APIRouter, Depends, HTTPException
from fastapi import Path as FastApiPath
from fastapi import Query
from projectdavid_common import UtilsInterface, ValidationInterface
from sqlalchemy.orm import Session

from entities_api.dependencies import get_db

# Import specific exceptions from the service layer
from entities_api.services.vectors import (
    AssistantNotFoundError,
    DatabaseConflictError,
    VectorStoreDBError,
    VectorStoreDBService,
    VectorStoreFileNotFoundError,
    VectorStoreNotFoundError,
)

# Import the main interface and specific models/enums needed

router = APIRouter()
logging_utility = UtilsInterface.LoggingUtility()


@router.post(
    "/vector-stores",
    response_model=ValidationInterface.VectorStoreRead,  # Use imported model
    status_code=201,
    summary="Create Vector Store",
    description="Creates a new vector store metadata record in the database.",
)
def create_vector_store_endpoint(
    vector_store_data: ValidationInterface.VectorStoreCreateWithSharedId,  # Use imported model
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
        logging_utility.info(
            f"Successfully created vector store record in DB: {store.id}"
        )
        return store
    except DatabaseConflictError as e:
        logging_utility.warning(
            f"Conflict creating vector store ID {vector_store_data.shared_id}: {e}"
        )
        raise HTTPException(status_code=409, detail=str(e))
    except VectorStoreDBError as e:
        logging_utility.error(
            f"Error creating vector store DB record for ID {vector_store_data.shared_id}: {str(e)}"
        )
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error during vector store creation: {str(e)}",
        )
    except Exception as e:
        logging_utility.exception(
            f"Unexpected error creating vector store DB record for ID {vector_store_data.shared_id}: {str(e)}"
        )
        raise HTTPException(
            status_code=500, detail="An unexpected internal server error occurred."
        )


@router.delete(
    "/vector-stores/{vector_store_id}",
    status_code=204,
    summary="Delete Vector Store",
    description="Deletes or marks a vector store record as deleted.",
)
def delete_vector_store_endpoint(
    vector_store_id: str = FastApiPath(
        ..., description="The ID of the vector store to delete."
    ),
    permanent: bool = Query(
        False,
        description="Permanently delete the record and associated data via cascade.",
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
        raise HTTPException(
            status_code=500, detail="An unexpected internal server error occurred."
        )


@router.get(
    "/vector-stores/{vector_store_id}",
    response_model=ValidationInterface.VectorStoreRead,  # Use imported model
    summary="Get Vector Store",
    description="Retrieves metadata for a specific vector store by its ID.",
)
def get_vector_store_endpoint(
    vector_store_id: str = FastApiPath(
        ..., description="The ID of the vector store to retrieve."
    ),
    db: Session = Depends(get_db),
):
    vector_service = VectorStoreDBService(db)
    store = vector_service.get_vector_store_by_id(vector_store_id)
    if not store:
        raise HTTPException(
            status_code=404, detail=f"Vector store '{vector_store_id}' not found."
        )
    return store


@router.get(
    "/vector-stores/lookup/collection",
    response_model=ValidationInterface.VectorStoreRead,  # Use imported model
    summary="Get Vector Store by Collection Name",
    description="Retrieves vector store metadata using its unique collection name.",
)
def retrieve_vector_store_by_collection_endpoint(
    name: str = Query(
        ...,
        description="The unique collection name (usually the vector store ID) to look up.",
    ),
    db: Session = Depends(get_db),
):
    vector_service = VectorStoreDBService(db)
    store = vector_service.get_vector_store_by_collection_name(name)
    if not store:
        raise HTTPException(
            status_code=404,
            detail=f"Vector store with collection name '{name}' not found.",
        )
    return store


@router.get(
    "/users/{user_id}/vector-stores",
    response_model=List[ValidationInterface.VectorStoreRead],  # Use imported model
    summary="List User's Vector Stores",
    description="Retrieves a list of non-deleted vector stores owned by a specific user.",
)
def get_stores_by_user_endpoint(
    user_id: str = FastApiPath(
        ..., description="The ID of the user whose vector stores to list."
    ),
    db: Session = Depends(get_db),
):
    vector_service = VectorStoreDBService(db)
    try:
        stores = vector_service.get_stores_by_user(user_id)
        return stores
    except Exception as e:
        logging_utility.error(f"Error fetching stores for user {user_id}: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to fetch vector stores")


# --- Vector Store File Endpoints ---


@router.post(
    "/vector-stores/{vector_store_id}/files",
    response_model=ValidationInterface.VectorStoreFileRead,  # Use imported model
    status_code=201,
    summary="Add File Record to Vector Store",
    description="Registers a file's metadata associated with a specific vector store.",
)
def add_file_to_vector_store_endpoint(
    file_data: ValidationInterface.VectorStoreFileCreate,  # Body (No default) - comes first
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
            meta_data=file_data.meta_data,  # FIX: Use the correct field name from the model.
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
        logging_utility.error(
            f"Error creating file record for store '{vector_store_id}': {str(e)}"
        )
        raise HTTPException(
            status_code=500, detail=f"Failed to create file record: {str(e)}"
        )
    except Exception as e:
        logging_utility.exception(
            f"Unexpected error creating file record for store '{vector_store_id}': {str(e)}"
        )
        raise HTTPException(
            status_code=500, detail="An unexpected internal server error occurred."
        )


@router.get(
    "/vector-stores/{vector_store_id}/files",
    response_model=List[ValidationInterface.VectorStoreFileRead],  # Use imported model
    summary="List Files in Vector Store",
    description="Retrieves metadata for all non-deleted files associated with a vector store.",
)
def list_files_in_vector_store_endpoint(
    vector_store_id: str = FastApiPath(
        ..., description="The ID of the vector store whose files to list."
    ),
    db: Session = Depends(get_db),
):
    vector_service = VectorStoreDBService(db)
    try:
        files = vector_service.list_vector_store_files(vector_store_id)
        return files
    except Exception as e:
        logging_utility.error(
            f"Error listing files for store '{vector_store_id}': {str(e)}"
        )
        raise HTTPException(status_code=500, detail=f"Failed to list files: {str(e)}")


@router.delete(
    "/vector-stores/{vector_store_id}/files",
    status_code=204,
    summary="Delete File Record from Vector Store",
    description="Deletes a file's metadata record associated with a vector store, identified by file path.",
)
def delete_file_from_vector_store_endpoint(
    vector_store_id: str = FastApiPath(
        ..., description="The ID of the vector store containing the file record."
    ),
    file_path: str = Query(
        ..., description="The file path identifier used when adding the file."
    ),
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
        raise HTTPException(
            status_code=500, detail=f"Failed to delete file record: {str(e)}"
        )
    except Exception as e:
        logging_utility.exception(
            f"Unexpected error deleting file record '{file_path}' from store '{vector_store_id}': {str(e)}"
        )
        raise HTTPException(
            status_code=500, detail="An unexpected internal server error occurred."
        )


@router.patch(
    "/vector-stores/{vector_store_id}/files/{file_id}",
    response_model=ValidationInterface.VectorStoreFileRead,  # Use imported model
    summary="Update Vector Store File Status",
    description="Updates the processing status and optionally the error message for a file record.",
)
def update_vector_store_file_status_endpoint(
    file_id: str = FastApiPath(..., description="The ID of the file record to update."),
    vector_store_id: str = FastApiPath(
        ..., description="The ID of the vector store owning the file record."
    ),
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
        logging_utility.error(
            f"Error updating file status for file '{file_id}': {str(e)}"
        )
        raise HTTPException(
            status_code=500, detail=f"Failed to update file status: {str(e)}"
        )
    except Exception as e:
        logging_utility.exception(
            f"Unexpected error updating file status for file '{file_id}': {str(e)}"
        )
        raise HTTPException(
            status_code=500, detail="An unexpected internal server error occurred."
        )


@router.post(
    "/assistants/{assistant_id}/vector-stores/{vector_store_id}/attach",
    status_code=200,
    response_model=Dict[str, bool],
    summary="Attach Vector Store to Assistant",
    description="Creates an association between an assistant and a vector store.",
)
def attach_vector_store_to_assistant_endpoint(
    assistant_id: str = FastApiPath(..., description="The ID of the assistant."),
    vector_store_id: str = FastApiPath(
        ..., description="The ID of the vector store to attach."
    ),
    db: Session = Depends(get_db),
):
    vector_service = VectorStoreDBService(db)
    logging_utility.info(
        f"Request to attach vector store '{vector_store_id}' to assistant '{assistant_id}'."
    )
    try:
        _ = vector_service.attach_vector_store_to_assistant(
            vector_store_id, assistant_id
        )
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
        raise HTTPException(
            status_code=500, detail=f"Failed to attach vector store: {str(e)}"
        )
    except Exception as e:
        logging_utility.exception(
            f"Unexpected error attaching store '{vector_store_id}' to assistant '{assistant_id}': {str(e)}"
        )
        raise HTTPException(
            status_code=500, detail="An unexpected internal server error occurred."
        )


@router.delete(
    "/assistants/{assistant_id}/vector-stores/{vector_store_id}/detach",
    status_code=200,
    response_model=Dict[str, bool],
    summary="Detach Vector Store from Assistant",
    description="Removes the association between an assistant and a vector store.",
)
def detach_vector_store_from_assistant_endpoint(
    assistant_id: str = FastApiPath(..., description="The ID of the assistant."),
    vector_store_id: str = FastApiPath(
        ..., description="The ID of the vector store to detach."
    ),
    db: Session = Depends(get_db),
):
    vector_service = VectorStoreDBService(db)
    logging_utility.info(
        f"Request to detach vector store '{vector_store_id}' from assistant '{assistant_id}'."
    )
    try:
        _ = vector_service.detach_vector_store_from_assistant(
            vector_store_id, assistant_id
        )
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
        raise HTTPException(
            status_code=500, detail=f"Failed to detach vector store: {str(e)}"
        )
    except Exception as e:
        logging_utility.exception(
            f"Unexpected error detaching store '{vector_store_id}' from assistant '{assistant_id}': {str(e)}"
        )
        raise HTTPException(
            status_code=500, detail="An unexpected internal server error occurred."
        )


@router.get(
    "/assistants/{assistant_id}/vector-stores",
    response_model=List[ValidationInterface.VectorStoreRead],  # Use imported model
    summary="List Assistant's Vector Stores",
    description="Retrieves a list of vector stores currently attached to an assistant.",
)
def get_vector_stores_for_assistant_endpoint(
    assistant_id: str = FastApiPath(
        ..., description="The ID of the assistant whose stores to list."
    ),
    db: Session = Depends(get_db),
):
    vector_service = VectorStoreDBService(db)
    try:
        stores = vector_service.get_vector_stores_for_assistant(assistant_id)
        return stores
    except Exception as e:
        logging_utility.error(
            f"Error fetching stores for assistant {assistant_id}: {str(e)}"
        )
        raise HTTPException(
            status_code=500, detail="Failed to fetch assistant's vector stores"
        )
