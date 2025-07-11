from typing import List, Optional

from fastapi import HTTPException
from projectdavid_common import UtilsInterface, ValidationInterface
from projectdavid_common.constants.tools import TOOLS_ID_MAP
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from src.api.entities_api.models.models import Assistant, Tool
from src.api.entities_api.services.logging_service import LoggingUtility

validator = ValidationInterface()
logging_utility = LoggingUtility()


class ToolService:

    def __init__(self, db: Session):
        self.db = db
        logging_utility.info("ToolService initialized with database session.")

    def create_tool(
        self, tool: validator.ToolCreate, set_id: Optional[str] = None
    ) -> validator.ToolRead:
        """
        Create a tool.

        • If `tool.name` **or** `tool.type` is one of the reserved tool-keys
          (code_interpreter, web_search, …) we enforce the canonical ID
          from TOOLS_ID_MAP.

        • If the caller tries to override that ID we reject the request.

        • For non-reserved tools we either use the supplied `set_id`
          (provided it is not in the reserved map **and** not already taken)
          or generate a fresh one.
        """
        logging_utility.info("Starting create_tool %s (requested id=%s)", tool, set_id)
        reserved_key = None
        if tool.name in TOOLS_ID_MAP:
            reserved_key = tool.name
        elif tool.type in TOOLS_ID_MAP:
            reserved_key = tool.type
        if reserved_key:
            canonical_id = TOOLS_ID_MAP[reserved_key]
            if set_id and set_id != canonical_id:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid set_id for reserved tool '{reserved_key}'. Expected '{canonical_id}'.",
                )
            tool_id = canonical_id
            logging_utility.debug(
                "Reserved tool ➜ using canonical ID %s for key %s",
                tool_id,
                reserved_key,
            )
        elif set_id:
            if set_id in TOOLS_ID_MAP.values():
                raise HTTPException(
                    status_code=400, detail="set_id collides with a reserved tool id"
                )
            tool_id = set_id
            logging_utility.debug("Using client-supplied id: %s", tool_id)
        else:
            tool_id = UtilsInterface.IdentifierService.generate_tool_id()
            logging_utility.debug("Generated tool id: %s", tool_id)
        try:
            db_tool = Tool(
                id=tool_id,
                name=tool.name,
                type=tool.type,
                function=tool.function.dict() if tool.function else None,
            )
            self.db.add(db_tool)
            self.db.commit()
            self.db.refresh(db_tool)
            logging_utility.info("Tool created successfully with ID: %s", tool_id)
            return validator.ToolRead.model_validate(db_tool)
        except IntegrityError as e:
            self.db.rollback()
            logging_utility.error("IntegrityError during tool creation: %s", str(e))
            raise HTTPException(status_code=400, detail="Duplicate tool id or name")
        except Exception as e:
            self.db.rollback()
            logging_utility.error("Unexpected error during tool creation: %s", str(e))
            raise HTTPException(
                status_code=500, detail="An error occurred while creating the tool"
            )

    def associate_tool_with_assistant(self, tool_id: str, assistant_id: str) -> None:
        logging_utility.info(
            "Associating tool with ID %s to assistant with ID %s", tool_id, assistant_id
        )
        try:
            tool = self._get_tool_or_404(tool_id)
            assistant = (
                self.db.query(Assistant).filter(Assistant.id == assistant_id).first()
            )
            if not assistant:
                logging_utility.warning("Assistant with ID %s not found.", assistant_id)
                raise HTTPException(
                    status_code=404,
                    detail=f"Assistant with id {assistant_id} not found",
                )
            assistant.tools.append(tool)
            self.db.commit()
            logging_utility.info(
                "Successfully associated tool ID %s with assistant ID %s",
                tool_id,
                assistant_id,
            )
        except HTTPException as e:
            logging_utility.error("HTTPException: %s", str(e))
            raise
        except Exception as e:
            self.db.rollback()
            logging_utility.error("Error associating tool with assistant: %s", str(e))
            raise HTTPException(
                status_code=500, detail="An error occurred while creating the tool"
            )

    def disassociate_tool_from_assistant(self, tool_id: str, assistant_id: str) -> None:
        logging_utility.info(
            "Disassociating tool with ID %s from assistant with ID %s",
            tool_id,
            assistant_id,
        )
        try:
            tool = self._get_tool_or_404(tool_id)
            assistant = (
                self.db.query(Assistant).filter(Assistant.id == assistant_id).first()
            )
            if not assistant:
                logging_utility.warning("Assistant with ID %s not found.", assistant_id)
                raise HTTPException(
                    status_code=404,
                    detail=f"Assistant with id {assistant_id} not found",
                )
            if tool in assistant.tools:
                assistant.tools.remove(tool)
                self.db.commit()
                logging_utility.info(
                    "Successfully disassociated tool ID %s from assistant ID %s",
                    tool_id,
                    assistant_id,
                )
            else:
                raise HTTPException(
                    status_code=400, detail="Tool not associated with the assistant"
                )
        except HTTPException as e:
            logging_utility.error("HTTPException: %s", str(e))
            raise
        except Exception as e:
            self.db.rollback()
            logging_utility.error(
                "Error disassociating tool from assistant: %s", str(e)
            )
            raise HTTPException(
                status_code=500,
                detail="An error occurred while disassociating the tool from the assistant",
            )

    def get_tool(self, tool_id: str) -> validator.ToolRead:
        logging_utility.info("Retrieving tool with ID: %s", tool_id)
        try:
            db_tool = self._get_tool_or_404(tool_id)
            logging_utility.info("Tool retrieved successfully: %s", db_tool)
            return validator.ToolRead.model_validate(db_tool)
        except HTTPException as e:
            logging_utility.error("HTTPException: %s", str(e))
            raise
        except Exception as e:
            logging_utility.error("Unexpected error retrieving tool: %s", str(e))
            raise HTTPException(
                status_code=500, detail="An error occurred while retrieving the tool"
            )

    def get_tool_by_name(self, name: str) -> validator.ToolRead:
        """Retrieve a tool by its name."""
        logging_utility.info("Retrieving tool by name: %s", name)
        try:
            db_tool = self.db.query(Tool).filter(Tool.name == name).first()
            if not db_tool:
                logging_utility.warning("Tool with name %s not found", name)
                raise HTTPException(
                    status_code=404, detail=f"Tool with name {name} not found"
                )
            logging_utility.info("Tool retrieved successfully: %s", db_tool)
            return validator.ToolRead.model_validate(db_tool)
        except Exception as e:
            logging_utility.error("Unexpected error retrieving tool: %s", str(e))
            raise HTTPException(
                status_code=500, detail="An error occurred while retrieving the tool"
            )

    def update_tool(
        self, tool_id: str, tool_update: validator.ToolUpdate
    ) -> validator.ToolRead:
        logging_utility.info(
            "Updating tool with ID: %s, ToolUpdate: %s", tool_id, tool_update
        )
        try:
            db_tool = self._get_tool_or_404(tool_id)
            update_data = tool_update.model_dump(exclude_unset=True)
            logging_utility.debug("Updating tool with data: %s", update_data)
            for key, value in update_data.items():
                setattr(db_tool, key, value)
            self.db.commit()
            self.db.refresh(db_tool)
            logging_utility.info("Tool with ID %s updated successfully", tool_id)
            return validator.ToolRead.model_validate(db_tool)
        except HTTPException as e:
            logging_utility.error("HTTPException: %s", str(e))
            raise
        except Exception as e:
            self.db.rollback()
            logging_utility.error("Error updating tool: %s", str(e))
            raise HTTPException(
                status_code=500, detail="An error occurred while updating the tool"
            )

    def delete_tool(self, tool_id: str) -> None:
        logging_utility.info("Deleting tool with ID: %s", tool_id)
        try:
            db_tool = self._get_tool_or_404(tool_id)
            self.db.delete(db_tool)
            self.db.commit()
            logging_utility.info("Tool with ID %s deleted successfully", tool_id)
        except HTTPException as e:
            logging_utility.error("HTTPException: %s", str(e))
            raise
        except Exception as e:
            self.db.rollback()
            logging_utility.error("Error deleting tool: %s", str(e))
            raise HTTPException(
                status_code=500, detail="An error occurred while deleting the tool"
            )

    def list_tools(
        self, assistant_id: Optional[str] = None, restructure: bool = False
    ) -> List[dict]:
        logging_utility.info("Listing tools for assistant ID: %s", assistant_id)
        try:
            if assistant_id:
                assistant = (
                    self.db.query(Assistant)
                    .options(joinedload(Assistant.tools))
                    .filter(Assistant.id == assistant_id)
                    .first()
                )
                logging_utility.debug("Assistant found: %s", assistant)
                if not assistant:
                    logging_utility.warning(
                        "Assistant with ID %s not found", assistant_id
                    )
                    raise HTTPException(
                        status_code=404,
                        detail=f"Assistant with id {assistant_id} not found",
                    )
                tools = assistant.tools
            else:
                tools = self.db.query(Tool).all()
            logging_utility.info("Found %d tools", len(tools))
            tool_list = [self._tool_to_dict(tool) for tool in tools]
            if restructure:
                tool_list = self.restructure_tools({"tools": tool_list})
            return tool_list
        except Exception as e:
            logging_utility.error("Error listing tools: %s", str(e))
            raise HTTPException(
                status_code=500, detail="An error occurred while listing the tools"
            )

    def restructure_tools(self, assistant_tools):
        """Restructure the tools to handle dynamic function structures."""

        def parse_parameters(parameters):
            """Recursively parse parameters and handle different structures."""
            if isinstance(parameters, dict):
                parsed = {}
                for key, value in parameters.items():
                    if isinstance(value, dict):
                        parsed[key] = parse_parameters(value)
                    else:
                        parsed[key] = value
                return parsed
            return parameters

        restructured_tools = []
        for tool in assistant_tools["tools"]:
            function_info = tool["function"]
            if "function" in function_info:
                function_info = function_info["function"]
            restructured_tool = {
                "type": tool["type"],
                "name": function_info.get("name", "Unnamed tool"),
                "description": function_info.get(
                    "description", "No description provided"
                ),
                "parameters": parse_parameters(function_info.get("parameters", {})),
            }
            restructured_tools.append(restructured_tool)
        return restructured_tools

    def _tool_to_dict(self, tool: Tool) -> dict:
        return {
            "id": tool.id,
            "name": tool.name,
            "type": tool.type,
            "function": tool.function,
        }

    def _get_tool_or_404(self, tool_id: str) -> Tool:
        logging_utility.debug("Fetching tool with ID: %s", tool_id)
        db_tool = self.db.query(Tool).filter(Tool.id == tool_id).first()
        if not db_tool:
            logging_utility.warning("Tool not found with ID: %s", tool_id)
            raise HTTPException(status_code=404, detail="Tool not found")
        logging_utility.debug("Tool with ID %s found", tool_id)
        return db_tool
