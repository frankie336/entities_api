import time
from datetime import datetime
from sqlalchemy import Column, String, Integer, Boolean, JSON, DateTime, ForeignKey, Table, Text
from sqlalchemy.orm import relationship, declarative_base, joinedload
from sqlalchemy import Enum
from enum import Enum as PyEnum

Base = declarative_base()

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



class StatusEnum(PyEnum):
    queued = "queued"
    in_progress = "in_progress"
    pending_action ="action_required"
    completed = "completed"
    failed = "failed"
    cancelling = "cancelling"
    cancelled = "cancelled"
    pending = "pending"
    processing = "processing"
    expired = "expired"
    retrying = "retrying"


# Models
class User(Base):
    __tablename__ = "users"

    id = Column(String(64), primary_key=True, index=True)
    name = Column(String(128), index=True)

    threads = relationship('Thread', secondary=thread_participants, back_populates='participants')
    assistants = relationship('Assistant', secondary=user_assistants, back_populates='users')
    sandboxes = relationship('Sandbox', back_populates='user', cascade="all, delete-orphan")


class Thread(Base):
    __tablename__ = "threads"

    id = Column(String(64), primary_key=True, index=True)
    created_at = Column(Integer, nullable=False)
    meta_data = Column(JSON, nullable=False, default={})
    object = Column(String(64), nullable=False)
    tool_resources = Column(JSON, nullable=False, default={})

    participants = relationship('User', secondary=thread_participants, back_populates='threads')


from sqlalchemy import Text

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
    status = Column(Enum(StatusEnum), nullable=False)  # Use StatusEnum here
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
    model = Column(String(64), nullable=False)
    instructions = Column(String(2024), nullable=True)
    meta_data = Column(JSON, nullable=True)
    top_p = Column(Integer, nullable=True)
    temperature = Column(Integer, nullable=True)
    response_format = Column(String(64), nullable=True)

    tools = relationship("Tool", secondary=assistant_tools, back_populates="assistants", lazy="joined")
    users = relationship("User", secondary=user_assistants, back_populates="assistants")


class Tool(Base):
    __tablename__ = "tools"

    id = Column(String(64), primary_key=True, index=True)
    name = Column(String(128), nullable=False)
    type = Column(String(64), nullable=False)
    function = Column(JSON, nullable=True)

    assistants = relationship("Assistant", secondary=assistant_tools, back_populates="tools")
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
    status = Column(Enum(StatusEnum), nullable=False, default=StatusEnum.pending)  # Use StatusEnum here
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
