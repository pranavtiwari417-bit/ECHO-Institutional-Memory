"""
ECHO - Retrieval Service

Handles:
- Document retrieval from SQLite
- Entity retrieval
- Relationship retrieval
- Decision retrieval
- Source retrieval
- Knowledge graph context
"""

from typing import Any, Dict, List

from services.database import (
    search_documents,
    get_entities,
    get_relationships,
    get_decisions,
    get_sources,
)

from services.graph_service import (
    get_graph_stats,
    get_related_entities,
)


def retrieve_documents(query: str, top_k: int = 5) -> List[Dict[str, Any]]:
    """Retrieve relevant documents from SQLite."""
    if not query.strip():
        return []

    try:
        results = search_documents(query.strip(), limit=top_k)

        if not results:
            return []

        return results

    except Exception:
        return []


def retrieve_entities(query: str, top_k: int = 10) -> List[Dict[str, Any]]:
    """Retrieve entities matching the query."""
    try:
        entities = get_entities()

        query_words = query.lower().split()

        matched = []

        for entity in entities:
            name = str(entity.get("name", "")).lower()
            entity_type = str(entity.get("entity_type", "")).lower()

            score = 0

            for word in query_words:
                if word in name:
                    score += 2
                if word in entity_type:
                    score += 1

            if score > 0:
                item = dict(entity)
                item["_relevance"] = score
                matched.append(item)

        matched.sort(
            key=lambda x: x.get("_relevance", 0),
            reverse=True
        )

        return matched[:top_k]

    except Exception:
        return []


def retrieve_relationships(
    entity_name: str = "",
    top_k: int = 20
) -> List[Dict[str, Any]]:
    """Retrieve relationships from the knowledge base."""
    try:
        relationships = get_relationships()

        if not entity_name:
            return relationships[:top_k]

        name = entity_name.lower()

        matched = [
            relationship
            for relationship in relationships
            if name in str(
                relationship.get("source_entity", "")
            ).lower()
            or name in str(
                relationship.get("target_entity", "")
            ).lower()
        ]

        return matched[:top_k]

    except Exception:
        return []


def retrieve_decisions(
    query: str = "",
    top_k: int = 10
) -> List[Dict[str, Any]]:
    """Retrieve decisions related to the query."""
    try:
        decisions = get_decisions()

        if not query.strip():
            return decisions[:top_k]

        query_words = query.lower().split()
        matched = []

        for decision in decisions:
            text = " ".join([
                str(decision.get("title", "")),
                str(decision.get("description", "")),
                str(decision.get("reason", "")),
                str(decision.get("meeting", "")),
            ]).lower()

            score = sum(
                1 for word in query_words
                if word in text
            )

            if score > 0:
                item = dict(decision)
                item["_relevance"] = score
                matched.append(item)

        matched.sort(
            key=lambda x: x.get("_relevance", 0),
            reverse=True
        )

        return matched[:top_k]

    except Exception:
        return []


def retrieve_sources(
    document_ids: List[int] | None = None,
    top_k: int = 20
) -> List[Dict[str, Any]]:
    """Retrieve source information."""
    try:
        sources = get_sources()

        if document_ids:
            sources = [
                source
                for source in sources
                if source.get("document_id") in document_ids
            ]

        return sources[:top_k]

    except Exception:
        return []


def retrieve_graph_context(
    entity_name: str = "",
    top_k: int = 10
) -> Dict[str, Any]:
    """Retrieve relevant knowledge graph information."""
    try:
        stats = get_graph_stats()

        related = []

        if entity_name.strip():
            related = get_related_entities(
                entity_name.strip(),
                max_depth=1
            )

        return {
            "stats": stats,
            "entity": entity_name,
            "related_entities": related[:top_k]
        }

    except Exception:
        return {
            "stats": {},
            "entity": entity_name,
            "related_entities": []
        }


def retrieve_context(
    query: str,
    top_k: int = 5
) -> Dict[str, Any]:
    """
    Main retrieval function.

    Combines:
    - Documents
    - Entities
    - Relationships
    - Decisions
    - Sources
    - Knowledge graph context
    """

    documents = retrieve_documents(query, top_k)

    entities = retrieve_entities(query, top_k)

    decisions = retrieve_decisions(query, top_k)

    relationships = []

    if entities:
        relationships = retrieve_relationships(
            entities[0].get("name", ""),
            top_k=20
        )

    document_ids = [
        document.get("id")
        for document in documents
        if document.get("id") is not None
    ]

    sources = retrieve_sources(
        document_ids=document_ids,
        top_k=20
    )

    graph_context = {
        "stats": {},
        "entity": "",
        "related_entities": []
    }

    if entities:
        graph_context = retrieve_graph_context(
            entities[0].get("name", ""),
            top_k=top_k
        )

    return {
        "query": query,
        "documents": documents,
        "entities": entities,
        "relationships": relationships,
        "decisions": decisions,
        "sources": sources,
        "graph_context": graph_context
    }


def build_context_text(context: Dict[str, Any]) -> str:
    """Convert retrieved information into readable context."""

    parts = []

    documents = context.get("documents", [])

    if documents:
        parts.append("RELEVANT DOCUMENTS:")

        for document in documents:
            parts.append(
                f"- {document.get('title') or document.get('filename', '')}: "
                f"{document.get('content', '')}"
            )

    entities = context.get("entities", [])

    if entities:
        parts.append("\nENTITIES:")

        for entity in entities:
            parts.append(
                f"- {entity.get('name', '')} "
                f"({entity.get('entity_type', '')})"
            )

    relationships = context.get("relationships", [])

    if relationships:
        parts.append("\nRELATIONSHIPS:")

        for relationship in relationships:
            parts.append(
                f"- {relationship.get('source_entity', '')} "
                f"--[{relationship.get('relation', '')}]--> "
                f"{relationship.get('target_entity', '')}"
            )

    decisions = context.get("decisions", [])

    if decisions:
        parts.append("\nDECISIONS:")

        for decision in decisions:
            parts.append(
                f"- {decision.get('title', '')}: "
                f"{decision.get('description', '')}"
            )

    sources = context.get("sources", [])

    if sources:
        parts.append("\nSOURCES:")

        for source in sources:
            parts.append(
                f"- {source.get('filename', '')}"
                f" | Page: {source.get('page_number', 'N/A')}"
            )

    return "\n".join(parts)


def retrieve(query: str, top_k: int = 5) -> Dict[str, Any]:
    """Public retrieval API."""
    context = retrieve_context(query, top_k)

    context["context_text"] = build_context_text(context)

    return context