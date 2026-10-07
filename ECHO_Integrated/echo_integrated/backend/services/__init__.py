"""
ECHO - Institutional Memory & Decision Intelligence Engine

Services package initialization.
"""

from .database import (
    initialize_database,
    get_connection,
    add_document,
    get_document,
    get_all_documents,
    search_documents,
    update_document,
    delete_document,
    add_entity,
    get_entities,
    add_relationship,
    get_relationships,
    add_decision,
    get_decisions,
    add_source,
    get_sources,
    search_all,
)

from .graph_service import (
    initialize_graph,
    create_graph,
    load_graph,
    save_graph,
    rebuild_graph,
    get_graph_stats,
    get_node,
    get_related_entities,
    find_path,
    graph_to_dict,
)

from .llm_service import (
    generate_text,
    answer_query,
    summarize_text,
    extract_entities,
    extract_decisions,
    is_ollama_available,
    is_model_available,
    get_llm_status,
)

from .retrieval import (
    retrieve,
    retrieve_context,
    retrieve_documents,
    retrieve_entities,
    retrieve_relationships,
    retrieve_decisions,
    retrieve_sources,
)

__all__ = [
    "initialize_database",
    "get_connection",
    "add_document",
    "get_document",
    "get_all_documents",
    "search_documents",
    "update_document",
    "delete_document",
    "add_entity",
    "get_entities",
    "add_relationship",
    "get_relationships",
    "add_decision",
    "get_decisions",
    "add_source",
    "get_sources",
    "search_all",
    "initialize_graph",
    "create_graph",
    "load_graph",
    "save_graph",
    "rebuild_graph",
    "get_graph_stats",
    "get_node",
    "get_related_entities",
    "find_path",
    "graph_to_dict",
    "generate_text",
    "answer_query",
    "summarize_text",
    "extract_entities",
    "extract_decisions",
    "is_ollama_available",
    "is_model_available",
    "get_llm_status",
    "retrieve",
    "retrieve_context",
    "retrieve_documents",
    "retrieve_entities",
    "retrieve_relationships",
    "retrieve_decisions",
    "retrieve_sources",
]
