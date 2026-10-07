"""Echo knowledge_ai: offline knowledge graph + local-AI module for institutional decisions."""

from .answer_generator import INSUFFICIENT_MESSAGE, answer_question
from .config import Config, ConfigError, load_config
from .extractor import (
    chunk_text,
    extract_document,
    extract_from_chunk,
    merge_extractions,
    parse_date,
    validate_extraction_payload,
)
from .graph_builder import (
    build_graph,
    build_graph_from_documents,
    graph_from_dict,
    graph_has_mock_data,
    graph_stats,
    graph_to_dict,
    load_graph,
    save_graph,
)
from .llm_service import LLMError, LLMResponseError, LLMService, LLMUnavailableError
from .retriever import (
    entities_on_date,
    find_decisions_on_date,
    find_entities,
    find_path,
    get_decision_trail,
    list_decision_trails,
    neighbors,
    retrieve_context,
)
from .schemas import (
    AnswerResult,
    EntityType,
    ExtractionResult,
    RelationType,
    SourceChunk,
    SourceDocument,
)

__version__ = "0.1.0"

__all__ = [
    "AnswerResult", "Config", "ConfigError", "EntityType", "ExtractionResult",
    "INSUFFICIENT_MESSAGE", "LLMError", "LLMResponseError", "LLMService",
    "LLMUnavailableError", "RelationType", "SourceChunk", "SourceDocument",
    "answer_question", "build_graph", "build_graph_from_documents", "chunk_text",
    "entities_on_date", "extract_document", "extract_from_chunk", "find_decisions_on_date",
    "find_entities",
    "find_path", "get_decision_trail", "graph_from_dict", "graph_has_mock_data",
    "graph_stats", "graph_to_dict", "list_decision_trails", "load_config", "load_graph",
    "merge_extractions", "neighbors", "parse_date", "retrieve_context", "save_graph",
    "validate_extraction_payload",
]
