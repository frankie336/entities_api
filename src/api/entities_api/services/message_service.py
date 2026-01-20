import json
import time
from typing import Any, Dict, List, Optional

from fastapi import HTTPException
from projectdavid_common import UtilsInterface, ValidationInterface

from src.api.entities_api.db.database import SessionLocal
# FIX: Import Action/Tool for the JOIN
from src.api.entities_api.models.models import Action, Message, Thread, Tool
from src.api.entities_api.services.logging_service import LoggingUtility

validator = ValidationInterface()
logging_utility = LoggingUtility()


class MessageService:

    def __init__(self):
        self.message_chunks: Dict[str, List[str]] = {}
        logging_utility.info(f"Initialized MessageService. Source: {__file__}")

    def create_message(self, message: validator.MessageCreate) -> validator.MessageRead:
        logging_utility.info(
            f"Creating message for thread_id={message.thread_id}, role={message.role}. Source: {__file__}"
        )
        with SessionLocal() as db:
            db_thread = db.query(Thread).filter(Thread.id == message.thread_id).first()
            if not db_thread:
                raise HTTPException(status_code=404, detail="Thread not found")

            # Safe access
            t_id = getattr(message, "tool_id", None)
            tc_id = getattr(message, "tool_call_id", None)

            db_message = Message(
                id=UtilsInterface.IdentifierService.generate_message_id(),
                assistant_id=message.assistant_id,
                attachments=[],
                completed_at=None,
                content=message.content,
                created_at=int(time.time()),
                incomplete_at=None,
                incomplete_details=None,
                meta_data=json.dumps(message.meta_data),
                object="message",
                role=message.role,
                run_id=None,
                status=None,
                thread_id=message.thread_id,
                sender_id=message.sender_id,
                tool_id=t_id,
                tool_call_id=tc_id,
            )
            try:
                db.add(db_message)
                db.commit()
                db.refresh(db_message)
            except Exception as e:
                db.rollback()
                logging_utility.error(f"Error saving message: {e}")
                raise HTTPException(status_code=500, detail="Failed to create message")

            return ValidationInterface.MessageRead(
                id=db_message.id,
                assistant_id=db_message.assistant_id,
                attachments=db_message.attachments,
                completed_at=db_message.completed_at,
                content=db_message.content,
                created_at=db_message.created_at,
                incomplete_at=db_message.incomplete_at,
                incomplete_details=db_message.incomplete_details,
                meta_data=json.loads(db_message.meta_data or "{}"),
                object=db_message.object,
                role=db_message.role,
                run_id=db_message.run_id,
                status=db_message.status,
                thread_id=db_message.thread_id,
                sender_id=db_message.sender_id,
                tool_id=db_message.tool_id,
                tool_call_id=db_message.tool_call_id,
            )

    def retrieve_message(self, message_id: str) -> ValidationInterface.MessageRead:
        logging_utility.info(
            f"Retrieving message with id={message_id}. Source: {__file__}"
        )
        with SessionLocal() as db:
            db_message = db.query(Message).filter(Message.id == message_id).first()
            if not db_message:
                raise HTTPException(status_code=404, detail="Message not found")

            return ValidationInterface.MessageRead(
                id=db_message.id,
                assistant_id=db_message.assistant_id,
                attachments=db_message.attachments,
                completed_at=db_message.completed_at,
                content=db_message.content,
                created_at=db_message.created_at,
                incomplete_at=db_message.incomplete_at,
                incomplete_details=db_message.incomplete_details,
                meta_data=json.loads(db_message.meta_data or "{}"),
                object=db_message.object,
                role=db_message.role,
                run_id=db_message.run_id,
                status=db_message.status,
                thread_id=db_message.thread_id,
                sender_id=db_message.sender_id,
                tool_id=db_message.tool_id,
                tool_call_id=db_message.tool_call_id,
            )

    def list_messages(
        self,
        thread_id: str,
        limit: int = 20,
        order: str = "asc",
    ) -> validator.MessagesList:
        logging_utility.info(
            f"Listing messages for thread_id={thread_id}, limit={limit}, order={order}."
        )
        with SessionLocal() as db:
            db_thread = db.query(Thread).filter(Thread.id == thread_id).first()
            if not db_thread:
                raise HTTPException(status_code=404, detail="Thread not found")

            query = db.query(Message).filter(Message.thread_id == thread_id)
            query = (
                query.order_by(Message.created_at.asc())
                if order == "asc"
                else query.order_by(Message.created_at.desc())
            )
            db_messages = query.limit(limit).all()

            messages: List[validator.MessageRead] = []
            for db_msg in db_messages:
                if isinstance(db_msg.meta_data, str):
                    try:
                        db_msg.meta_data = json.loads(db_msg.meta_data)
                    except (TypeError, ValueError):
                        db_msg.meta_data = {}
                messages.append(validator.MessageRead.model_validate(db_msg))

            return validator.MessagesList(
                data=messages,
                first_id=messages[0].id if messages else None,
                last_id=messages[-1].id if messages else None,
                has_more=len(db_messages) >= limit,
            )

    def save_assistant_message_chunk(
        self,
        thread_id: str,
        content: str,
        role: str,
        assistant_id: str,
        sender_id: str,
        is_last_chunk: bool = False,
    ) -> Optional[ValidationInterface.MessageRead]:
        if thread_id not in self.message_chunks:
            self.message_chunks[thread_id] = []
        self.message_chunks[thread_id].append(content)

        if not is_last_chunk:
            return None

        complete_message = "".join(self.message_chunks.pop(thread_id, []))

        with SessionLocal() as db:
            db_message = Message(
                id=UtilsInterface.IdentifierService.generate_message_id(),
                assistant_id=assistant_id,
                attachments=[],
                completed_at=int(time.time()),
                content=complete_message,
                created_at=int(time.time()),
                meta_data=json.dumps({}),
                object="message",
                role=role,
                thread_id=thread_id,
                sender_id=sender_id,
            )
            try:
                db.add(db_message)
                db.commit()
                db.refresh(db_message)
            except Exception as e:
                db.rollback()
                raise HTTPException(status_code=500, detail="Failed to save message")

            if isinstance(db_message.meta_data, str):
                try:
                    db_message.meta_data = json.loads(db_message.meta_data)
                except (json.JSONDecodeError, TypeError):
                    db_message.meta_data = {}

            return ValidationInterface.MessageRead.model_validate(db_message)

    # ------------------------------------------------------------------
    # 🔍 DEFINITIVE FIX: JOIN Message -> Action -> Tool to get 'name'
    # ------------------------------------------------------------------
    def list_messages_for_thread(self, thread_id: str) -> List[Dict[str, Any]]:
        """
        List messages for a thread formatted for the Context Window.
        Ensures 'role: tool' messages have the 'name' field by joining
        via the Action table.
        """
        with SessionLocal() as db:
            db_thread = db.query(Thread).filter(Thread.id == thread_id).first()
            if not db_thread:
                raise HTTPException(status_code=404, detail="Thread not found")

            # --- THE FIX: JOIN CHAIN ---
            # 1. Message.tool_id usually holds the Action ID (act_...)
            # 2. Action.tool_id holds the Tool ID
            # 3. Tool.name holds the string name (e.g. 'get_flight_times')
            results = (
                db.query(Message, Tool.name)
                .outerjoin(Action, Message.tool_id == Action.id)
                .outerjoin(Tool, Action.tool_id == Tool.id)
                .filter(Message.thread_id == thread_id)
                .order_by(Message.created_at.asc())
                .all()
            )

            formatted_messages = []

            for db_message, tool_name in results:
                # --- 1. TOOL MESSAGE ---
                if db_message.role == "tool":
                    # Use the tool_call_id (Dialogue Binding ID)
                    t_id = db_message.tool_call_id or db_message.tool_id

                    msg_dict = {
                        "role": "tool",
                        "tool_call_id": t_id,
                        "content": db_message.content,
                    }

                    # INJECT NAME (Required for gpt-oss / Llama)
                    if tool_name:
                        msg_dict["name"] = tool_name
                    # If not found via Action Join, check if it's a direct Tool ID
                    elif not tool_name and db_message.tool_id:
                        # Fallback: Maybe tool_id was the Tool ID directly?
                        direct_tool = (
                            db.query(Tool).filter(Tool.id == db_message.tool_id).first()
                        )
                        if direct_tool:
                            msg_dict["name"] = direct_tool.name

                    formatted_messages.append(msg_dict)

                # --- 2. ASSISTANT MESSAGE ---
                elif db_message.role == "assistant":
                    try:
                        content_json = json.loads(db_message.content)
                        if (
                            isinstance(content_json, list)
                            and content_json
                            and isinstance(content_json[0], dict)
                            and "type" in content_json[0]
                            and content_json[0]["type"] == "function"
                        ):
                            # Tool Call Message
                            formatted_messages.append(
                                {
                                    "role": "assistant",
                                    "tool_calls": content_json,
                                    # -------------------------------------------------
                                    # FIX: Changed None to "" (Empty String)
                                    # Strict OSS models crash on null content in history
                                    # -------------------------------------------------
                                    "content": "",
                                }
                            )
                        else:
                            # Standard text (even if it was a JSON string that wasn't a tool call)
                            formatted_messages.append(
                                {"role": db_message.role, "content": db_message.content}
                            )
                    except (json.JSONDecodeError, TypeError):
                        # Not JSON, so it's just regular text content
                        formatted_messages.append(
                            {"role": db_message.role, "content": db_message.content}
                        )

                # --- 3. OTHER MESSAGES (System, User) ---
                else:
                    formatted_messages.append(
                        {"role": db_message.role, "content": db_message.content}
                    )

            return formatted_messages
    def submit_tool_output(
        self, message: validator.MessageCreate
    ) -> ValidationInterface.MessageRead:
        with SessionLocal() as db:
            db_thread = db.query(Thread).filter(Thread.id == message.thread_id).first()
            if not db_thread:
                raise HTTPException(status_code=404, detail="Thread not found")

            t_id = getattr(message, "tool_id", None)
            tc_id = getattr(message, "tool_call_id", None)

            db_message = Message(
                id=UtilsInterface.IdentifierService.generate_message_id(),
                assistant_id=message.assistant_id,
                content=message.content,
                created_at=int(time.time()),
                meta_data=json.dumps(message.meta_data or {}),
                object="message",
                role="tool",
                thread_id=message.thread_id,
                tool_id=t_id,
                tool_call_id=tc_id,
            )
            try:
                db.add(db_message)
                db.commit()
                db.refresh(db_message)
            except Exception as e:
                db.rollback()
                raise HTTPException(status_code=500, detail="Failed to create message")

            if isinstance(db_message.meta_data, str):
                try:
                    db_message.meta_data = json.loads(db_message.meta_data)
                except (json.JSONDecodeError, TypeError):
                    db_message.meta_data = {}

            return ValidationInterface.MessageRead.model_validate(db_message)

    def delete_message(self, message_id: str) -> validator.MessageDeleted:
        with SessionLocal() as db:
            db_msg = db.query(Message).filter(Message.id == message_id).first()
            if not db_msg:
                raise HTTPException(status_code=404, detail="Message not found")
            db.delete(db_msg)
            db.commit()
            return validator.MessageDeleted(id=message_id)
