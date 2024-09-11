# entities_api/routers.py
from typing import Dict, Any, List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from db.database import get_db
from entities_api.schemas import ToolCreate, ToolRead, ToolUpdate, ToolList, ActionUpdate, ActionRead, ActionList, \
    ActionCreate
from entities_api.schemas import (
    UserCreate, UserRead, UserUpdate, ThreadCreate, ThreadRead, MessageCreate, MessageRead, Run, AssistantCreate,
    AssistantRead, RunStatusUpdate, AssistantUpdate, ThreadIds, ThreadReadDetailed, ToolMessageCreate
)
from entities_api.services.action_service import ActionService
from entities_api.services.assistant_service import AssistantService
from entities_api.services.logging_service import LoggingUtility
from entities_api.services.message_service import MessageService
from entities_api.services.run_service import RunService
from entities_api.services.thread_service import ThreadService
from entities_api.services.tool_service import ToolService
from entities_api.services.user_service import UserService

logging_utility = LoggingUtility()

router = APIRouter()


@router.post("/users", response_model=UserRead)
def create_user(user: UserCreate = None, db: Session = Depends(get_db)):
    user_service = UserService(db)
    return user_service.create_user(user)


@router.get("/users/{user_id}", response_model=UserRead)
def get_user(user_id: str, db: Session = Depends(get_db)):
    user_service = UserService(db)
    return user_service.get_user(user_id)


@router.put("/users/{user_id}", response_model=UserRead)
def update_user(user_id: str, user_update: UserUpdate, db: Session = Depends(get_db)):
    user_service = UserService(db)
    return user_service.update_user(user_id, user_update)


@router.delete("/users/{user_id}", status_code=204)
def delete_user(user_id: str, db: Session = Depends(get_db)):
    user_service = UserService(db)
    user_service.delete_user(user_id)
    return {"detail": "User deleted successfully"}


@router.post("/threads", response_model=ThreadReadDetailed)
def create_thread(thread: ThreadCreate, db: Session = Depends(get_db)):
    logging_utility.info("Received request to create a new thread")
    thread_service = ThreadService(db)
    try:
        new_thread = thread_service.create_thread(thread)
        logging_utility.info(f"Successfully created thread with ID: {new_thread.id}")
        return new_thread
    except HTTPException as e:
        logging_utility.error(f"HTTP error occurred while creating thread: {str(e)}")
        raise e
    except Exception as e:
        logging_utility.error(f"An error occurred while creating thread: {str(e)}")
        raise HTTPException(status_code=500, detail=f"An error occurred: {str(e)}")


@router.get("/threads/{thread_id}", response_model=ThreadRead)
def get_thread(thread_id: str, db: Session = Depends(get_db)):
    thread_service = ThreadService(db)
    return thread_service.get_thread(thread_id)


@router.delete("/threads/{thread_id}", status_code=204)
def delete_thread(thread_id: str, db: Session = Depends(get_db)):
    logging_utility.info(f"Received request to delete thread with ID: {thread_id}")
    thread_service = ThreadService(db)
    try:
        thread_service.delete_thread(thread_id)
        logging_utility.info(f"Successfully deleted thread with ID: {thread_id}")
        return {"detail": "Thread deleted successfully"}
    except HTTPException as e:
        logging_utility.error(f"HTTP error occurred while deleting thread: {str(e)}")
        raise e
    except Exception as e:
        logging_utility.error(f"An error occurred while deleting thread: {str(e)}")
        raise HTTPException(status_code=500, detail=f"An error occurred: {str(e)}")


@router.get("/users/{user_id}/threads", response_model=ThreadIds)
def list_threads_by_user(user_id: str, db: Session = Depends(get_db)):
    logging_utility.info(f"Listing threads for user ID: {user_id}")
    thread_service = ThreadService(db)
    try:
        thread_ids = thread_service.list_threads_by_user(user_id)
        logging_utility.info(f"Successfully retrieved threads for user ID: {user_id}")
        return {"thread_ids": thread_ids}
    except HTTPException as e:
        logging_utility.error(f"HTTP error occurred while listing threads: {str(e)}")
        raise e
    except Exception as e:
        logging_utility.error(f"An error occurred while listing threads: {str(e)}")
        raise HTTPException(status_code=500, detail=f"An error occurred: {str(e)}")


@router.post("/messages", response_model=MessageRead)
def create_message(message: MessageCreate, db: Session = Depends(get_db)):
    message_service = MessageService(db)
    return message_service.create_message(message)


@router.get("/messages/{message_id}", response_model=MessageRead)
def get_message(message_id: str, db: Session = Depends(get_db)):
    message_service = MessageService(db)
    return message_service.retrieve_message(message_id)


@router.get("/threads/{thread_id}/messages", response_model=List[MessageRead])
def list_messages(thread_id: str, limit: int = 20, order: str = "asc", db: Session = Depends(get_db)):
    logging_utility.info(f"Retrieving messages for thread: {thread_id}")
    message_service = MessageService(db)
    return message_service.list_messages(thread_id=thread_id, limit=limit, order=order)


@router.post("/runs", response_model=Run)
def create_run(run: Run, db: Session = Depends(get_db)):
    run_service = RunService(db)
    return run_service.create_run(run)


@router.get("/runs/{run_id}", response_model=Run)
def get_run(run_id: str, db: Session = Depends(get_db)):
    run_service = RunService(db)
    return run_service.get_run(run_id)


@router.put("/runs/{run_id}/status", response_model=Run)
def update_run_status(run_id: str, status_update: RunStatusUpdate, db: Session = Depends(get_db)):
    run_service = RunService(db)
    try:
        updated_run = run_service.update_run_status(run_id, status_update.status)
        return updated_run
    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"An error occurred: {str(e)}")


@router.post("/runs/{run_id}/cancel", response_model=Run)
def cancel_run(run_id: str, db: Session = Depends(get_db)):
    run_service = RunService(db)
    try:
        cancelled_run = run_service.cancel_run(run_id)
        return cancelled_run
    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"An error occurred: {str(e)}")


@router.post("/assistants", response_model=AssistantRead)
def create_assistant(assistant: AssistantCreate, db: Session = Depends(get_db)):
    assistant_service = AssistantService(db)
    return assistant_service.create_assistant(assistant)


@router.get("/assistants/{assistant_id}", response_model=AssistantRead)
def get_assistant(assistant_id: str, db: Session = Depends(get_db)):
    assistant_service = AssistantService(db)
    return assistant_service.get_assistant(assistant_id)


@router.put("/assistants/{assistant_id}", response_model=AssistantRead)
def update_assistant(assistant_id: str, assistant_update: AssistantUpdate, db: Session = Depends(get_db)):
    assistant_service = AssistantService(db)
    try:
        return assistant_service.update_assistant(assistant_id, assistant_update)
    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"An error occurred: {str(e)}")


@router.get("/threads/{thread_id}/formatted_messages", response_model=List[Dict[str, Any]])
def get_formatted_messages(thread_id: str, db: Session = Depends(get_db)):
    message_service = MessageService(db)
    try:
        return message_service.list_messages_for_thread(thread_id)
    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"An error occurred: {str(e)}")


@router.post("/messages/assistant", response_model=MessageRead)
def save_assistant_message(message: MessageCreate, db: Session = Depends(get_db)):
    message_service = MessageService(db)
    return message_service.save_assistant_message_chunk(
        thread_id=message.thread_id,
        content=message.content,
        is_last_chunk=True  # Assuming we're always sending the complete message
    )

@router.post("/messages/{message_id}/tool", response_model=MessageRead)
def add_tool_message(message_id: str, tool_message: ToolMessageCreate, db: Session = Depends(get_db)):
    message_service = MessageService(db)
    try:
        return message_service.add_tool_message(message_id, tool_message.content)
    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"An error occurred: {str(e)}")

@router.post("/tools", response_model=ToolRead)
def create_tool(tool: ToolCreate, db: Session = Depends(get_db)):
    tool_service = ToolService(db)
    return tool_service.create_tool(tool)






@router.post("/assistants/{assistant_id}/tools/{tool_id}")
def associate_tool_with_assistant(assistant_id: str, tool_id: str, db: Session = Depends(get_db)):
    tool_service = ToolService(db)
    tool_service.associate_tool_with_assistant(tool_id, assistant_id)
    return {"message": "Tool associated with assistant successfully"}


@router.get("/tools/{tool_id}", response_model=ToolRead)
def get_tool(tool_id: str, db: Session = Depends(get_db)):
    tool_service = ToolService(db)
    return tool_service.get_tool(tool_id)

@router.get("/tools/name/{name}", response_model=ToolRead)
def get_tool_by_name(name: str, db: Session = Depends(get_db)):
    tool_service = ToolService(db)
    return tool_service.get_tool_by_name(name)

@router.put("/tools/{tool_id}", response_model=ToolRead)
def update_tool(tool_id: str, tool_update: ToolUpdate, db: Session = Depends(get_db)):
    tool_service = ToolService(db)
    return tool_service.update_tool(tool_id, tool_update)


@router.delete("/tools/{tool_id}", status_code=204)
def delete_tool(tool_id: str, db: Session = Depends(get_db)):
    tool_service = ToolService(db)
    tool_service.delete_tool(tool_id)
    return {"detail": "Tool deleted successfully"}


@router.get("/tools", response_model=ToolList)
@router.get("/assistants/{assistant_id}/tools", response_model=ToolList)
def list_tools(assistant_id: str = None, db: Session = Depends(get_db)):
    tool_service = ToolService(db)
    tools = tool_service.list_tools(assistant_id)
    return ToolList(tools=tools)


@router.post("/actions", response_model=ActionRead)
def create_action(action: ActionCreate, db: Session = Depends(get_db)):
    action_service = ActionService(db)
    return action_service.create_action(action)


@router.get("/actions/{action_id}", response_model=ActionRead)
def get_action(action_id: str, db: Session = Depends(get_db)):
    logging_utility.info(f"Received request to get action with ID: {action_id}")

    action_service = ActionService(db)
    try:
        action = action_service.get_action(action_id)
        logging_utility.info(f"Action retrieved successfully with ID: {action_id}")
        return action
    except HTTPException as e:
        logging_utility.error(f"HTTP error while retrieving action with ID {action_id}: {str(e)}")
        raise e
    except Exception as e:
        logging_utility.error(f"Unexpected error while retrieving action with ID {action_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"An error occurred: {str(e)}")



@router.put("/actions/{action_id}", response_model=ActionRead)
def update_action_status(action_id: str, action_update: ActionUpdate, db: Session = Depends(get_db)):
    action_service = ActionService(db)
    return action_service.update_action_status(action_id, action_update)

@router.get("/runs/{run_id}/actions", response_model=ActionList)
def list_actions_for_run(run_id: str, db: Session = Depends(get_db)):
    action_service = ActionService(db)
    return action_service.list_actions_for_run(run_id)

@router.post("/actions/expire", response_model=dict)
def expire_actions(db: Session = Depends(get_db)):
    action_service = ActionService(db)
    count = action_service.expire_actions()
    return {"expired_count": count}

@router.delete("/actions/{action_id}", status_code=204)
def delete_action(action_id: str, db: Session = Depends(get_db)):
    action_service = ActionService(db)
    action_service.delete_action(action_id)
    return {"detail": "Action deleted successfully"}