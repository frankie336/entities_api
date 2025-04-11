from fastapi import APIRouter, Depends, HTTPException
from projectdavid_common import ValidationInterface
from projectdavid_common.utilities.logging_service import LoggingUtility
from sqlalchemy.orm import Session

from entities_api.dependencies import get_db
from entities_api.services.tools import ToolService

validation = ValidationInterface()

router = APIRouter()
logging_utility = LoggingUtility()


@router.post("/tools", response_model=validation.ToolRead)
def create_tool(tool: validation.ToolCreate, db: Session = Depends(get_db)):
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
        logging_utility.error(
            f"An unexpected error occurred while creating tool: {str(e)}"
        )
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")


@router.post("/assistants/{assistant_id}/tools/{tool_id}")
def associate_tool_with_assistant(
    assistant_id: str, tool_id: str, db: Session = Depends(get_db)
):
    logging_utility.info(
        f"Received request to associate tool ID: {tool_id} with assistant ID: {assistant_id}"
    )
    tool_service = ToolService(db)
    try:
        tool_service.associate_tool_with_assistant(tool_id, assistant_id)
        logging_utility.info(
            f"Tool ID: {tool_id} associated successfully with assistant ID: {assistant_id}"
        )
        return {"message": "Tool associated with assistant successfully"}
    except HTTPException as e:
        logging_utility.error(
            f"HTTP error occurred while associating tool {tool_id} with assistant {assistant_id}: {str(e)}"
        )
        raise e
    except Exception as e:
        logging_utility.error(
            f"An unexpected error occurred while associating tool {tool_id} with assistant {assistant_id}: {str(e)}"
        )
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")


@router.delete("/assistants/{assistant_id}/tools/{tool_id}", status_code=204)
def disassociate_tool_from_assistant(
    assistant_id: str, tool_id: str, db: Session = Depends(get_db)
):
    """
    Endpoint to disassociate a tool from an assistant.
    """
    logging_utility.info(
        f"Received request to disassociate tool ID: {tool_id} from assistant ID: {assistant_id}"
    )
    tool_service = ToolService(db)
    try:
        tool_service.disassociate_tool_from_assistant(tool_id, assistant_id)
        logging_utility.info(
            f"Tool ID: {tool_id} disassociated successfully from assistant ID: {assistant_id}"
        )
        return {"message": "Tool disassociated from assistant successfully"}
    except HTTPException as e:
        logging_utility.error(
            f"HTTP error occurred while disassociating tool {tool_id} from assistant {assistant_id}: {str(e)}"
        )
        raise e
    except Exception as e:
        logging_utility.error(
            f"An unexpected error occurred while disassociating tool {tool_id} from assistant {assistant_id}: {str(e)}"
        )
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")


@router.get("/tools/{tool_id}", response_model=validation.ToolRead)
def get_tool(tool_id: str, db: Session = Depends(get_db)):
    logging_utility.info(f"Received request to get tool with ID: {tool_id}")
    tool_service = ToolService(db)
    try:
        tool = tool_service.get_tool(tool_id)
        logging_utility.info(f"Tool retrieved successfully with ID: {tool_id}")
        return tool
    except HTTPException as e:
        logging_utility.error(
            f"HTTP error occurred while retrieving tool {tool_id}: {str(e)}"
        )
        raise e
    except Exception as e:
        logging_utility.error(
            f"An unexpected error occurred while retrieving tool {tool_id}: {str(e)}"
        )
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")


@router.get("/tools/name/{name}", response_model=validation.ToolRead)
def get_tool_by_name(name: str, db: Session = Depends(get_db)):
    logging_utility.info(f"Received request to get tool by name: {name}")
    tool_service = ToolService(db)
    try:
        tool = tool_service.get_tool_by_name(name)
        logging_utility.info(f"Tool retrieved successfully with name: {name}")
        return tool
    except HTTPException as e:
        logging_utility.error(
            f"HTTP error occurred while retrieving tool by name {name}: {str(e)}"
        )
        raise e
    except Exception as e:
        logging_utility.error(
            f"An unexpected error occurred while retrieving tool by name {name}: {str(e)}"
        )
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")


@router.put("/tools/{tool_id}", response_model=validation.ToolRead)
def update_tool(
    tool_id: str, tool_update: validation.ToolUpdate, db: Session = Depends(get_db)
):
    logging_utility.info(f"Received request to update tool with ID: {tool_id}")
    tool_service = ToolService(db)
    try:
        updated_tool = tool_service.update_tool(tool_id, tool_update)
        logging_utility.info(f"Tool updated successfully with ID: {tool_id}")
        return updated_tool
    except HTTPException as e:
        logging_utility.error(
            f"HTTP error occurred while updating tool {tool_id}: {str(e)}"
        )
        raise e
    except Exception as e:
        logging_utility.error(
            f"An unexpected error occurred while updating tool {tool_id}: {str(e)}"
        )
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
        logging_utility.error(
            f"HTTP error occurred while deleting tool {tool_id}: {str(e)}"
        )
        raise e
    except Exception as e:
        logging_utility.error(
            f"An unexpected error occurred while deleting tool {tool_id}: {str(e)}"
        )
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")


@router.get("/tools", response_model=validation.ToolList)
@router.get("/assistants/{assistant_id}/tools", response_model=validation.ToolList)
def list_tools(assistant_id: str = None, db: Session = Depends(get_db)):
    if assistant_id:
        logging_utility.info(
            f"Received request to list tools for assistant ID: {assistant_id}"
        )
    else:
        logging_utility.info("Received request to list all tools.")
    tool_service = ToolService(db)
    try:
        tools = tool_service.list_tools(assistant_id)
        logging_utility.info("Tools retrieved successfully.")
        return validation.ToolList(tools=tools)
    except HTTPException as e:
        logging_utility.error(f"HTTP error occurred while listing tools: {str(e)}")
        raise e
    except Exception as e:
        logging_utility.error(
            f"An unexpected error occurred while listing tools: {str(e)}"
        )
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")
