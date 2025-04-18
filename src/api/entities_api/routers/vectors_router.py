from typing import Dict, List

from fastapi import APIRouter, Depends, HTTPException
from fastapi import Path as FastApiPath
from fastapi import Query
from projectdavid_common import UtilsInterface, ValidationInterface
from sqlalchemy.orm import Session

from entities_api.dependencies import get_db
from entities_api.services.vectors import (AssistantNotFoundError,
                                           DatabaseConflictError,
                                           VectorStoreDBError,
                                           VectorStoreDBService,
                                           VectorStoreFileNotFoundError,
                                           VectorStoreNotFoundError)

router = APIRouter()
logging_utility = UtilsInterface.LoggingUtility()


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
    svc = VectorStoreDBService(db)
    logging_utility.info(
        f"Received create request: name={vector_store_data.name} id={vector_store_data.shared_id}"
    )
    try:
        store = svc.create_vector_store(
            shared_id=vector_store_data.shared_id,
            name=vector_store_data.name,
            user_id=vector_store_data.user_id,
            vector_size=vector_store_data.vector_size,
            distance_metric=vector_store_data.distance_metric,
            config=vector_store_data.config,
        )
        logging_utility.info(f"Created vector store record: {store.id}")
        return store

    except DatabaseConflictError as e:
        logging_utility.warning(f"Conflict on create: {e}")
        raise HTTPException(status_code=409, detail=str(e))

    except VectorStoreDBError as e:
        logging_utility.error(f"DB error on create: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error during creation: {e}",
        )

    except Exception as e:
        logging_utility.exception(f"Unexpected on create: {e}")
        raise HTTPException(status_code=500, detail="Unexpected internal error.")


@router.delete(
    "/vector-stores/{vector_store_id}",
    status_code=204,
    summary="Delete Vector Store",
    description="Deletes or marks a vector store record as deleted.",
)
def delete_vector_store_endpoint(
    vector_store_id: str = FastApiPath(..., description="Vector store ID"),
    permanent: bool = Query(
        False, description="If true, permanently delete; otherwise soft‑delete"
    ),
    db: Session = Depends(get_db),
):
    svc = VectorStoreDBService(db)
    logging_utility.info(
        f"Delete request for store={vector_store_id} permanent={permanent}"
    )
    try:
        if permanent:
            svc.permanently_delete_vector_store(vector_store_id)
        else:
            svc.mark_vector_store_deleted(vector_store_id)
        return None

    except VectorStoreNotFoundError as e:
        logging_utility.warning(f"Not found on delete: {e}")
        raise HTTPException(status_code=404, detail=str(e))

    except VectorStoreDBError as e:
        logging_utility.error(f"DB error on delete: {e}")
        raise HTTPException(status_code=500, detail=f"Delete failed: {e}")

    except Exception as e:
        logging_utility.exception(f"Unexpected on delete: {e}")
        raise HTTPException(status_code=500, detail="Unexpected internal error.")


@router.get(
    "/vector-stores/{vector_store_id}",
    response_model=ValidationInterface.VectorStoreRead,
    summary="Get Vector Store",
    description="Retrieves metadata for a specific vector store by its ID.",
)
def get_vector_store_endpoint(
    vector_store_id: str = FastApiPath(..., description="Vector store ID"),
    db: Session = Depends(get_db),
):
    svc = VectorStoreDBService(db)
    store = svc.get_vector_store_by_id(vector_store_id)
    if not store:
        raise HTTPException(status_code=404, detail="Vector store not found.")
    return store


@router.get(
    "/vector-stores/lookup/collection",
    response_model=ValidationInterface.VectorStoreRead,
    summary="Get Vector Store by Collection Name",
    description="Retrieves vector store metadata using its unique collection name.",
)
def get_by_collection_endpoint(
    name: str = Query(..., description="Collection name to look up"),
    db: Session = Depends(get_db),
):
    svc = VectorStoreDBService(db)
    store = svc.get_vector_store_by_collection_name(name)
    if not store:
        raise HTTPException(status_code=404, detail="Collection not found.")
    return store


@router.get(
    "/users/{user_id}/vector-stores",
    response_model=List[ValidationInterface.VectorStoreRead],
    summary="List User's Vector Stores",
    description="Retrieves non-deleted vector stores owned by a user.",
)
def list_by_user_endpoint(
    user_id: str = FastApiPath(..., description="User ID"),
    db: Session = Depends(get_db),
):
    svc = VectorStoreDBService(db)
    try:
        return svc.get_stores_by_user(user_id)
    except Exception as e:
        logging_utility.error(f"Error listing by user: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch stores.")


@router.post(
    "/vector-stores/{vector_store_id}/files",
    response_model=ValidationInterface.VectorStoreFileRead,
    status_code=201,
    summary="Add File Record to Vector Store",
    description="Registers a file metadata record under a vector store.",
)
def add_file_endpoint(
    file_data: ValidationInterface.VectorStoreFileCreate,
    vector_store_id: str = FastApiPath(..., description="Vector store ID"),
    db: Session = Depends(get_db),
):
    svc = VectorStoreDBService(db)
    logging_utility.info(
        f"Add file to store={vector_store_id} file_id={file_data.file_id}"
    )
    try:
        record = svc.create_vector_store_file(
            vector_store_id=vector_store_id,
            file_id=file_data.file_id,
            file_name=file_data.file_name,
            file_path=file_data.file_path,
            status=file_data.status or ValidationInterface.StatusEnum.completed,
            meta_data=file_data.meta_data,
        )
        return record

    except VectorStoreNotFoundError as e:
        logging_utility.warning(f"Store not found on add file: {e}")
        raise HTTPException(status_code=404, detail=str(e))

    except DatabaseConflictError as e:
        logging_utility.warning(f"Conflict on add file: {e}")
        raise HTTPException(status_code=409, detail=str(e))

    except VectorStoreDBError as e:
        logging_utility.error(f"DB error on add file: {e}")
        raise HTTPException(status_code=500, detail=f"Add file failed: {e}")

    except Exception as e:
        logging_utility.exception(f"Unexpected on add file: {e}")
        raise HTTPException(status_code=500, detail="Unexpected internal error.")


@router.get(
    "/vector-stores/{vector_store_id}/files",
    response_model=List[ValidationInterface.VectorStoreFileRead],
    summary="List Files in Vector Store",
    description="Retrieves all non-deleted file records for a vector store.",
)
def list_files_endpoint(
    vector_store_id: str = FastApiPath(..., description="Vector store ID"),
    db: Session = Depends(get_db),
):
    svc = VectorStoreDBService(db)
    try:
        return svc.list_vector_store_files(vector_store_id)
    except Exception as e:
        logging_utility.error(f"Error listing files: {e}")
        raise HTTPException(status_code=500, detail="Failed to list files.")


@router.delete(
    "/vector-stores/{vector_store_id}/files",
    status_code=204,
    summary="Delete File from Vector Store",
    description="Deletes a file record by its path for a given vector store.",
)
def delete_file_endpoint(
    vector_store_id: str = FastApiPath(..., description="Vector store ID"),
    file_path: str = Query(..., description="File‑path identifier"),
    db: Session = Depends(get_db),
):
    svc = VectorStoreDBService(db)
    logging_utility.info(f"Delete file={file_path} from store={vector_store_id}")
    try:
        svc.delete_vector_store_file_by_path(vector_store_id, file_path)
        return None

    except (VectorStoreNotFoundError, VectorStoreFileNotFoundError) as e:
        logging_utility.warning(f"Not found on delete file: {e}")
        raise HTTPException(status_code=404, detail=str(e))

    except VectorStoreDBError as e:
        logging_utility.error(f"DB error on delete file: {e}")
        raise HTTPException(status_code=500, detail=f"Delete file failed: {e}")

    except Exception as e:
        logging_utility.exception(f"Unexpected on delete file: {e}")
        raise HTTPException(status_code=500, detail="Unexpected internal error.")


@router.patch(
    "/vector-stores/{vector_store_id}/files/{file_id}",
    response_model=ValidationInterface.VectorStoreFileRead,
    summary="Update Vector Store File Status",
    description="Updates the status and optional error message for a file record.",
)
def update_file_status_endpoint(
    vector_store_id: str = FastApiPath(..., description="Vector store ID"),
    file_id: str = FastApiPath(..., description="File record ID"),
    file_status: ValidationInterface.VectorStoreFileUpdateStatus = ...,
    db: Session = Depends(get_db),
):
    svc = VectorStoreDBService(db)
    logging_utility.info(f"Update status file={file_id} in store={vector_store_id}")
    try:
        return svc.update_vector_store_file_status(
            vector_store_id, file_id, file_status.status, file_status.error_message
        )

    except VectorStoreFileNotFoundError as e:
        logging_utility.warning(f"File not found on update status: {e}")
        raise HTTPException(status_code=404, detail=str(e))

    except VectorStoreDBError as e:
        logging_utility.error(f"DB error on update status: {e}")
        raise HTTPException(status_code=500, detail=f"Update status failed: {e}")

    except Exception as e:
        logging_utility.exception(f"Unexpected on update status: {e}")
        raise HTTPException(status_code=500, detail="Unexpected internal error.")


@router.post(
    "/assistants/{assistant_id}/vector-stores/{vector_store_id}/attach",
    response_model=Dict[str, bool],
    summary="Attach Vector Store to Assistant",
    description="Associates a vector store with an assistant.",
)
def attach_store_endpoint(
    assistant_id: str = FastApiPath(..., description="Assistant ID"),
    vector_store_id: str = FastApiPath(..., description="Vector store ID"),
    db: Session = Depends(get_db),
):
    svc = VectorStoreDBService(db)
    logging_utility.info(f"Attach store={vector_store_id} to assistant={assistant_id}")
    try:
        svc.attach_vector_store_to_assistant(vector_store_id, assistant_id)
        return {"success": True}

    except (VectorStoreNotFoundError, AssistantNotFoundError) as e:
        logging_utility.warning(f"Not found on attach: {e}")
        raise HTTPException(status_code=404, detail=str(e))

    except VectorStoreDBError as e:
        logging_utility.error(f"DB error on attach: {e}")
        raise HTTPException(status_code=500, detail=f"Attach failed: {e}")

    except Exception as e:
        logging_utility.exception(f"Unexpected on attach: {e}")
        raise HTTPException(status_code=500, detail="Unexpected internal error.")


@router.delete(
    "/assistants/{assistant_id}/vector-stores/{vector_store_id}/detach",
    response_model=Dict[str, bool],
    summary="Detach Vector Store from Assistant",
    description="Removes the association between an assistant and a vector store.",
)
def detach_store_endpoint(
    assistant_id: str = FastApiPath(..., description="Assistant ID"),
    vector_store_id: str = FastApiPath(..., description="Vector store ID"),
    db: Session = Depends(get_db),
):
    svc = VectorStoreDBService(db)
    logging_utility.info(
        f"Detach store={vector_store_id} from assistant={assistant_id}"
    )
    try:
        svc.detach_vector_store_from_assistant(vector_store_id, assistant_id)
        return {"success": True}

    except AssistantNotFoundError as e:
        logging_utility.warning(f"Assistant not found on detach: {e}")
        raise HTTPException(status_code=404, detail=str(e))

    except VectorStoreDBError as e:
        logging_utility.error(f"DB error on detach: {e}")
        raise HTTPException(status_code=500, detail=f"Detach failed: {e}")

    except Exception as e:
        logging_utility.exception(f"Unexpected on detach: {e}")
        raise HTTPException(status_code=500, detail="Unexpected internal error.")


@router.get(
    "/assistants/{assistant_id}/vector-stores",
    response_model=List[ValidationInterface.VectorStoreRead],
    summary="List Assistant's Vector Stores",
    description="Retrieves vector stores attached to an assistant.",
)
def list_assistant_stores_endpoint(
    assistant_id: str = FastApiPath(..., description="Assistant ID"),
    db: Session = Depends(get_db),
):
    svc = VectorStoreDBService(db)
    try:
        return svc.get_vector_stores_for_assistant(assistant_id)
    except Exception as e:
        logging_utility.error(f"Error listing assistant stores: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch assistant stores.")
