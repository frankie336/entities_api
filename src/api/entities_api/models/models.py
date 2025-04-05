import logging
import time
from datetime import datetime
from enum import Enum as PyEnum
from entities_common import ValidationInterface

from sqlalchemy import (
    Column, String, Integer, Boolean, JSON, DateTime, ForeignKey, Table, BigInteger, Index, Enum as SAEnum
)
from sqlalchemy import Text
from sqlalchemy.orm import relationship, declarative_base, joinedload

# Configure logging
logger = logging.getLogger(__name__)

Base = declarative_base()

validation = ValidationInterface


# Association tables
thread_participants = Table(
    'thread_participants', Base.metadata,
    Column('thread_id', String(64), ForeignKey('threads.id'), primary_key=True),
    Column('user_id', String(64), ForeignKey('users.id'), primary_key=True)
)

assistant_tools = Table(
    'assistant_tools', Base.metadata,
    Column('assistant_id', String(64), ForeignKey('assistants.id')),
    Column('tool_id', String(64), ForeignKey('tools.id'))
)

user_assistants = Table(
    'user_assistants', Base.metadata,
    Column('user_id', String(64), ForeignKey('users.id'), primary_key=True),
    Column('assistant_id', String(64), ForeignKey('assistants.id'), primary_key=True)
)

vector_store_assistants = Table(
    'vector_store_assistants', Base.metadata,
    Column('vector_store_id', String(64), ForeignKey('vector_stores.id'), primary_key=True),
    Column('assistant_id', String(64), ForeignKey('assistants.id'), primary_key=True)
)

thread_vector_stores = Table(
    'thread_vector_stores', Base.metadata,
    Column('thread_id', String(64), ForeignKey('threads.id'), primary_key=True),
    Column('vector_store_id', String(64), ForeignKey('vector_stores.id'), primary_key=True)
)


class StatusEnum(PyEnum):
    deleted = "deleted"
    active = "active"               # Added this member
    queued = "queued"
    in_progress = "in_progress"
    pending_action = "action_required"
    completed = "completed"
    failed = "failed"
    cancelling = "cancelling"
    cancelled = "cancelled"
    pending = "pending"
    processing = "processing"
    expired = "expired"
    retrying = "retrying"

# -----------------------------------------------------------------------------
# Models
# -----------------------------------------------------------------------------
class User(Base):
    __tablename__ = "users"

    id = Column(String(64), primary_key=True, index=True)
    name = Column(String(128), index=True)
    # Reintroduce the threads relationship
    threads = relationship(
        'Thread',
        secondary=thread_participants,
        back_populates='participants'
    )
    assistants = relationship(
        'Assistant',
        secondary=user_assistants,
        back_populates='users'
    )
    sandboxes = relationship(
        'Sandbox',
        back_populates='user',
        cascade="all, delete-orphan"
    )
    vector_stores = relationship(
        "VectorStore",
        back_populates="user",
        lazy="select"
    )
    files = relationship(
        "File",
        back_populates="user",
        cascade="all, delete-orphan"
    )


class Thread(Base):
    __tablename__ = "threads"

    id = Column(String(64), primary_key=True, index=True)
    created_at = Column(Integer, nullable=False)
    meta_data = Column(JSON, nullable=False, default={})
    object = Column(String(64), nullable=False)
    tool_resources = Column(JSON, nullable=False, default={})
    # Reintroduce the participants relationship
    participants = relationship(
        'User',
        secondary=thread_participants,
        back_populates='threads'
    )
    vector_stores = relationship(
        "VectorStore",
        secondary=thread_vector_stores,
        back_populates="threads",
        lazy="select"
    )


class Message(Base):
    __tablename__ = "messages"

    id = Column(String(64), primary_key=True, index=True)
    assistant_id = Column(String(64), index=True)
    attachments = Column(JSON, default=[])
    completed_at = Column(Integer, nullable=True)
    content = Column(Text(length=4294967295), nullable=False)  # Specify LONGTEXT size explicitly
    created_at = Column(Integer, nullable=False)
    incomplete_at = Column(Integer, nullable=True)
    incomplete_details = Column(JSON, nullable=True)
    meta_data = Column(JSON, nullable=False, default={})
    object = Column(String(64), nullable=False)
    role = Column(String(32), nullable=False)
    run_id = Column(String(64), nullable=True)
    tool_id = Column(String(64), nullable=True)
    status = Column(String(32), nullable=True)
    thread_id = Column(String(64), nullable=False)
    sender_id = Column(String(64), nullable=True)


class Run(Base):
    __tablename__ = "runs"

    id = Column(String(64), primary_key=True)
    assistant_id = Column(String(64), nullable=False)
    cancelled_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(Integer, default=lambda: int(time.time()))
    expires_at = Column(Integer, nullable=True)
    failed_at = Column(DateTime, nullable=True)
    incomplete_details = Column(String(256), nullable=True)
    instructions = Column(String(1024), nullable=True)
    last_error = Column(String(256), nullable=True)
    max_completion_tokens = Column(Integer, nullable=True)
    max_prompt_tokens = Column(Integer, nullable=True)
    meta_data = Column(JSON, nullable=True)
    model = Column(String(64), nullable=True)
    object = Column(String(64), nullable=False)
    parallel_tool_calls = Column(Boolean, default=False)
    required_action = Column(String(256), nullable=True)
    response_format = Column(String(64), nullable=True)
    started_at = Column(DateTime, nullable=True)
    status = Column(SAEnum(validation.StatusEnum), nullable=False)
    thread_id = Column(String(64), nullable=False)
    tool_choice = Column(String(64), nullable=True)
    tools = Column(JSON, nullable=True)
    truncation_strategy = Column(JSON, nullable=True)
    usage = Column(JSON, nullable=True)
    temperature = Column(Integer, nullable=True)
    top_p = Column(Integer, nullable=True)
    tool_resources = Column(JSON, nullable=True)

    actions = relationship("Action", back_populates="run")


class Assistant(Base):
    __tablename__ = "assistants"

    id = Column(String(64), primary_key=True, index=True)
    object = Column(String(64), nullable=False)
    created_at = Column(Integer, nullable=False)
    name = Column(String(128), nullable=False)
    description = Column(String(256), nullable=True)
    model = Column(String(64), nullable=True)
    instructions = Column(Text, nullable=True)
    tool_configs = Column(JSON, nullable=True)
    meta_data = Column(JSON, nullable=True)
    top_p = Column(Integer, nullable=True)
    temperature = Column(Integer, nullable=True)
    response_format = Column(String(64), nullable=True)

    tools = relationship(
        "Tool",
        secondary=assistant_tools,
        back_populates="assistants",
        lazy="joined"
    )
    users = relationship(
        "User",
        secondary=user_assistants,
        back_populates="assistants",
        lazy="select"
    )
    vector_stores = relationship(
        "VectorStore",
        secondary="vector_store_assistants",
        back_populates="assistants",
        lazy="select",
        passive_deletes=True
    )


class Tool(Base):
    __tablename__ = "tools"

    id = Column(String(64), primary_key=True, index=True)
    name = Column(String(128), nullable=False)
    type = Column(String(64), nullable=False)
    function = Column(JSON, nullable=True)

    assistants = relationship(
        "Assistant",
        secondary=assistant_tools,
        back_populates="tools"
    )
    actions = relationship("Action", back_populates="tool")


class Action(Base):
    __tablename__ = "actions"

    id = Column(String(64), primary_key=True, index=True)
    run_id = Column(String(64), ForeignKey('runs.id'), nullable=True)
    tool_id = Column(String(64), ForeignKey('tools.id'), nullable=True)
    triggered_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=True)
    is_processed = Column(Boolean, default=False)
    processed_at = Column(DateTime, nullable=True)
    status = Column(String(64), nullable=True)
    function_args = Column(JSON, nullable=True)
    result = Column(JSON, nullable=True)

    tool = relationship("Tool", back_populates="actions")
    run = relationship("Run", back_populates="actions")

    @staticmethod
    def get_full_action_query(session):
        return session.query(Action).options(
            joinedload(Action.run),
            joinedload(Action.tool)
        )


class Sandbox(Base):
    __tablename__ = "sandboxes"

    id = Column(String(64), primary_key=True, index=True)
    user_id = Column(String(64), ForeignKey('users.id'), nullable=False)
    name = Column(String(128), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    status = Column(String(32), nullable=False, default="active")
    config = Column(JSON, nullable=True)
    user = relationship("User", back_populates="sandboxes")


class File(Base):
    __tablename__ = "files"

    id = Column(String(64), primary_key=True, index=True)
    object = Column(String(64), nullable=False, default="file")
    bytes = Column(Integer, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=True)
    filename = Column(String(256), nullable=False)
    purpose = Column(String(64), nullable=False)
    mime_type = Column(String(255))
    user_id = Column(String(64), ForeignKey('users.id'), nullable=False)
    user = relationship("User", back_populates="files")
    storage_locations = relationship("FileStorage", back_populates="file", cascade="all, delete-orphan")


class FileStorage(Base):
    __tablename__ = "file_storage"

    id = Column(Integer, primary_key=True, autoincrement=True)
    file_id = Column(String(64), ForeignKey('files.id', ondelete="CASCADE"), nullable=False)
    storage_system = Column(String(64), nullable=False, default="samba",
                            comment="Storage system type (samba, s3, etc.)")
    storage_path = Column(String(512), nullable=False,
                          comment="Path to file in storage system (relative to share root)")
    is_primary = Column(Boolean, default=True,
                        comment="Indicates if this is the primary storage location")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow,
                        comment="When this storage entry was created")
    file = relationship("File", back_populates="storage_locations")
    __table_args__ = (
        Index('idx_file_storage_file_id', 'file_id'),
    )



class VectorStore(Base):
    __tablename__ = "vector_stores"

    id = Column(String(64), primary_key=True, index=True)
    name = Column(String(128), nullable=False, unique=False)
    user_id = Column(String(64), ForeignKey('users.id'), nullable=False)
    collection_name = Column(String(128), nullable=False, unique=True)
    vector_size = Column(Integer, nullable=False)
    distance_metric = Column(String(32), nullable=False)
    created_at = Column(BigInteger, default=lambda: int(datetime.now().timestamp()))
    updated_at = Column(BigInteger, onupdate=lambda: int(datetime.now().timestamp()))
    status = Column(SAEnum(StatusEnum), nullable=False)
    config = Column(JSON, nullable=True)
    file_count = Column(Integer, default=0, nullable=False)  # Added field
    user = relationship("User", back_populates="vector_stores", lazy="select")
    threads = relationship(
        "Thread",
        secondary="thread_vector_stores",
        back_populates="vector_stores",
        lazy="select"
    )
    assistants = relationship(
        "Assistant",
        secondary="vector_store_assistants",
        back_populates="vector_stores",
        lazy="select",
        passive_deletes=True
    )
    files = relationship(
        "VectorStoreFile",
        back_populates="vector_store",
        cascade="all, delete-orphan",
        lazy="dynamic"
    )


class VectorStoreFile(Base):
    __tablename__ = "vector_store_files"

    id = Column(String(64), primary_key=True, index=True)
    vector_store_id = Column(String(64), ForeignKey('vector_stores.id'), nullable=False)
    file_name = Column(String(256), nullable=False)
    file_path = Column(String(1024), nullable=False)
    processed_at = Column(Integer, nullable=True)
    status = Column(SAEnum(StatusEnum), default=StatusEnum.queued)
    error_message = Column(Text, nullable=True)
    meta_data = Column(JSON, nullable=True)
    vector_store = relationship("VectorStore", back_populates="files")
