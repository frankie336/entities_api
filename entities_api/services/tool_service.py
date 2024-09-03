from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from fastapi import HTTPException
from entities_api.schemas import ToolCreate, ToolUpdate, ToolRead
from models.models import Tool, Assistant
from entities_api.services.identifier_service import IdentifierService
from entities_api.services.logging_service import LoggingUtility
from typing import List

logging_utility = LoggingUtility()

class ToolService:
    def __init__(self, db: Session):
        self.db = db
        logging_utility.info("ToolService initialized")

    def create_tool(self, tool: ToolCreate, assistant_id: str) -> ToolRead:
        logging_utility.info("Creating new tool for assistant_id=%s", assistant_id)
        try:
            # Check if the assistant exists
            assistant = self.db.query(Assistant).filter(Assistant.id == assistant_id).first()
            if not assistant:
                logging_utility.error(f"Assistant with id {assistant_id} not found")
                raise HTTPException(status_code=404, detail=f"Assistant with id {assistant_id} not found")

            tool_id = IdentifierService.generate_tool_id()
            db_tool = Tool(
                id=tool_id,
                type=tool.type,
                function=tool.function.dict() if tool.function else None,
                assistant_id=assistant_id
            )
            self.db.add(db_tool)
            self.db.commit()
            self.db.refresh(db_tool)
            logging_utility.info("Tool created successfully with id=%s", tool_id)
            return ToolRead.from_orm(db_tool)
        except IntegrityError as e:
            self.db.rollback()
            logging_utility.error(f"IntegrityError while creating tool: {str(e)}")
            raise HTTPException(status_code=400, detail="Invalid assistant ID or duplicate tool ID")
        except Exception as e:
            self.db.rollback()
            logging_utility.error("Error creating tool: %s", str(e))
            raise HTTPException(status_code=500, detail="An error occurred while creating the tool")

    def get_tool(self, tool_id: str) -> ToolRead:
        logging_utility.info("Retrieving tool with id=%s", tool_id)
        try:
            db_tool = self._get_tool_or_404(tool_id)
            return ToolRead.from_orm(db_tool)
        except HTTPException as e:
            logging_utility.warning("Tool not found: %s", str(e))
            raise
        except Exception as e:
            logging_utility.error("Error retrieving tool: %s", str(e))
            raise HTTPException(status_code=500, detail="An error occurred while retrieving the tool")

    def update_tool(self, tool_id: str, tool_update: ToolUpdate) -> ToolRead:
        logging_utility.info("Updating tool with id=%s", tool_id)
        try:
            db_tool = self._get_tool_or_404(tool_id)
            update_data = tool_update.dict(exclude_unset=True)
            for key, value in update_data.items():
                setattr(db_tool, key, value)
            self.db.commit()
            self.db.refresh(db_tool)
            logging_utility.info("Tool updated successfully")
            return ToolRead.from_orm(db_tool)
        except HTTPException as e:
            logging_utility.warning("Tool not found for update: %s", str(e))
            raise
        except Exception as e:
            self.db.rollback()
            logging_utility.error("Error updating tool: %s", str(e))
            raise HTTPException(status_code=500, detail="An error occurred while updating the tool")

    def delete_tool(self, tool_id: str) -> None:
        logging_utility.info("Deleting tool with id=%s", tool_id)
        try:
            db_tool = self._get_tool_or_404(tool_id)
            self.db.delete(db_tool)
            self.db.commit()
            logging_utility.info("Tool deleted successfully")
        except HTTPException as e:
            logging_utility.warning("Tool not found for deletion: %s", str(e))
            raise
        except Exception as e:
            self.db.rollback()
            logging_utility.error("Error deleting tool: %s", str(e))
            raise HTTPException(status_code=500, detail="An error occurred while deleting the tool")

    def list_tools(self, assistant_id: str) -> List[ToolRead]:
        logging_utility.info("Listing tools for assistant_id=%s", assistant_id)
        try:
            tools = self.db.query(Tool).filter(Tool.assistant_id == assistant_id).all()
            return [ToolRead.from_orm(tool) for tool in tools]
        except Exception as e:
            logging_utility.error("Error listing tools: %s", str(e))
            raise HTTPException(status_code=500, detail="An error occurred while listing the tools")

    def _get_tool_or_404(self, tool_id: str) -> Tool:
        db_tool = self.db.query(Tool).filter(Tool.id == tool_id).first()
        if not db_tool:
            logging_utility.warning("Tool not found with id=%s", tool_id)
            raise HTTPException(status_code=404, detail="Tool not found")
        return db_tool