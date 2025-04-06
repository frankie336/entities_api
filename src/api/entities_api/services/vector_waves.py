# entities_api/services/vector_waves.py
from typing import Dict
from entities_api.services.vector_store_service import VectorStoreService


class AssistantVectorWaves:
    def __init__(self, vector_service: VectorStoreService):
        self.vector_service = vector_service

    def _initialize_core_waves(self, assistant_id: str, user_id: str) -> Dict[str, dict]:
        """Create and associate core vector stores with the assistant"""

        waves_config = {
            "memory": {
                "name": f"{assistant_id}-memory",
                "vector_size": 1024,
                "description": "Long-term knowledge storage",
            },
            "conversation": {
                "name": f"{assistant_id}-chat",
                "vector_size": 768,
                "description": "Dialog context history",
            },
            "documents": {
                "name": f"{assistant_id}-documents",
                "vector_size": 512,
                "description": "User-uploaded file storage",
            },
        }

        created_waves = {}
        for wave_type, config in waves_config.items():
            # Create vector store
            store = self.vector_service.create_vector_store(
                name=config["name"],
                user_id=user_id,
            )

            # Attach to assistant
            self.vector_service.attach_vector_store_to_assistant(
                vector_store_id=store.id, assistant_id=assistant_id
            )

            created_waves[wave_type] = {"store": store, "config": config}

        return created_waves

    def get_wave_store(self, wave_type: str) -> VectorStoreService:
        """Get initialized vector store for a specific wave"""
        if wave_type not in self.waves:
            raise ValueError(
                f"Invalid wave type: {wave_type}. Valid options: {list(self.waves.keys())}"
            )
        return self.waves[wave_type]["store"]
