# src/api/entities_api/services/scratchpad_service.py
from datetime import datetime

from src.api.entities_api.cache.scratchpad_cache import ScratchpadCache


class ScratchpadService:
    def __init__(self, cache: ScratchpadCache):
        self.cache = cache

    async def get_formatted_view(self, thread_id: str) -> str:
        """
        Returns the scratchpad content formatted for the LLM's consumption.
        """
        data = await self.cache.get_scratchpad(thread_id)
        content = data.get("content", "")
        last_updated = data.get("last_updated", 0)

        if not content:
            return "(The scratchpad is currently empty. Use `update_scratchpad` to create a plan.)"

        # Convert timestamp to readable string
        dt = datetime.fromtimestamp(last_updated).strftime("%H:%M:%S")

        return (
            f"--- 📝 RESEARCH SCRATCHPAD (Last Updated: {dt}) ---\n"
            f"{content}\n"
            f"---------------------------------------------------"
        )

    async def update_content(self, thread_id: str, content: str):
        """Replaces the entire scratchpad (e.g., rewriting the plan)."""
        await self.cache.overwrite_scratchpad(thread_id, content)
        return "Scratchpad updated successfully."

    async def append_note(self, thread_id: str, note: str):
        """Adds a quick finding to the bottom."""
        await self.cache.append_to_scratchpad(thread_id, note)
        return "Note appended successfully."

    async def clear(self, thread_id: str):
        await self.cache.clear_scratchpad(thread_id)
        return "Scratchpad cleared."
