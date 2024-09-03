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

    def create_tool(self, tool: ToolCreate) -> ToolRead:
        logging_utility.info("Creating new tool")
        try:
            tool_id = IdentifierService.generate_tool_id()
            db_tool = Tool(
                id=tool_id,
                type=tool.type,
                function=tool.function.dict() if tool.function else None
            )
            self.db.add(db_tool)
            self.db.commit()
            self.db.refresh(db_tool)
            logging_utility.info("Tool created successfully with id=%s", tool_id)
            return ToolRead.model_validate(db_tool)
        except IntegrityError as e:
            self.db.rollback()
            logging_utility.error(f"IntegrityError while creating tool: {str(e)}")
            raise HTTPException(status_code=400, detail="Invalid tool data or duplicate tool ID")
        except Exception as e:
            self.db.rollback()
            logging_utility.error("Error creating tool: %s", str(e))
            raise HTTPException(status_code=500, detail="An error occurred while creating the tool")

    def associate_tool_with_assistant(self, tool_id: str, assistant_id: str) -> None:
        logging_utility.info(f"Associating tool {tool_id} with assistant {assistant_id}")
        try:
            tool = self._get_tool_or_404(tool_id)
            assistant = self.db.query(Assistant).filter(Assistant.id == assistant_id).first()
            if not assistant:
                raise HTTPException(status_code=404, detail=f"Assistant with id {assistant_id} not found")
            assistant.tools.append(tool)
            self.db.commit()
            logging_utility.info(f"Tool {tool_id} associated with assistant {assistant_id}")
        except HTTPException:
            raise
        except Exception as e:
            self.db.rollback()
            logging_utility.error(f"Error associating tool with assistant: {str(e)}")
            raise HTTPException(status_code=500, detail="An error occurred while associating the tool with the assistant")

    def get_tool(self, tool_id: str) -> ToolRead:
        logging_utility.info("Retrieving tool with id=%s", tool_id)
        try:
            db_tool = self._get_tool_or_404(tool_id)
            return ToolRead.model_validate(db_tool)
        except HTTPException:
            raise
        except Exception as e:
            logging_utility.error("Error retrieving tool: %s", str(e))
            raise HTTPException(status_code=500, detail="An error occurred while retrieving the tool")

    def update_tool(self, tool_id: str, tool_update: ToolUpdate) -> ToolRead:
        logging_utility.info("Updating tool with id=%s", tool_id)
        try:
            db_tool = self._get_tool_or_404(tool_id)
            update_data = tool_update.model_dump(exclude_unset=True)
            for key, value in update_data.items():
                setattr(db_tool, key, value)
            self.db.commit()
            self.db.refresh(db_tool)
            logging_utility.info("Tool updated successfully")
            return ToolRead.model_validate(db_tool)
        except HTTPException:
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
        except HTTPException:
            raise
        except Exception as e:
            self.db.rollback()
            logging_utility.error("Error deleting tool: %s", str(e))
            raise HTTPException(status_code=500, detail="An error occurred while deleting the tool")

    def list_tools(self, assistant_id: str = None) -> List[ToolRead]:
        logging_utility.info("Listing tools")
        try:
            if assistant_id:
                assistant = self.db.query(Assistant).filter(Assistant.id == assistant_id).first()
                if not assistant:
                    raise HTTPException(status_code=404, detail=f"Assistant with id {assistant_id} not found")
                tools = assistant.tools
            else:
                tools = self.db.query(Tool).all()
            return [ToolRead.model_validate(tool) for tool in tools]
        except HTTPException:
            raise
        except Exception as e:
            logging_utility.error("Error listing tools: %s", str(e))
            raise HTTPException(status_code=500, detail="An error occurred while listing the tools")

    def _get_tool_or_404(self, tool_id: str) -> Tool:
        db_tool = self.db.query(Tool).filter(Tool.id == tool_id).first()
        if not db_tool:
            logging_utility.warning("Tool not found with id=%s", tool_id)
            raise HTTPException(status_code=404, detail="Tool not found")
        return db_tool