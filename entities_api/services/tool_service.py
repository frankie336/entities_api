import httpx
from pydantic import ValidationError
from sqlalchemy.orm import Session, joinedload
from sqlalchemy.exc import IntegrityError
from fastapi import HTTPException
from entities_api.schemas import ToolCreate, ToolUpdate, ToolRead
from models.models import Tool, Assistant
from entities_api.services.identifier_service import IdentifierService
from entities_api.services.logging_service import LoggingUtility
from typing import List, Optional

logging_utility = LoggingUtility()


class ToolService:
    def __init__(self, db: Session):
        self.db = db
        logging_utility.info("ToolService initialized with database session.")

    def create_tool(self, tool: ToolCreate) -> ToolRead:
        logging_utility.info("Starting create_tool with ToolCreate: %s", tool)
        try:
            tool_id = IdentifierService.generate_tool_id()
            logging_utility.debug("Generated tool ID: %s", tool_id)

            db_tool = Tool(
                id=tool_id,
                type=tool.type,
                function=tool.function.dict() if tool.function else None
            )
            self.db.add(db_tool)
            self.db.commit()
            self.db.refresh(db_tool)

            logging_utility.info("Tool created successfully with ID: %s", tool_id)
            return ToolRead.model_validate(db_tool)
        except IntegrityError as e:
            self.db.rollback()
            logging_utility.error("IntegrityError during tool creation: %s", str(e))
            raise HTTPException(status_code=400, detail="Invalid tool data or duplicate tool ID")
        except Exception as e:
            self.db.rollback()
            logging_utility.error("Unexpected error during tool creation: %s", str(e))
            raise HTTPException(status_code=500, detail="An error occurred while creating the tool")

    def associate_tool_with_assistant(self, tool_id: str, assistant_id: str) -> None:
        logging_utility.info("Associating tool with ID %s to assistant with ID %s", tool_id, assistant_id)
        try:
            tool = self._get_tool_or_404(tool_id)
            assistant = self.db.query(Assistant).filter(Assistant.id == assistant_id).first()

            if not assistant:
                logging_utility.warning("Assistant with ID %s not found.", assistant_id)
                raise HTTPException(status_code=404, detail=f"Assistant with id {assistant_id} not found")

            assistant.tools.append(tool)
            self.db.commit()

            logging_utility.info("Successfully associated tool ID %s with assistant ID %s", tool_id, assistant_id)
        except HTTPException as e:
            logging_utility.error("HTTPException: %s", str(e))
            raise
        except Exception as e:
            self.db.rollback()
            logging_utility.error("Error associating tool with assistant: %s", str(e))
            raise HTTPException(status_code=500, detail="An error occurred while associating the tool with the assistant")

    def get_tool(self, tool_id: str) -> ToolRead:
        logging_utility.info("Retrieving tool with ID: %s", tool_id)
        try:
            db_tool = self._get_tool_or_404(tool_id)
            logging_utility.info("Tool retrieved successfully: %s", db_tool)
            return ToolRead.model_validate(db_tool)
        except HTTPException as e:
            logging_utility.error("HTTPException: %s", str(e))
            raise
        except Exception as e:
            logging_utility.error("Unexpected error retrieving tool: %s", str(e))
            raise HTTPException(status_code=500, detail="An error occurred while retrieving the tool")

    def update_tool(self, tool_id: str, tool_update: ToolUpdate) -> ToolRead:
        logging_utility.info("Updating tool with ID: %s, ToolUpdate: %s", tool_id, tool_update)
        try:
            db_tool = self._get_tool_or_404(tool_id)
            update_data = tool_update.model_dump(exclude_unset=True)
            logging_utility.debug("Updating tool with data: %s", update_data)

            for key, value in update_data.items():
                setattr(db_tool, key, value)

            self.db.commit()
            self.db.refresh(db_tool)

            logging_utility.info("Tool with ID %s updated successfully", tool_id)
            return ToolRead.model_validate(db_tool)
        except HTTPException as e:
            logging_utility.error("HTTPException: %s", str(e))
            raise
        except Exception as e:
            self.db.rollback()
            logging_utility.error("Error updating tool: %s", str(e))
            raise HTTPException(status_code=500, detail="An error occurred while updating the tool")

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
            raise HTTPException(status_code=500, detail="An error occurred while deleting the tool")

    # TODO: pydentic validation - not the end of the world!
    def list_tools(self, assistant_id: Optional[str] = None) -> List[dict]:
        logging_utility.info("Listing tools for assistant ID: %s", assistant_id)
        try:
            if assistant_id:
                assistant = self.db.query(Assistant).options(joinedload(Assistant.tools)).filter(Assistant.id == assistant_id).first()
                logging_utility.debug("Assistant found: %s", assistant)

                if not assistant:
                    logging_utility.warning("Assistant with ID %s not found", assistant_id)
                    raise HTTPException(status_code=404, detail=f"Assistant with id {assistant_id} not found")

                tools = assistant.tools
                logging_utility.debug("Tools found: %s", tools)
            else:
                tools = self.db.query(Tool).all()
                logging_utility.debug("All tools: %s", tools)

            logging_utility.info("Found %d tools", len(tools))
            # Convert ORM objects to dictionaries manually
            return [self._tool_to_dict(tool) for tool in tools]
        except Exception as e:
            logging_utility.error("Error listing tools: %s", str(e))
            raise HTTPException(status_code=500, detail="An error occurred while listing the tools")

    def _tool_to_dict(self, tool: Tool) -> dict:
        # Manually convert the ORM Tool object to a dictionary
        return {
            "id": tool.id,
            "type": tool.type,
            "function": tool.function  # Assuming function is stored as a dictionary or JSON-like structure
        }

    def _get_tool_or_404(self, tool_id: str) -> Tool:
            logging_utility.debug("Fetching tool with ID: %s", tool_id)
            db_tool = self.db.query(Tool).filter(Tool.id == tool_id).first()
            if not db_tool:
                logging_utility.warning("Tool not found with ID: %s", tool_id)
                raise HTTPException(status_code=404, detail="Tool not found")
            logging_utility.debug("Tool with ID %s found", tool_id)
            return db_tool
