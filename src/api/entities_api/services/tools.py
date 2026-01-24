# src/api/entities_api/services/tools.py
from typing import List, Optional

from fastapi import HTTPException
from projectdavid_common import UtilsInterface, ValidationInterface
from projectdavid_common.constants.tools import TOOLS_ID_MAP
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from entities_api.utils.cache_utils import get_sync_invalidator

# --- FIX: Step 1 ---
# Import the SessionLocal factory.
from src.api.entities_api.db.database import SessionLocal
from src.api.entities_api.models.models import Assistant, Tool
from src.api.entities_api.services.logging_service import LoggingUtility

validator = ValidationInterface()
logging_utility = LoggingUtility()


class ToolService:

    # --- FIX: Step 2 ---
    # The constructor no longer accepts or stores a database session.
    def __init__(self):
        logging_utility.info("ToolService initialized.")

    @staticmethod
    def _invalidate_assistants_using_tool(db: Session, tool_id: str):
        """
        Finds all assistants linked to this tool and invalidates their cache.
        Note: Removed 'self' as it is no longer needed.
        """
        try:
            # Find assistants that have this tool in their 'tools' relationship
            assistants = (
                db.query(Assistant).filter(Assistant.tools.any(id=tool_id)).all()
            )

            if not assistants:
                return

            # This helper seems to handle its own instantiation
            cache = get_sync_invalidator()
            for asst in assistants:
                cache.invalidate_sync(asst.id)
                logging_utility.info(
                    f"Invalidated assistant {asst.id} due to tool update"
                )

        except Exception as e:
            logging_utility.error(f"Error during bulk cache invalidation: {e}")

    def create_tool(
        self, tool: validator.ToolCreate, set_id: Optional[str] = None
    ) -> validator.ToolRead:
        """
        Create a tool.
        """
        logging_utility.info("Starting create_tool %s (requested id=%s)", tool, set_id)
        # --- FIX: Step 4 ---
        # Each method now creates and manages its own session.
        with SessionLocal() as db:
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
            elif set_id:
                if set_id in TOOLS_ID_MAP.values():
                    raise HTTPException(
                        status_code=400,
                        detail="set_id collides with a reserved tool id",
                    )
                tool_id = set_id
            else:
                tool_id = UtilsInterface.IdentifierService.generate_tool_id()

            try:
                db_tool = Tool(
                    id=tool_id,
                    name=tool.name,
                    type=tool.type,
                    function=tool.function.dict() if tool.function else None,
                )
                db.add(db_tool)
                db.commit()
                db.refresh(db_tool)
                logging_utility.info("Tool created successfully with ID: %s", tool_id)
                return validator.ToolRead.model_validate(db_tool)
            except IntegrityError as e:
                db.rollback()
                logging_utility.error("IntegrityError during tool creation: %s", str(e))
                raise HTTPException(status_code=400, detail="Duplicate tool id or name")
            except Exception as e:
                db.rollback()
                logging_utility.error(
                    "Unexpected error during tool creation: %s", str(e)
                )
                raise HTTPException(
                    status_code=500, detail="An error occurred while creating the tool"
                )

    def associate_tool_with_assistant(self, tool_id: str, assistant_id: str) -> None:
        logging_utility.info(
            "Associating tool with ID %s to assistant with ID %s", tool_id, assistant_id
        )
        with SessionLocal() as db:
            try:
                tool = self._get_tool_or_404(tool_id, db)
                assistant = (
                    db.query(Assistant).filter(Assistant.id == assistant_id).first()
                )
                if not assistant:
                    raise HTTPException(
                        status_code=404,
                        detail=f"Assistant with id {assistant_id} not found",
                    )
                assistant.tools.append(tool)
                db.commit()

                # --- NEW: INVALIDATION ---
                try:
                    get_sync_invalidator().invalidate_sync(assistant_id)
                except Exception as e:
                    logging_utility.error(f"Cache invalidation failed: {e}")

                logging_utility.info(
                    "Successfully associated tool ID %s with assistant ID %s",
                    tool_id,
                    assistant_id,
                )
            except HTTPException as e:
                raise
            except Exception as e:
                db.rollback()
                logging_utility.error(
                    "Error associating tool with assistant: %s", str(e)
                )
                raise HTTPException(
                    status_code=500, detail="An error occurred while creating the tool"
                )

    def disassociate_tool_from_assistant(self, tool_id: str, assistant_id: str) -> None:
        logging_utility.info(
            "Disassociating tool with ID %s from assistant with ID %s",
            tool_id,
            assistant_id,
        )
        with SessionLocal() as db:
            try:
                tool = self._get_tool_or_404(tool_id, db)
                assistant = (
                    db.query(Assistant).filter(Assistant.id == assistant_id).first()
                )
                if not assistant:
                    raise HTTPException(
                        status_code=404,
                        detail=f"Assistant with id {assistant_id} not found",
                    )
                if tool in assistant.tools:
                    assistant.tools.remove(tool)
                    db.commit()

                    # --- NEW: INVALIDATION ---
                    try:
                        get_sync_invalidator().invalidate_sync(assistant_id)
                    except Exception as e:
                        logging_utility.error(f"Cache invalidation failed: {e}")

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
                raise
            except Exception as e:
                db.rollback()
                logging_utility.error(
                    "Error disassociating tool from assistant: %s", str(e)
                )
                raise HTTPException(
                    status_code=500,
                    detail="An error occurred while disassociating the tool from the assistant",
                )

    def get_tool(self, tool_id: str) -> validator.ToolRead:
        logging_utility.info("Retrieving tool with ID: %s", tool_id)
        with SessionLocal() as db:
            try:
                db_tool = self._get_tool_or_404(tool_id, db)
                return validator.ToolRead.model_validate(db_tool)
            except HTTPException as e:
                raise
            except Exception as e:
                logging_utility.error("Unexpected error retrieving tool: %s", str(e))
                raise HTTPException(
                    status_code=500,
                    detail="An error occurred while retrieving the tool",
                )

    def get_tool_by_name(self, name: str) -> validator.ToolRead:
        """Retrieve a tool by its name."""
        logging_utility.info("Retrieving tool by name: %s", name)
        with SessionLocal() as db:
            try:
                db_tool = db.query(Tool).filter(Tool.name == name).first()
                if not db_tool:
                    raise HTTPException(
                        status_code=404, detail=f"Tool with name {name} not found"
                    )
                return validator.ToolRead.model_validate(db_tool)
            except Exception as e:
                logging_utility.error("Unexpected error retrieving tool: %s", str(e))
                raise HTTPException(
                    status_code=500,
                    detail="An error occurred while retrieving the tool",
                )

    def update_tool(
        self, tool_id: str, tool_update: validator.ToolUpdate
    ) -> validator.ToolRead:
        logging_utility.info(
            "Updating tool with ID: %s, ToolUpdate: %s", tool_id, tool_update
        )

        with SessionLocal() as db:
            try:
                db_tool = self._get_tool_or_404(tool_id, db)
                update_data = tool_update.model_dump(exclude_unset=True)
                for key, value in update_data.items():
                    setattr(db_tool, key, value)
                db.commit()
                db.refresh(db_tool)

                # --- NEW: INVALIDATION ---
                # Since the tool definition (parameters/description) changed,
                # ALL assistants using this tool are now serving stale configs.
                self._invalidate_assistants_using_tool(db, tool_id)

                return validator.ToolRead.model_validate(db_tool)
            except HTTPException as e:
                raise
            except Exception as e:
                db.rollback()
                logging_utility.error("Error updating tool: %s", str(e))
                raise HTTPException(
                    status_code=500, detail="An error occurred while updating the tool"
                )

    def delete_tool(self, tool_id: str) -> None:
        logging_utility.info("Deleting tool with ID: %s", tool_id)
        with SessionLocal() as db:
            try:
                # 1. Identify linked assistants BEFORE deleting the tool
                # This ensures we have the IDs needed for cache invalidation
                assistants_to_invalidate = (
                    db.query(Assistant).filter(Assistant.tools.any(id=tool_id)).all()
                )

                # 2. Perform the deletion
                db_tool = self._get_tool_or_404(tool_id, db)
                db.delete(db_tool)
                db.commit()
                logging_utility.info(
                    "Tool with ID %s deleted successfully from DB", tool_id
                )

                # 3. Invalidate the cache for affected assistants
                if assistants_to_invalidate:
                    try:
                        cache = get_sync_invalidator()
                        for asst in assistants_to_invalidate:
                            cache.invalidate_sync(asst.id)
                            logging_utility.info(
                                f"Invalidated assistant cache for: {asst.id}"
                            )
                    except Exception as e:
                        # We log but don't raise here so the DB deletion remains "successful"
                        logging_utility.error(f"Error during cache invalidation: {e}")

            except HTTPException:
                # Re-raise known HTTP errors (like 404 from _get_tool_or_404)
                raise
            except Exception as e:
                db.rollback()
                logging_utility.error("Error deleting tool: %s", str(e))
                raise HTTPException(
                    status_code=500, detail="An error occurred while deleting the tool"
                )

    def list_tools(
        self, assistant_id: Optional[str] = None, restructure: bool = False
    ) -> List[dict]:
        logging_utility.info("Listing tools for assistant ID: %s", assistant_id)
        with SessionLocal() as db:
            try:
                if assistant_id:
                    assistant = (
                        db.query(Assistant)
                        .options(joinedload(Assistant.tools))
                        .filter(Assistant.id == assistant_id)
                        .first()
                    )
                    if not assistant:
                        raise HTTPException(
                            status_code=404,
                            detail=f"Assistant with id {assistant_id} not found",
                        )
                    tools = assistant.tools
                else:
                    tools = db.query(Tool).all()
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

        # This method does not interact with the DB, so no changes are needed.
        def parse_parameters(parameters):
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
        # This method does not interact with the DB, so no changes are needed.
        return {
            "id": tool.id,
            "name": tool.name,
            "type": tool.type,
            "function": tool.function,
        }

    # --- FIX: Step 3 ---
    # Helper methods that need a session must now accept it as a parameter.
    def _get_tool_or_404(self, tool_id: str, db: Session) -> Tool:
        logging_utility.debug("Fetching tool with ID: %s", tool_id)
        db_tool = db.query(Tool).filter(Tool.id == tool_id).first()
        if not db_tool:
            logging_utility.warning("Tool not found with ID: %s", tool_id)
            raise HTTPException(status_code=404, detail="Tool not found")
        logging_utility.debug("Tool with ID %s found", tool_id)
        return db_tool
