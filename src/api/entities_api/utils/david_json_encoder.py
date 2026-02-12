import json


class DavidJSONEncoder(json.JSONEncoder):
    """
    Handles Pydantic models (StatusEvent, etc.) during json.dumps.
    Works for both Pydantic v1 and v2.
    """

    def default(self, obj):
        # Handle Pydantic v2
        if hasattr(obj, "model_dump"):
            return obj.model_dump()
        # Handle Pydantic v1
        if hasattr(obj, "dict") and callable(obj.dict):
            return obj.dict()
        # Handle other non-serializables
        if isinstance(obj, (set, tuple)):
            return list(obj)
        return super().default(obj)


def david_dumps(obj) -> str:
    """Centralized, safe JSON dumper for the entire Agentic stack."""
    return json.dumps(obj, cls=DavidJSONEncoder)
