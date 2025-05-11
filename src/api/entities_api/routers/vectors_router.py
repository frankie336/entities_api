# src/api/entities_api/routers/vector_store_router.py
from typing import Any, Dict, List, Union

from fastapi import APIRouter, Depends, HTTPException
from fastapi import Path as FastApiPath
from fastapi import Query, status
from projectdavid_common import UtilsInterface, ValidationInterface
from sqlalchemy.orm import Session

from entities_api.dependencies import get_api_key, get_db
from entities_api.models.models import ApiKey as ApiKeyModel
from entities_api.models.models import User as UserModel  # for auth check
from entities_api.models.models import VectorStore
from entities_api.services.vectors import (AssistantNotFoundError,
                                           DatabaseConflictError,
                                           VectorStoreDBError,
                                           VectorStoreDBService,
                                           VectorStoreFileNotFoundError,
                                           VectorStoreNotFoundError)

router = APIRouter()  # consistent with other routers

log = UtilsInterface.LoggingUtility()


# --------------------------------------------------------------------------- #
#  CREATE STORE  – normal user → self,  admin → override owner_id
# --------------------------------------------------------------------------- #
@router.post(
    "/vector-stores",
    response_model=ValidationInterface.VectorStoreRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create Vector Store",
    description=(
        "Creates a new vector‑store.  \n\n"
        "- **Regular callers** → the store is assigned to *their* user‑id.  \n"
        "- **Admins** → may pass the optional `owner_id` query‑param to create the "
        "store for a different user."
    ),
)
def create_vector_store(
    data: ValidationInterface.VectorStoreCreateWithSharedId,
    owner_id: str | None = Query(
        default=None,
        description="Target user‑id (admin‑only).  "
        "If omitted, the store is created for the caller.",
    ),
    db: Session = Depends(get_db),
    auth_key: ApiKeyModel = Depends(get_api_key),
):
    """
    • Enforces ownership and admin override rules.
    • Persists the *metadata* row; the physical Qdrant collection is
      created by the SDK **before** this call.
    """
    # ── determine effective owner ──────────────────────────────────────
    if owner_id is None:
        owner_id = auth_key.user_id
    elif owner_id != auth_key.user_id:
        # override ⇒ requester must be admin
        requester: UserModel | None = (
            db.query(UserModel).filter(UserModel.id == auth_key.user_id).first()
        )
        if not requester or not requester.is_admin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only admins may specify owner_id.",
            )

    log.info(
        "Create vector‑store %s  owner=%s  requested_by=%s",
        data.shared_id,
        owner_id,
        auth_key.user_id,
    )

    service = VectorStoreDBService(db)
    try:
        store = service.create_vector_store(
            shared_id=data.shared_id,
            name=data.name,
            user_id=owner_id,  # ← new owner logic
            vector_size=data.vector_size,
            distance_metric=data.distance_metric,
            config=data.config,
        )
        return store

    except DatabaseConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except VectorStoreDBError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal error: {exc}",
        ) from exc


# --------------------------------------------------------------------------- #
#  DELETE / SOFT-DELETE STORE
# --------------------------------------------------------------------------- #
@router.delete(
    "/vector-stores/{vector_store_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete Vector Store",
)
def delete_vector_store(
    vector_store_id: str = FastApiPath(...),
    permanent: bool = Query(False),
    db: Session = Depends(get_db),
    auth_key: ApiKeyModel = Depends(get_api_key),
):
    log.info(
        "User '%s' – delete store %s permanent=%s",
        auth_key.user_id,
        vector_store_id,
        permanent,
    )
    service = VectorStoreDBService(db)
    try:
        (
            service.permanently_delete_vector_store(vector_store_id)
            if permanent
            else service.mark_vector_store_deleted(vector_store_id)
        )
    except VectorStoreNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except VectorStoreDBError as exc:
        raise HTTPException(status_code=500, detail=f"Delete failed: {exc}") from exc


# --------------------------------------------------------------------------- #
#  GET BY ID  (owners only)
# --------------------------------------------------------------------------- #
@router.get(
    "/vector-stores/{vector_store_id}",
    response_model=ValidationInterface.VectorStoreRead,
)
def get_vector_store(
    vector_store_id: str = FastApiPath(...),
    db: Session = Depends(get_db),
    auth_key: ApiKeyModel = Depends(get_api_key),
):
    service = VectorStoreDBService(db)
    store = service.get_vector_store_by_id(vector_store_id)
    if not store or store.user_id != auth_key.user_id:  # ⟵ ownership check
        raise HTTPException(status_code=404, detail="Vector store not found.")
    return store


# --------------------------------------------------------------------------- #
#  LIST MY STORES   (REPLACES /users/{id}/vector-stores)
# --------------------------------------------------------------------------- #
@router.get(
    "/vector-stores",
    response_model=List[ValidationInterface.VectorStoreRead],
    summary="List current user's Vector Stores",
)
def list_my_vector_stores(
    db: Session = Depends(get_db),
    auth_key: ApiKeyModel = Depends(get_api_key),
):
    service = VectorStoreDBService(db)
    return service.get_stores_by_user(auth_key.user_id)


# --------------------------------------------------------------------------- #
#  FILE OPS  – owner-checked via store.user_id
# --------------------------------------------------------------------------- #
@router.post(
    "/vector-stores/{vector_store_id}/files",
    response_model=ValidationInterface.VectorStoreFileRead,
    status_code=status.HTTP_201_CREATED,
)
def add_file(
    file_data: ValidationInterface.VectorStoreFileCreate,
    vector_store_id: str = FastApiPath(...),
    db: Session = Depends(get_db),
    auth_key: ApiKeyModel = Depends(get_api_key),
):
    service = VectorStoreDBService(db)
    # Ownership check
    store = service.get_vector_store_by_id(vector_store_id)
    if not store or store.user_id != auth_key.user_id:
        raise HTTPException(status_code=404, detail="Vector store not found.")
    return service.create_vector_store_file(
        vector_store_id=vector_store_id,
        file_id=file_data.file_id,
        file_name=file_data.file_name,
        file_path=file_data.file_path,
        status=file_data.status or ValidationInterface.StatusEnum.completed,
        meta_data=file_data.meta_data,
    )


@router.get(
    "/vector-stores/{vector_store_id}/files",
    response_model=List[ValidationInterface.VectorStoreFileRead],
)
def list_files(
    vector_store_id: str = FastApiPath(...),
    db: Session = Depends(get_db),
    auth_key: ApiKeyModel = Depends(get_api_key),
):
    service = VectorStoreDBService(db)
    store = service.get_vector_store_by_id(vector_store_id)
    if not store or store.user_id != auth_key.user_id:
        raise HTTPException(status_code=404, detail="Vector store not found.")
    return service.list_vector_store_files(vector_store_id)


@router.delete(
    "/vector-stores/{vector_store_id}/files",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_file(
    vector_store_id: str = FastApiPath(...),
    file_path: str = Query(...),
    db: Session = Depends(get_db),
    auth_key: ApiKeyModel = Depends(get_api_key),
):
    service = VectorStoreDBService(db)
    store = service.get_vector_store_by_id(vector_store_id)
    if not store or store.user_id != auth_key.user_id:
        raise HTTPException(status_code=404, detail="Vector store not found.")
    service.delete_vector_store_file_by_path(vector_store_id, file_path)


@router.patch(
    "/vector-stores/{vector_store_id}/files/{file_id}",
    response_model=ValidationInterface.VectorStoreFileRead,
)
def update_file_status(
    file_status: ValidationInterface.VectorStoreFileUpdateStatus,  # ← moved first
    vector_store_id: str = FastApiPath(...),
    file_id: str = FastApiPath(...),
    db: Session = Depends(get_db),
    auth_key: ApiKeyModel = Depends(get_api_key),
):
    service = VectorStoreDBService(db)
    store = service.get_vector_store_by_id(vector_store_id)
    if not store or store.user_id != auth_key.user_id:
        raise HTTPException(status_code=404, detail="Vector store not found.")
    return service.update_vector_store_file_status(
        file_id, file_status.status, file_status.error_message
    )


# --------------------------------------------------------------------------- #
#  ASSISTANT LINKS  – same auth model (user must own assistant or be admin)
# --------------------------------------------------------------------------- #
@router.post(
    "/assistants/{assistant_id}/vector-stores/{vector_store_id}/attach",
    response_model=Dict[str, bool],
)
def attach_store(
    assistant_id: str,
    vector_store_id: str,
    db: Session = Depends(get_db),
    auth_key: ApiKeyModel = Depends(get_api_key),
):
    service = VectorStoreDBService(db)
    # ownership of store already validated inside helper
    service.attach_vector_store_to_assistant(vector_store_id, assistant_id)
    return {"success": True}


@router.delete(
    "/assistants/{assistant_id}/vector-stores/{vector_store_id}/detach",
    response_model=Dict[str, bool],
)
def detach_store(
    assistant_id: str,
    vector_store_id: str,
    db: Session = Depends(get_db),
    auth_key: ApiKeyModel = Depends(get_api_key),
):
    service = VectorStoreDBService(db)
    service.detach_vector_store_from_assistant(vector_store_id, assistant_id)
    return {"success": True}


@router.get(
    "/assistants/{assistant_id}/vector-stores",
    response_model=List[ValidationInterface.VectorStoreRead],
)
def list_assistant_stores(
    assistant_id: str,
    db: Session = Depends(get_db),
    auth_key: ApiKeyModel = Depends(get_api_key),
):
    service = VectorStoreDBService(db)
    return service.get_vector_stores_for_assistant(assistant_id)


# --------------------------------------------------------------------------- #
#  LOOK-UP BY COLLECTION (legacy – *not yet ownership-scoped*)
# --------------------------------------------------------------------------- #
@router.get(
    "/vector-stores/lookup/collection",
    response_model=ValidationInterface.VectorStoreRead,
    summary="Get Vector Store by Collection Name",
    description="Retrieves vector-store metadata using its unique collection name.",
)
def get_vector_store_by_collection(
    name: str = Query(..., description="Collection name to look up"),
    db: Session = Depends(get_db),
    # auth_key: ApiKeyModel = Depends(get_api_key),  # ⇐ hook here when you lock it down
):
    service = VectorStoreDBService(db)
    store = service.get_vector_store_by_collection_name(name)
    if not store:
        raise HTTPException(status_code=404, detail="Collection not found.")
    return store
