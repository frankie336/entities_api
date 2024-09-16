# entities_api/routers.py
from typing import Dict, Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from db.database import get_db
from entities_api.schemas import SandboxCreate, SandboxRead, SandboxUpdate
from entities_api.schemas import (
    UserCreate, UserRead, UserUpdate,
    ThreadCreate, ThreadRead, ThreadReadDetailed, ThreadIds,
    MessageCreate, MessageRead,
    Run, RunStatusUpdate,
    AssistantCreate, AssistantRead, AssistantUpdate,
    ToolCreate, ToolRead, ToolUpdate, ToolList,
    ActionCreate, ActionRead, ActionUpdate, ToolMessageCreate
)
from entities_api.services.action_service import ActionService
from entities_api.services.assistant_service import AssistantService
from entities_api.services.logging_service import LoggingUtility
from entities_api.services.message_service import MessageService
from entities_api.services.run_service import RunService
from entities_api.services.sandbox_service import SandboxService
from entities_api.services.thread_service import ThreadService
from entities_api.services.tool_service import ToolService
from entities_api.services.user_service import UserService

logging_utility = LoggingUtility()
router = APIRouter()


@router.post("/users", response_model=UserRead)
def create_user(user: UserCreate = None, db: Session = Depends(get_db)):
    logging_utility.info("Received request to create a new user.")
    user_service = UserService(db)
    try:
        new_user = user_service.create_user(user)
        logging_utility.info(f"User created successfully with ID: {new_user.id}")
        return new_user
    except HTTPException as e:
        logging_utility.error(f"HTTP error occurred while creating user: {str(e)}")
        raise e
    except Exception as e:
        logging_utility.error(f"An unexpected error occurred while creating user: {str(e)}")
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")


@router.get("/users/{user_id}", response_model=UserRead)
def get_user(user_id: str, db: Session = Depends(get_db)):
    logging_utility.info(f"Received request to get user with ID: {user_id}")
    user_service = UserService(db)
    try:
        user = user_service.get_user(user_id)
        logging_utility.info(f"User retrieved successfully with ID: {user_id}")
        return user
    except HTTPException as e:
        logging_utility.error(f"HTTP error occurred while retrieving user {user_id}: {str(e)}")
        raise e
    except Exception as e:
        logging_utility.error(f"An unexpected error occurred while retrieving user {user_id}: {str(e)}")
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")


@router.put("/users/{user_id}", response_model=UserRead)
def update_user(user_id: str, user_update: UserUpdate, db: Session = Depends(get_db)):
    logging_utility.info(f"Received request to update user with ID: {user_id}")
    user_service = UserService(db)
    try:
        updated_user = user_service.update_user(user_id, user_update)
        logging_utility.info(f"User updated successfully with ID: {user_id}")
        return updated_user
    except HTTPException as e:
        logging_utility.error(f"HTTP error occurred while updating user {user_id}: {str(e)}")
        raise e
    except Exception as e:
        logging_utility.error(f"An unexpected error occurred while updating user {user_id}: {str(e)}")
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")


@router.delete("/users/{user_id}", status_code=204)
def delete_user(user_id: str, db: Session = Depends(get_db)):
    logging_utility.info(f"Received request to delete user with ID: {user_id}")
    user_service = UserService(db)
    try:
        user_service.delete_user(user_id)
        logging_utility.info(f"User deleted successfully with ID: {user_id}")
        return {"detail": "User deleted successfully"}
    except HTTPException as e:
        logging_utility.error(f"HTTP error occurred while deleting user {user_id}: {str(e)}")
        raise e
    except Exception as e:
        logging_utility.error(f"An unexpected error occurred while deleting user {user_id}: {str(e)}")
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")


@router.post("/threads", response_model=ThreadReadDetailed)
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


@router.get("/threads/{thread_id}", response_model=ThreadRead)
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


@router.get("/users/{user_id}/threads", response_model=ThreadIds)
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


@router.post("/messages", response_model=MessageRead)
def create_message(message: MessageCreate, db: Session = Depends(get_db)):
    logging_utility.info(f"Received request to create a new message in thread ID: {message.thread_id}")
    message_service = MessageService(db)
    try:
        new_message = message_service.create_message(message)
        logging_utility.info(f"Message created successfully with ID: {new_message.id}")
        return new_message
    except HTTPException as e:
        logging_utility.error(f"HTTP error occurred while creating message: {str(e)}")
        raise e
    except Exception as e:
        logging_utility.error(f"An unexpected error occurred while creating message: {str(e)}")
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")


@router.get("/messages/{message_id}", response_model=MessageRead)
def get_message(message_id: str, db: Session = Depends(get_db)):
    logging_utility.info(f"Received request to get message with ID: {message_id}")
    message_service = MessageService(db)
    try:
        message = message_service.retrieve_message(message_id)
        logging_utility.info(f"Message retrieved successfully with ID: {message_id}")
        return message
    except HTTPException as e:
        logging_utility.error(f"HTTP error occurred while retrieving message {message_id}: {str(e)}")
        raise e
    except Exception as e:
        logging_utility.error(f"An unexpected error occurred while retrieving message {message_id}: {str(e)}")
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")


@router.get("/threads/{thread_id}/messages", response_model=List[MessageRead])
def list_messages(thread_id: str, limit: int = 20, order: str = "asc", db: Session = Depends(get_db)):
    logging_utility.info(f"Received request to list messages for thread ID: {thread_id}")
    message_service = MessageService(db)
    try:
        messages = message_service.list_messages(thread_id=thread_id, limit=limit, order=order)
        logging_utility.info(f"Successfully retrieved messages for thread ID: {thread_id}")
        return messages
    except HTTPException as e:
        logging_utility.error(f"HTTP error occurred while listing messages for thread {thread_id}: {str(e)}")
        raise e
    except Exception as e:
        logging_utility.error(f"An unexpected error occurred while listing messages for thread {thread_id}: {str(e)}")
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")


@router.post("/runs", response_model=Run)
def create_run(run: Run, db: Session = Depends(get_db)):
    logging_utility.info(f"Received request to create a new run for thread ID: {run.thread_id}")
    run_service = RunService(db)
    try:
        new_run = run_service.create_run(run)
        logging_utility.info(f"Run created successfully with ID: {new_run.id}")
        return new_run
    except HTTPException as e:
        logging_utility.error(f"HTTP error occurred while creating run: {str(e)}")
        raise e
    except Exception as e:
        logging_utility.error(f"An unexpected error occurred while creating run: {str(e)}")
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")


@router.get("/runs/{run_id}", response_model=Run)
def get_run(run_id: str, db: Session = Depends(get_db)):
    logging_utility.info(f"Received request to get run with ID: {run_id}")
    run_service = RunService(db)
    try:
        run = run_service.get_run(run_id)
        logging_utility.info(f"Run retrieved successfully with ID: {run_id}")
        return run
    except HTTPException as e:
        logging_utility.error(f"HTTP error occurred while retrieving run {run_id}: {str(e)}")
        raise e
    except Exception as e:
        logging_utility.error(f"An unexpected error occurred while retrieving run {run_id}: {str(e)}")
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")


@router.put("/runs/{run_id}/status", response_model=Run)
def update_run_status(run_id: str, status_update: RunStatusUpdate, db: Session = Depends(get_db)):
    logging_utility.info(f"Received request to update status of run ID: {run_id} to {status_update.status}")
    run_service = RunService(db)
    try:
        updated_run = run_service.update_run_status(run_id, status_update.status)
        logging_utility.info(f"Run status updated successfully for run ID: {run_id}")
        return updated_run
    except HTTPException as e:
        logging_utility.error(f"HTTP error occurred while updating run status {run_id}: {str(e)}")
        raise e
    except Exception as e:
        logging_utility.error(f"An unexpected error occurred while updating run status {run_id}: {str(e)}")
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")


@router.post("/runs/{run_id}/cancel", response_model=Run)
def cancel_run(run_id: str, db: Session = Depends(get_db)):
    logging_utility.info(f"Received request to cancel run with ID: {run_id}")
    run_service = RunService(db)
    try:
        cancelled_run = run_service.cancel_run(run_id)
        logging_utility.info(f"Run cancelled successfully with ID: {run_id}")
        return cancelled_run
    except HTTPException as e:
        logging_utility.error(f"HTTP error occurred while cancelling run {run_id}: {str(e)}")
        raise e
    except Exception as e:
        logging_utility.error(f"An unexpected error occurred while cancelling run {run_id}: {str(e)}")
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")


@router.post("/assistants", response_model=AssistantRead)
def create_assistant(assistant: AssistantCreate, db: Session = Depends(get_db)):
    logging_utility.info(f"Received request to create a new assistant.")
    assistant_service = AssistantService(db)
    try:
        new_assistant = assistant_service.create_assistant(assistant)
        logging_utility.info(f"Assistant created successfully with ID: {new_assistant.id}")
        return new_assistant
    except HTTPException as e:
        logging_utility.error(f"HTTP error occurred while creating assistant: {str(e)}")
        raise e
    except Exception as e:
        logging_utility.error(f"An unexpected error occurred while creating assistant: {str(e)}")
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")


@router.get("/assistants/{assistant_id}", response_model=AssistantRead)
def get_assistant(assistant_id: str, db: Session = Depends(get_db)):
    logging_utility.info(f"Received request to get assistant with ID: {assistant_id}")
    assistant_service = AssistantService(db)
    try:
        assistant = assistant_service.get_assistant(assistant_id)
        logging_utility.info(f"Assistant retrieved successfully with ID: {assistant_id}")
        return assistant
    except HTTPException as e:
        logging_utility.error(f"HTTP error occurred while retrieving assistant {assistant_id}: {str(e)}")
        raise e
    except Exception as e:
        logging_utility.error(f"An unexpected error occurred while retrieving assistant {assistant_id}: {str(e)}")
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")


@router.put("/assistants/{assistant_id}", response_model=AssistantRead)
def update_assistant(assistant_id: str, assistant_update: AssistantUpdate, db: Session = Depends(get_db)):
    logging_utility.info(f"Received request to update assistant with ID: {assistant_id}")
    assistant_service = AssistantService(db)
    try:
        updated_assistant = assistant_service.update_assistant(assistant_id, assistant_update)
        logging_utility.info(f"Assistant updated successfully with ID: {assistant_id}")
        return updated_assistant
    except HTTPException as e:
        logging_utility.error(f"HTTP error occurred while updating assistant {assistant_id}: {str(e)}")
        raise e
    except Exception as e:
        logging_utility.error(f"An unexpected error occurred while updating assistant {assistant_id}: {str(e)}")
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")


@router.get("/threads/{thread_id}/formatted_messages", response_model=List[Dict[str, Any]])
def get_formatted_messages(thread_id: str, db: Session = Depends(get_db)):
    logging_utility.info(f"Received request to get formatted messages for thread ID: {thread_id}")
    message_service = MessageService(db)
    try:
        messages = message_service.list_messages_for_thread(thread_id)
        logging_utility.info(f"Formatted messages retrieved successfully for thread ID: {thread_id}")
        return messages
    except HTTPException as e:
        logging_utility.error(f"HTTP error occurred while retrieving formatted messages for thread {thread_id}: {str(e)}")
        raise e
    except Exception as e:
        logging_utility.error(f"An unexpected error occurred while retrieving formatted messages for thread {thread_id}: {str(e)}")
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")


@router.post("/messages/assistant", response_model=MessageRead)
def save_assistant_message(message: MessageCreate, db: Session = Depends(get_db)):
    logging_utility.info(f"Received request to save assistant message in thread ID: {message.thread_id}")
    message_service = MessageService(db)
    try:
        new_message = message_service.save_assistant_message_chunk(
            thread_id=message.thread_id,
            content=message.content,
            is_last_chunk=True  # Assuming we're always sending the complete message
        )
        logging_utility.info(f"Assistant message saved successfully with ID: {new_message.id}")
        return new_message
    except HTTPException as e:
        logging_utility.error(f"HTTP error occurred while saving assistant message: {str(e)}")
        raise e
    except Exception as e:
        logging_utility.error(f"An unexpected error occurred while saving assistant message: {str(e)}")
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")


@router.post("/messages/{message_id}/tool", response_model=MessageRead)
def add_tool_message(message_id: str, tool_message: ToolMessageCreate, db: Session = Depends(get_db)):
    logging_utility.info(f"Received request to add tool message to message ID: {message_id}")
    message_service = MessageService(db)
    try:
        updated_message = message_service.add_tool_message(message_id, tool_message.content)
        logging_utility.info(f"Tool message added successfully to message ID: {message_id}")
        return updated_message
    except HTTPException as e:
        logging_utility.error(f"HTTP error occurred while adding tool message to message {message_id}: {str(e)}")
        raise e
    except Exception as e:
        logging_utility.error(f"An unexpected error occurred while adding tool message to message {message_id}: {str(e)}")
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")


@router.post("/tools", response_model=ToolRead)
def create_tool(tool: ToolCreate, db: Session = Depends(get_db)):
    logging_utility.info(f"Received request to create a new tool.")
    tool_service = ToolService(db)
    try:
        new_tool = tool_service.create_tool(tool)
        logging_utility.info(f"Tool created successfully with ID: {new_tool.id}")
        return new_tool
    except HTTPException as e:
        logging_utility.error(f"HTTP error occurred while creating tool: {str(e)}")
        raise e
    except Exception as e:
        logging_utility.error(f"An unexpected error occurred while creating tool: {str(e)}")
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")


@router.post("/assistants/{assistant_id}/tools/{tool_id}")
def associate_tool_with_assistant(assistant_id: str, tool_id: str, db: Session = Depends(get_db)):
    logging_utility.info(f"Received request to associate tool ID: {tool_id} with assistant ID: {assistant_id}")
    tool_service = ToolService(db)
    try:
        tool_service.associate_tool_with_assistant(tool_id, assistant_id)
        logging_utility.info(f"Tool ID: {tool_id} associated successfully with assistant ID: {assistant_id}")
        return {"message": "Tool associated with assistant successfully"}
    except HTTPException as e:
        logging_utility.error(f"HTTP error occurred while associating tool {tool_id} with assistant {assistant_id}: {str(e)}")
        raise e
    except Exception as e:
        logging_utility.error(f"An unexpected error occurred while associating tool {tool_id} with assistant {assistant_id}: {str(e)}")
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")


@router.get("/tools/{tool_id}", response_model=ToolRead)
def get_tool(tool_id: str, db: Session = Depends(get_db)):
    logging_utility.info(f"Received request to get tool with ID: {tool_id}")
    tool_service = ToolService(db)
    try:
        tool = tool_service.get_tool(tool_id)
        logging_utility.info(f"Tool retrieved successfully with ID: {tool_id}")
        return tool
    except HTTPException as e:
        logging_utility.error(f"HTTP error occurred while retrieving tool {tool_id}: {str(e)}")
        raise e
    except Exception as e:
        logging_utility.error(f"An unexpected error occurred while retrieving tool {tool_id}: {str(e)}")
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")


@router.get("/tools/name/{name}", response_model=ToolRead)
def get_tool_by_name(name: str, db: Session = Depends(get_db)):
    logging_utility.info(f"Received request to get tool by name: {name}")
    tool_service = ToolService(db)
    try:
        tool = tool_service.get_tool_by_name(name)
        logging_utility.info(f"Tool retrieved successfully with name: {name}")
        return tool
    except HTTPException as e:
        logging_utility.error(f"HTTP error occurred while retrieving tool by name {name}: {str(e)}")
        raise e
    except Exception as e:
        logging_utility.error(f"An unexpected error occurred while retrieving tool by name {name}: {str(e)}")
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")


@router.put("/tools/{tool_id}", response_model=ToolRead)
def update_tool(tool_id: str, tool_update: ToolUpdate, db: Session = Depends(get_db)):
    logging_utility.info(f"Received request to update tool with ID: {tool_id}")
    tool_service = ToolService(db)
    try:
        updated_tool = tool_service.update_tool(tool_id, tool_update)
        logging_utility.info(f"Tool updated successfully with ID: {tool_id}")
        return updated_tool
    except HTTPException as e:
        logging_utility.error(f"HTTP error occurred while updating tool {tool_id}: {str(e)}")
        raise e
    except Exception as e:
        logging_utility.error(f"An unexpected error occurred while updating tool {tool_id}: {str(e)}")
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")


@router.delete("/tools/{tool_id}", status_code=204)
def delete_tool(tool_id: str, db: Session = Depends(get_db)):
    logging_utility.info(f"Received request to delete tool with ID: {tool_id}")
    tool_service = ToolService(db)
    try:
        tool_service.delete_tool(tool_id)
        logging_utility.info(f"Tool deleted successfully with ID: {tool_id}")
        return {"detail": "Tool deleted successfully"}
    except HTTPException as e:
        logging_utility.error(f"HTTP error occurred while deleting tool {tool_id}: {str(e)}")
        raise e
    except Exception as e:
        logging_utility.error(f"An unexpected error occurred while deleting tool {tool_id}: {str(e)}")
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")


@router.get("/tools", response_model=ToolList)
@router.get("/assistants/{assistant_id}/tools", response_model=ToolList)
def list_tools(assistant_id: str = None, db: Session = Depends(get_db)):
    if assistant_id:
        logging_utility.info(f"Received request to list tools for assistant ID: {assistant_id}")
    else:
        logging_utility.info("Received request to list all tools.")
    tool_service = ToolService(db)
    try:
        tools = tool_service.list_tools(assistant_id)
        logging_utility.info("Tools retrieved successfully.")
        return ToolList(tools=tools)
    except HTTPException as e:
        logging_utility.error(f"HTTP error occurred while listing tools: {str(e)}")
        raise e
    except Exception as e:
        logging_utility.error(f"An unexpected error occurred while listing tools: {str(e)}")
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")


@router.post("/actions", response_model=ActionRead)
def create_action(action: ActionCreate, db: Session = Depends(get_db)):
    logging_utility.info(f"Received request to create a new action.")
    action_service = ActionService(db)
    try:
        new_action = action_service.create_action(action)
        logging_utility.info(f"Action created successfully with ID: {new_action.id}")
        return new_action
    except HTTPException as e:
        logging_utility.error(f"HTTP error occurred while creating action: {str(e)}")
        raise e
    except Exception as e:
        logging_utility.error(f"An unexpected error occurred while creating action: {str(e)}")
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")


@router.get("/actions/{action_id}", response_model=ActionRead)
def get_action(action_id: str, db: Session = Depends(get_db)):
    logging_utility.info(f"Received request to get action with ID: {action_id}")
    action_service = ActionService(db)
    try:
        action = action_service.get_action(action_id)
        logging_utility.info(f"Action retrieved successfully with ID: {action_id}")
        return action
    except HTTPException as e:
        logging_utility.error(f"HTTP error occurred while retrieving action {action_id}: {str(e)}")
        raise e
    except Exception as e:
        logging_utility.error(f"An unexpected error occurred while retrieving action {action_id}: {str(e)}")
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")


@router.put("/actions/{action_id}", response_model=ActionRead)
def update_action_status(action_id: str, action_update: ActionUpdate, db: Session = Depends(get_db)):
    logging_utility.info(f"Received request to update status of action ID: {action_id}")
    action_service = ActionService(db)
    try:
        updated_action = action_service.update_action_status(action_id, action_update)
        logging_utility.info(f"Action status updated successfully for action ID: {action_id}")
        return updated_action
    except HTTPException as e:
        logging_utility.error(f"HTTP error occurred while updating action status {action_id}: {str(e)}")
        raise e
    except Exception as e:
        logging_utility.error(f"An unexpected error occurred while updating action status {action_id}: {str(e)}")
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")


@router.get("/runs/{run_id}/actions/status", response_model=List[ActionRead])
def get_actions_by_status(run_id: str, status: Optional[str] = "pending", db: Session = Depends(get_db)):
    logging_utility.info(f"Received request to get actions for run ID: {run_id} with status: {status}")
    action_service = ActionService(db)
    try:
        actions = action_service.get_actions_by_status(run_id, status)
        logging_utility.info(f"Actions retrieved successfully for run ID: {run_id} with status: {status}")
        return actions
    except HTTPException as e:
        logging_utility.error(f"HTTP error occurred while retrieving actions for run {run_id} with status {status}: {str(e)}")
        raise e
    except Exception as e:
        logging_utility.error(f"An unexpected error occurred while retrieving actions for run {run_id} with status {status}: {str(e)}")
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")


@router.delete("/actions/{action_id}", status_code=204)
def delete_action(action_id: str, db: Session = Depends(get_db)):
    logging_utility.info(f"Received request to delete action with ID: {action_id}")
    action_service = ActionService(db)
    try:
        action_service.delete_action(action_id)
        logging_utility.info(f"Action deleted successfully with ID: {action_id}")
        return {"detail": "Action deleted successfully"}
    except HTTPException as e:
        logging_utility.error(f"HTTP error occurred while deleting action {action_id}: {str(e)}")
        raise e
    except Exception as e:
        logging_utility.error(f"An unexpected error occurred while deleting action {action_id}: {str(e)}")
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")


# Create Sandbox
@router.post("/sandboxes", response_model=SandboxRead)
def create_sandbox(sandbox_data: SandboxCreate, db: Session = Depends(get_db)):
    logging_utility.info(f"Received request to create sandbox for user_id: {sandbox_data.user_id}")
    sandbox_service = SandboxService(db)
    try:
        new_sandbox = sandbox_service.create_sandbox(sandbox_data)
        logging_utility.info(f"Sandbox created with ID: {new_sandbox.id}")
        return new_sandbox
    except HTTPException as e:
        logging_utility.error(f"HTTP error during sandbox creation: {str(e)}")
        raise e
    except Exception as e:
        logging_utility.error(f"Unexpected error during sandbox creation: {str(e)}")
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")

# Get Sandbox
@router.get("/sandboxes/{sandbox_id}", response_model=SandboxRead)
def get_sandbox(sandbox_id: str, db: Session = Depends(get_db)):
    logging_utility.info(f"Received request to get sandbox with ID: {sandbox_id}")
    sandbox_service = SandboxService(db)
    try:
        sandbox = sandbox_service.get_sandbox(sandbox_id)
        logging_utility.info(f"Sandbox retrieved with ID: {sandbox_id}")
        return sandbox
    except HTTPException as e:
        logging_utility.error(f"HTTP error during sandbox retrieval: {str(e)}")
        raise e
    except Exception as e:
        logging_utility.error(f"Unexpected error during sandbox retrieval: {str(e)}")
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")

# Update Sandbox
@router.put("/sandboxes/{sandbox_id}", response_model=SandboxRead)
def update_sandbox(sandbox_id: str, sandbox_update: SandboxUpdate, db: Session = Depends(get_db)):
    logging_utility.info(f"Received request to update sandbox with ID: {sandbox_id}")
    sandbox_service = SandboxService(db)
    try:
        updated_sandbox = sandbox_service.update_sandbox(sandbox_id, sandbox_update)
        logging_utility.info(f"Sandbox updated with ID: {sandbox_id}")
        return updated_sandbox
    except HTTPException as e:
        logging_utility.error(f"HTTP error during sandbox update: {str(e)}")
        raise e
    except Exception as e:
        logging_utility.error(f"Unexpected error during sandbox update: {str(e)}")
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")

# Delete Sandbox
@router.delete("/sandboxes/{sandbox_id}", status_code=204)
def delete_sandbox(sandbox_id: str, db: Session = Depends(get_db)):
    logging_utility.info(f"Received request to delete sandbox with ID: {sandbox_id}")
    sandbox_service = SandboxService(db)
    try:
        sandbox_service.delete_sandbox(sandbox_id)
        logging_utility.info(f"Sandbox deleted with ID: {sandbox_id}")
        return {"detail": "Sandbox deleted successfully"}
    except HTTPException as e:
        logging_utility.error(f"HTTP error during sandbox deletion: {str(e)}")
        raise e
    except Exception as e:
        logging_utility.error(f"Unexpected error during sandbox deletion: {str(e)}")
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")

# List Sandboxes for a User
@router.get("/users/{user_id}/sandboxes", response_model=List[SandboxRead])
def list_sandboxes_by_user(user_id: str, db: Session = Depends(get_db)):
    logging_utility.info(f"Received request to list sandboxes for user ID: {user_id}")
    sandbox_service = SandboxService(db)
    try:
        sandboxes = sandbox_service.list_sandboxes_by_user(user_id)
        logging_utility.info(f"Sandboxes retrieved for user ID: {user_id}")
        return sandboxes
    except HTTPException as e:
        logging_utility.error(f"HTTP error during listing sandboxes: {str(e)}")
        raise e
    except Exception as e:
        logging_utility.error(f"Unexpected error during listing sandboxes: {str(e)}")
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")