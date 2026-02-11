# src/api/entities_api/orchestration/mixins/orchestrator.py

from src.api.entities_api.orchestration.mixins.delegation_mixin import \
    DelegationMixin
from src.api.entities_api.orchestration.mixins.scratchpad_mixin import \
    ScratchpadMixin

# Note: We DO NOT import WebSearchMixin here because the Supervisor cannot browse!


class SupervisorOrchestrator(DelegationMixin, ScratchpadMixin):
    """
    This class represents the SUPERVISOR.
    It has the logic to manage memory (Scratchpad) and delegate tasks (Delegation),
    but it does not have the logic to browse the web directly.
    """

    def __init__(self, client):
        self.project_david_client = client

    # The 'handle_delegate_research_task' method is now available
    # to this class via inheritance from DelegationMixin.
