# src/api/entities_api/orchestration/mixins/create_supervisor.py
from projectdavid import Entity

from src.api.entities_api.constants.delegator import SUPERVISOR_TOOLS
from src.api.entities_api.orchestration.instructions.definitions import \
    SUPERVISOR_SYSTEM_PROMPT


def create_supervisor_assistant(client: Entity):
    """
    Creates the 'Brain' of the operation.
    """
    supervisor = client.assistants.create_assistant(
        name="Deep Research Supervisor",
        model="gpt-4o",  # Needs a smart model to plan
        instructions=SUPERVISOR_SYSTEM_PROMPT,  # <--- Level 4 Instructions
        tools=SUPERVISOR_TOOLS,
        # ^^^ This list contains:
        # 1. delegate_research_task
        # 2. read_scratchpad
        # 3. update_scratchpad
        # 4. append_scratchpad
        # IT DOES NOT CONTAIN: perform_web_search, read_web_page, etc.
    )
    return supervisor
