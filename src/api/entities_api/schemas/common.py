from enum import Enum
from enum import Enum as PyEnum


class ProviderEnum(str, Enum):
    openai = "openai"
    deepseek = "deepseek"
    hyperbolic = "Hyperbolic"
    togetherai = "togetherai"
    local = "local"


class StatusEnum(PyEnum):
    deleted = "deleted"
    active = "active"  # Added this member
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
