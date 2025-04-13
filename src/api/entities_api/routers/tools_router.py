from fastapi import APIRouter, Depends, HTTPException, status
from projectdavid_common import ValidationInterface
from projectdavid_common.utilities.logging_service import LoggingUtility
from sqlalchemy.orm import Session

from entities_api.dependencies import get_api_key, get_db
from entities_api.models.models import ApiKey as ApiKeyModel
from entities_api.services.tools import ToolService

validation = ValidationInterface()
router = APIRouter()
logging_utility = LoggingUtility()


@router.post(
    "/tools", response_model=validation.ToolRead, status_code=status.HTTP_201_CREATED
)
def create_tool(
    tool: validation.ToolCreate,
    db: Session = Depends(get_db),
    auth_key: ApiKeyModel = Depends(get_api_key),
):
    logging_utility.info(f"[{auth_key.user_id}] Creating a new tool.")
    tool_service = ToolService(db)
    new_tool = tool_service.create_tool(tool)
    return new_tool


@router.post("/assistants/{assistant_id}/tools/{tool_id}")
def associate_tool_with_assistant(
    assistant_id: str,
    tool_id: str,
    db: Session = Depends(get_db),
    auth_key: ApiKeyModel = Depends(get_api_key),
):
    logging_utility.info(
        f"[{auth_key.user_id}] Associating tool {tool_id} with assistant {assistant_id}"
    )
    tool_service = ToolService(db)
    tool_service.associate_tool_with_assistant(tool_id, assistant_id)
    return {"message": "Tool associated with assistant successfully"}


@router.delete(
    "/assistants/{assistant_id}/tools/{tool_id}", status_code=status.HTTP_204_NO_CONTENT
)
def disassociate_tool_from_assistant(
    assistant_id: str,
    tool_id: str,
    db: Session = Depends(get_db),
    auth_key: ApiKeyModel = Depends(get_api_key),
):
    logging_utility.info(
        f"[{auth_key.user_id}] Disassociating tool {tool_id} from assistant {assistant_id}"
    )
    tool_service = ToolService(db)
    tool_service.disassociate_tool_from_assistant(tool_id, assistant_id)
    return {"message": "Tool disassociated from assistant successfully"}


@router.get("/tools/{tool_id}", response_model=validation.ToolRead)
def get_tool(
    tool_id: str,
    db: Session = Depends(get_db),
    auth_key: ApiKeyModel = Depends(get_api_key),
):
    logging_utility.info(f"[{auth_key.user_id}] Fetching tool {tool_id}")
    tool_service = ToolService(db)
    return tool_service.get_tool(tool_id)


@router.get("/tools/name/{name}", response_model=validation.ToolRead)
def get_tool_by_name(
    name: str,
    db: Session = Depends(get_db),
    auth_key: ApiKeyModel = Depends(get_api_key),
):
    logging_utility.info(f"[{auth_key.user_id}] Fetching tool by name: {name}")
    tool_service = ToolService(db)
    return tool_service.get_tool_by_name(name)


@router.put("/tools/{tool_id}", response_model=validation.ToolRead)
def update_tool(
    tool_id: str,
    tool_update: validation.ToolUpdate,
    db: Session = Depends(get_db),
    auth_key: ApiKeyModel = Depends(get_api_key),
):
    logging_utility.info(f"[{auth_key.user_id}] Updating tool {tool_id}")
    tool_service = ToolService(db)
    return tool_service.update_tool(tool_id, tool_update)


@router.delete("/tools/{tool_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_tool(
    tool_id: str,
    db: Session = Depends(get_db),
    auth_key: ApiKeyModel = Depends(get_api_key),
):
    logging_utility.info(f"[{auth_key.user_id}] Deleting tool {tool_id}")
    tool_service = ToolService(db)
    tool_service.delete_tool(tool_id)
    return {"detail": "Tool deleted successfully"}


@router.get("/tools", response_model=validation.ToolList)
@router.get("/assistants/{assistant_id}/tools", response_model=validation.ToolList)
def list_tools(
    assistant_id: str = None,
    db: Session = Depends(get_db),
    auth_key: ApiKeyModel = Depends(get_api_key),
):
    logging_utility.info(
        f"[{auth_key.user_id}] Listing tools for assistant: {assistant_id or 'ALL'}"
    )
    tool_service = ToolService(db)
    tools = tool_service.list_tools(assistant_id)
    return validation.ToolList(tools=tools)
