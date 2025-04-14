from fastapi import APIRouter, Depends, HTTPException
from projectdavid_common import UtilsInterface, ValidationInterface
from sqlalchemy.orm import Session

from entities_api.dependencies import get_api_key, get_db
from entities_api.models.models import ApiKey as ApiKeyModel
from entities_api.services.threads import ThreadService

router = APIRouter(
    prefix="/threads",
    tags=["Threads"],
    responses={404: {"description": "Thread not found"}},
)

validator = ValidationInterface()
logging_utility = UtilsInterface.LoggingUtility()


@router.post("", response_model=ValidationInterface.ThreadReadDetailed)
def create_thread(
    thread: ValidationInterface.ThreadCreate,
    db: Session = Depends(get_db),
    auth_key: ApiKeyModel = Depends(get_api_key),
):
    logging_utility.info(f"[{auth_key.user_id}] Creating thread")
    try:
        service = ThreadService(db)
        return service.create_thread(thread)
    except Exception as e:
        logging_utility.error(f"Error creating thread: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to create thread")


@router.get("/{thread_id}", response_model=ValidationInterface.ThreadReadDetailed)
def get_thread(
    thread_id: str,
    db: Session = Depends(get_db),
    auth_key: ApiKeyModel = Depends(get_api_key),
):
    logging_utility.info(f"[{auth_key.user_id}] Fetching thread: {thread_id}")
    return ThreadService(db).get_thread(thread_id)


@router.delete("/{thread_id}", response_model=bool)
def delete_thread(
    thread_id: str,
    db: Session = Depends(get_db),
    auth_key: ApiKeyModel = Depends(get_api_key),
):
    logging_utility.info(f"[{auth_key.user_id}] Deleting thread: {thread_id}")
    return ThreadService(db).delete_thread(thread_id)


@router.get("/user/{user_id}", response_model=list[str])
def list_user_threads(
    user_id: str,
    db: Session = Depends(get_db),
    auth_key: ApiKeyModel = Depends(get_api_key),
):
    logging_utility.info(f"[{auth_key.user_id}] Listing threads for user {user_id}")
    return ThreadService(db).list_threads_by_user(user_id)


@router.put(
    "/{thread_id}/metadata", response_model=ValidationInterface.ThreadReadDetailed
)
def update_thread_metadata(
    thread_id: str,
    metadata: dict,
    db: Session = Depends(get_db),
    auth_key: ApiKeyModel = Depends(get_api_key),
):
    logging_utility.info(
        f"[{auth_key.user_id}] Updating metadata for thread {thread_id}"
    )
    return ThreadService(db).update_thread_metadata(thread_id, metadata)


@router.put("/{thread_id}", response_model=ValidationInterface.ThreadReadDetailed)
def update_thread(
    thread_id: str,
    thread_update: ValidationInterface.ThreadUpdate,
    db: Session = Depends(get_db),
    auth_key: ApiKeyModel = Depends(get_api_key),
):
    logging_utility.info(f"[{auth_key.user_id}] Updating thread {thread_id}")
    return ThreadService(db).update_thread(thread_id, thread_update)
