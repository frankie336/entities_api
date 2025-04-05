from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from entities_api.dependencies import get_db
from entities_api.serializers import ThreadCreate
from entities_api.services.logging_service import LoggingUtility
from entities_api.services.thread_service import ThreadService


from entities_common import ValidationInterface

validation = ValidationInterface()

router = APIRouter()
logging_utility = LoggingUtility()


@router.post("/threads", response_model=validation.ThreadReadDetailed)
def create_thread(thread: ThreadCreate, db: Session = Depends(get_db)):
    logging_utility.info("Received request to create a new thread.")
    thread_service = ThreadService(db)
    try:
        new_thread = thread_service.create_thread(thread)
        logging_utility.info(f"Thread created successfully with ID: {new_thread.id}")
        return new_thread
    except HTTPException as e:
        logging_utility.error(f"HTTP error occurred while creating thread: {str(e)}")
        raise e
    except Exception as e:
        logging_utility.error(f"An unexpected error occurred while creating thread: {str(e)}")
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")

@router.get("/threads/{thread_id}", response_model=validation.ThreadRead)
def get_thread(thread_id: str, db: Session = Depends(get_db)):
    logging_utility.info(f"Received request to get thread with ID: {thread_id}")
    thread_service = ThreadService(db)
    try:
        thread = thread_service.get_thread(thread_id)
        logging_utility.info(f"Thread retrieved successfully with ID: {thread_id}")
        return thread
    except HTTPException as e:
        logging_utility.error(f"HTTP error occurred while retrieving thread {thread_id}: {str(e)}")
        raise e
    except Exception as e:
        logging_utility.error(f"An unexpected error occurred while retrieving thread {thread_id}: {str(e)}")
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")


@router.delete("/threads/{thread_id}", status_code=204)
def delete_thread(thread_id: str, db: Session = Depends(get_db)):
    logging_utility.info(f"Received request to delete thread with ID: {thread_id}")
    thread_service = ThreadService(db)
    try:
        thread_service.delete_thread(thread_id)
        logging_utility.info(f"Thread deleted successfully with ID: {thread_id}")
        return {"detail": "Thread deleted successfully"}
    except HTTPException as e:
        logging_utility.error(f"HTTP error occurred while deleting thread {thread_id}: {str(e)}")
        raise e
    except Exception as e:
        logging_utility.error(f"An unexpected error occurred while deleting thread {thread_id}: {str(e)}")
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")


@router.get("/users/{user_id}/threads", response_model=validation.ThreadIds)
def list_threads_by_user(user_id: str, db: Session = Depends(get_db)):
    logging_utility.info(f"Received request to list threads for user ID: {user_id}")
    thread_service = ThreadService(db)
    try:
        thread_ids = thread_service.list_threads_by_user(user_id)
        logging_utility.info(f"Successfully retrieved threads for user ID: {user_id}")
        return {"thread_ids": thread_ids}
    except HTTPException as e:
        logging_utility.error(f"HTTP error occurred while listing threads for user {user_id}: {str(e)}")
        raise e
    except Exception as e:
        logging_utility.error(f"An unexpected error occurred while listing threads for user {user_id}: {str(e)}")
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")
