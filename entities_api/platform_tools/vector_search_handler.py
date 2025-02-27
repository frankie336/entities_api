from entities_api import OllamaClient
from entities_api.schemas import VectorStoreSearchResult
from entities_api.services.vector_store_service import VectorStoreService
from typing import Optional, List, Dict, Any, Union
from qdrant_client.http import models
import logging

client = OllamaClient()

class VectorSearchHandler:
    def __init__(self, assistant_id: str):
        self.assistant_id = assistant_id
        self.vector_store_service = VectorStoreService()
        self.source_mapping = self._build_dynamic_source_mapping()

    def _build_dynamic_source_mapping(self) -> Dict[str, str]:
        """Dynamically map source types to collection names"""
        stores = self.vector_store_service.get_vector_stores_for_assistant(
            assistant_id=self.assistant_id
        )

        mapping = {}
        for store in stores:
            try:
                _, source_type = store.name.split("-", 1)
                mapping[source_type] = store.collection_name
            except ValueError:
                logging.warning(
                    f"Skipping store '{store.name}' - invalid name format. "
                    f"Expected '{self.assistant_id}-<source_type>'"
                )
        return mapping

    def execute_search(self, **kwargs) -> List[VectorStoreSearchResult]:
        """Main entry point for vector searches"""
        search_type = kwargs.get("search_type", "basic_semantic")
        handler = getattr(self, f"handle_{search_type}", self.handle_basic_semantic)
        return handler(kwargs)

    def handle_basic_semantic(self, params: Dict) -> List[VectorStoreSearchResult]:
        """Basic vector similarity search"""
        return self.vector_store_service.search_vector_store(
            store_name=self._get_collection_name(params["source_type"]),
            query_text=params["query"],
            top_k=params.get("top_k", 5)
        )

    def handle_filtered(self, params: Dict) -> List[VectorStoreSearchResult]:
        """Metadata-filtered search"""
        return self.vector_store_service.search_vector_store(
            store_name=self._get_collection_name(params["source_type"]),
            query_text=params["query"],
            filters=params.get("filters", {}),
            score_threshold=params.get("score_threshold", 0.4)
        )

    def handle_complex_filters(self, params: Dict) -> List[VectorStoreSearchResult]:
        """Boolean logic filter search"""
        return self.vector_store_service.search_vector_store(
            store_name=self._get_collection_name(params["source_type"]),
            query_text=params["query"],
            filters=self._parse_complex_filters(params["filters"]),
            explain=params.get("explain", True)
        )

    def handle_temporal(self, params: Dict) -> List[VectorStoreSearchResult]:
        """Time-weighted search"""
        return self.vector_store_service.search_vector_store(
            store_name=self._get_collection_name(params["source_type"]),
            query_text=params["query"],
            score_boosts=params.get("score_boosts", {"created_at": 1.05})
        )

    def handle_explainable(self, params: Dict) -> List[VectorStoreSearchResult]:
        """Search with scoring explanations"""
        return self.vector_store_service.search_vector_store(
            store_name=self._get_collection_name(params["source_type"]),
            query_text=params["query"],
            explain=True
        )

    def handle_hybrid(self, params: Dict) -> List[VectorStoreSearchResult]:
        """Hybrid vector + keyword search"""
        return self.vector_store_service.search_vector_store(
            store_name=self._get_collection_name(params["source_type"]),
            query_text=params["query"],
            filters={"text_contains": params["search_query"]},
            score_boosts=params.get("score_boosts", {"keywords": 1.2})
        )

    def _get_collection_name(self, source_type: str) -> str:
        """Get validated collection name for source type"""
        collection_name = self.source_mapping.get(source_type)
        if not collection_name:
            available = list(self.source_mapping.keys())
            raise ValueError(
                f"No store found for source_type '{source_type}'. "
                f"Available types: {available}"
            )
        return collection_name

    def _parse_complex_filters(self, filters: Dict) -> models.Filter:
        """Convert JSON filters to Qdrant Filter objects"""
        return self._recursive_filter_builder(filters)

    def _recursive_filter_builder(self, condition: Union[Dict, List]) -> Union[models.Filter, models.FieldCondition]:
        """Recursively build Qdrant filter conditions"""
        if isinstance(condition, dict):
            for operator in ["$and", "$or", "$not"]:
                if operator in condition:
                    return self._handle_logical_operator(operator, condition[operator])
            return self._build_field_conditions(condition)
        elif isinstance(condition, list):
            return models.Filter(must=[self._recursive_filter_builder(c) for c in condition])
        raise ValueError(f"Unsupported condition type: {type(condition)}")

    def _handle_logical_operator(self, operator: str, conditions: List) -> models.Filter:
        """Process logical operators"""
        parsed_conditions = [self._recursive_filter_builder(c) for c in conditions]
        if operator == "$and":
            return models.Filter(must=parsed_conditions)
        elif operator == "$or":
            return models.Filter(should=parsed_conditions)
        elif operator == "$not":
            return models.Filter(must_not=parsed_conditions)
        raise ValueError(f"Unknown operator: {operator}")

    def _build_field_conditions(self, field_conditions: Dict) -> models.FieldCondition:
        """Build field-level conditions"""
        for field, condition in field_conditions.items():
            if isinstance(condition, dict):
                return self._parse_comparison_operators(field, condition)
            return models.FieldCondition(
                key=f"metadata.{field}",
                match=models.MatchValue(value=condition)
            )

    def _parse_comparison_operators(self, field: str, operators: Dict) -> models.FieldCondition:
        """Process comparison operators"""
        range_params = {}
        match_params = {}
        for op, value in operators.items():
            if op == "$gt":
                range_params["gt"] = value
            elif op == "$gte":
                range_params["gte"] = value
            elif op == "$lt":
                range_params["lt"] = value
            elif op == "$lte":
                range_params["lte"] = value
            elif op == "$ne":
                match_params["except"] = [value]
            elif op == "$in":
                match_params["any"] = value
            else:
                raise ValueError(f"Unsupported operator: {op}")

        if range_params:
            return models.FieldCondition(
                key=f"metadata.{field}",
                range=models.Range(**range_params)
            )
        elif match_params:
            if "except" in match_params:
                return models.FieldCondition(
                    key=f"metadata.{field}",
                    match=models.MatchExcept(**match_params)
                )
            return models.FieldCondition(
                key=f"metadata.{field}",
                match=models.MatchAny(**match_params)
            )
        raise ValueError("No valid operators found")