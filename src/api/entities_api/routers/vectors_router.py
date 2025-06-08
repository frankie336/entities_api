# src/api/entities_api/routers/vector_store_router.py
from typing import Any, Dict, List, Union

from fastapi import APIRouter, Depends, HTTPException
from fastapi import Path as FastApiPath
from fastapi import Query, status
from projectdavid_common import UtilsInterface, ValidationInterface
from projectdavid_common.schemas.vectors_schema import VectorStoreRead
from sqlalchemy.orm import Session

from entities_api.dependencies import get_api_key, get_db
from entities_api.models.models import ApiKey as ApiKeyModel
from entities_api.models.models import User as UserModel  # for auth checks
from entities_api.services.vectors import (
    AssistantNotFoundError,
    DatabaseConflictError,
    VectorStoreDBError,
    VectorStoreDBService,
    VectorStoreFileNotFoundError,
    VectorStoreNotFoundError,
)

router = APIRouter()
log = UtilsInterface.LoggingUtility()


# --------------------------------------------------------------------------- #
#  helper: is-admin? (cached single query per request)
# --------------------------------------------------------------------------- #
def _is_admin(user_id: str, db: Session) -> bool:
    user = db.query(UserModel).filter(UserModel.id == user_id).first()
    return bool(user and user.is_admin)


# --------------------------------------------------------------------------- #
#  CREATE STORE  – normal user → self,  admin → override owner_id
# --------------------------------------------------------------------------- #
@router.post(
    "/vector-stores",
    response_model=ValidationInterface.VectorStoreRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create Vector Store",
    description=(
        "Creates a new vector-store.  \n\n"
        "- **Regular callers** → the store is assigned to *their* user-id.  \n"
        "- **Admins** → may pass the optional `owner_id` query-param to create the "
        "store for a different user."
    ),
)
def create_vector_store(
    data: ValidationInterface.VectorStoreCreateWithSharedId,
    owner_id: str | None = Query(
        default=None,
        description="Target user-id (admin-only).  "
        "If omitted, the store is created for the caller.",
    ),
    db: Session = Depends(get_db),
    auth_key: ApiKeyModel = Depends(get_api_key),
):
    # ── determine effective owner ────────────────────────────────────────
    if owner_id is None:
        owner_id = auth_key.user_id
    elif owner_id != auth_key.user_id and not _is_admin(auth_key.user_id, db):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins may specify owner_id.",
        )

    log.info(
        "Create vector-store %s  owner=%s  requested_by=%s",
        data.shared_id,
        owner_id,
        auth_key.user_id,
    )

    service = VectorStoreDBService(db)
    try:
        return service.create_vector_store(
            shared_id=data.shared_id,
            name=data.name,
            user_id=owner_id,
            vector_size=data.vector_size,
            distance_metric=data.distance_metric,
            config=data.config,
        )
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
    store = service.get_vector_store_by_id(vector_store_id)
    if not store or (
        store.user_id != auth_key.user_id and not _is_admin(auth_key.user_id, db)
    ):
        raise HTTPException(status_code=404, detail="Vector store not found.")

    # proceed with delete / soft delete
    try:
        if permanent:
            service.permanently_delete_vector_store(vector_store_id)
        else:
            service.mark_vector_store_deleted(vector_store_id)
    except VectorStoreDBError as exc:
        raise HTTPException(status_code=500, detail=f"Delete failed: {exc}") from exc


# --------------------------------------------------------------------------- #
#  GET BY ID
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
    if not store or (
        store.user_id != auth_key.user_id and not _is_admin(auth_key.user_id, db)
    ):
        raise HTTPException(status_code=404, detail="Vector store not found.")
    return store


# --------------------------------------------------------------------------- #
#  LIST MY STORES
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
#  ADMIN – LIST BY USER
# --------------------------------------------------------------------------- #
@router.get(
    "/vector-stores/admin/by-user",
    response_model=List[VectorStoreRead],
    summary="(admin) list vector-stores for a given user_id",
)
def list_vector_stores_by_user(
    owner_id: str = Query(..., description="Target user-id"),
    db: Session = Depends(get_db),
    auth_key: ApiKeyModel = Depends(get_api_key),
):
    if not _is_admin(auth_key.user_id, db):
        raise HTTPException(status_code=403, detail="Admin privilege required.")

    service = VectorStoreDBService(db)
    return service.get_stores_by_user(owner_id)


# --------------------------------------------------------------------------- #
#  FILE OPS  – owner or admin
# --------------------------------------------------------------------------- #
def _require_store_access(
    store_id: str,
    db: Session,
    auth_key: ApiKeyModel,
    service: VectorStoreDBService,
):
    store = service.get_vector_store_by_id(store_id)
    if not store or (
        store.user_id != auth_key.user_id and not _is_admin(auth_key.user_id, db)
    ):
        raise HTTPException(status_code=404, detail="Vector store not found.")
    return store


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
    _require_store_access(vector_store_id, db, auth_key, service)
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
    _require_store_access(vector_store_id, db, auth_key, service)
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
    _require_store_access(vector_store_id, db, auth_key, service)
    service.delete_vector_store_file_by_path(vector_store_id, file_path)


@router.patch(
    "/vector-stores/{vector_store_id}/files/{file_id}",
    response_model=ValidationInterface.VectorStoreFileRead,
)
def update_file_status(
    file_status: ValidationInterface.VectorStoreFileUpdateStatus,
    vector_store_id: str = FastApiPath(...),
    file_id: str = FastApiPath(...),
    db: Session = Depends(get_db),
    auth_key: ApiKeyModel = Depends(get_api_key),
):
    service = VectorStoreDBService(db)
    _require_store_access(vector_store_id, db, auth_key, service)
    return service.update_vector_store_file_status(
        file_id, file_status.status, file_status.error_message
    )


# --------------------------------------------------------------------------- #
#  ASSISTANT LINKS  – owner or admin
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
    _require_store_access(vector_store_id, db, auth_key, service)
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
    _require_store_access(vector_store_id, db, auth_key, service)
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
    # any user who owns the assistant can call this; admins allowed via helper
    if (
        not _is_admin(auth_key.user_id, db)
        and assistant_id.split("_")[1] != auth_key.user_id.split("_")[1]
    ):
        # coarse check, adjust if you have explicit assistant ownership field
        raise HTTPException(status_code=403, detail="Forbidden")
    service = VectorStoreDBService(db)
    return service.get_vector_stores_for_assistant(assistant_id)


# --------------------------------------------------------------------------- #
#  LOOK-UP BY COLLECTION  (legacy, still open)
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
):
    service = VectorStoreDBService(db)
    store = service.get_vector_store_by_collection_name(name)
    if not store:
        raise HTTPException(status_code=404, detail="Collection not found.")
    return store
