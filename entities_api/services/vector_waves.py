#entities_api/services/vector_waves.py
from typing import Dict, List
from pathlib import Path
from datetime import datetime
from entities_api.services.vector_store_service import VectorStoreService
from entities_api.models.models import Assistant


class AssistantVectorWaves:
    def __init__(self, vector_service: VectorStoreService, assistant_id: str, user_id: str):
        self.vector_service = vector_service
        self.assistant_id = assistant_id
        self.user_id = user_id
        self.waves = self._initialize_core_waves()

    def _initialize_core_waves(self) -> Dict[str, dict]:
        """Create and associate core vector stores with the assistant"""
        waves_config = {
            "memory": {
                "name": f"{self.assistant_id}-memory",
                "vector_size": 1024,
                "description": "Long-term knowledge storage"
            },
            "conversation": {
                "name": f"{self.assistant_id}-conversation",
                "vector_size": 768,
                "description": "Dialog context history"
            },
            "documents": {
                "name": f"{self.assistant_id}-documents",
                "vector_size": 512,
                "description": "User-uploaded file storage"
            }
        }

        created_waves = {}
        for wave_type, config in waves_config.items():
            # Create vector store
            store = self.vector_service.create_vector_store(
                name=config['name'],
                user_id=self.user_id,
                vector_size=config['vector_size']
            )

            # Attach to assistant
            self.vector_service.attach_vector_store_to_assistant(
                vector_store_id=store.id,
                assistant_id=self.assistant_id
            )

            created_waves[wave_type] = {
                "store": store,
                "config": config
            }

        return created_waves

    def get_wave_store(self, wave_type: str) -> VectorStoreService:
        """Get initialized vector store for a specific wave"""
        if wave_type not in self.waves:
            raise ValueError(f"Invalid wave type: {wave_type}. Valid options: {list(self.waves.keys())}")
        return self.waves[wave_type]["store"]

    def add_to_memory(self, text: str, metadata: dict = None):
        """Store long-term knowledge"""
        store = self.get_wave_store("memory")
        return self.vector_service.add_texts(
            store_name=store.collection_name,
            texts=[text],
            metadata=[metadata or {}]
        )

    def add_conversation(self, dialog: str, speaker: str = "user"):
        """Store conversation context"""
        store = self.get_wave_store("conversation")
        return self.vector_service.add_texts(
            store_name=store.collection_name,
            texts=[dialog],
            metadata=[{
                "timestamp": datetime.now().isoformat(),
                "speaker": speaker,
                "type": "conversation"
            }]
        )

    def add_document(self, file_path: Path, source_url: str = None):
        """Process and store uploaded documents"""
        store = self.get_wave_store("documents")
        return self.vector_service.add_files(
            file_path=file_path,
            destination_store=store.collection_name,
            source_url=source_url,
            user_metadata={
                "original_filename": file_path.name,
                "uploaded_at": datetime.now().isoformat()
            }
        )

    def search_wave(self, wave_type: str, query: str, **kwargs) -> List[dict]:
        """Unified search across waves"""
        store = self.get_wave_store(wave_type)
        return self.vector_service.search_vector_store(
            store_name=store.collection_name,
            query_text=query,
            **kwargs
        )