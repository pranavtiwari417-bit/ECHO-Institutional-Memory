"""
ECHO - Institutional Memory & Decision Intelligence Engine

File: backend/models/schema.py
Purpose:
    Common data models used by the ECHO backend.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# ============================================================
# DOCUMENT
# ============================================================

@dataclass
class Document:
    id: Optional[int] = None
    filename: str = ""
    title: str = ""
    content: str = ""
    file_path: str = ""
    file_type: str = ""
    created_at: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


# ============================================================
# ENTITY
# ============================================================

@dataclass
class Entity:
    id: Optional[int] = None
    name: str = ""
    entity_type: str = ""
    document_id: Optional[int] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


# ============================================================
# RELATIONSHIP
# ============================================================

@dataclass
class Relationship:
    id: Optional[int] = None
    source_entity: str = ""
    relation: str = ""
    target_entity: str = ""
    document_id: Optional[int] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


# ============================================================
# DECISION
# ============================================================

@dataclass
class Decision:
    id: Optional[int] = None
    title: str = ""
    description: str = ""
    reason: str = ""
    date: Optional[str] = None
    meeting: Optional[str] = None
    document_id: Optional[int] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


# ============================================================
# SOURCE / EVIDENCE
# ============================================================

@dataclass
class Source:
    id: Optional[int] = None
    document_id: Optional[int] = None
    filename: str = ""
    page_number: Optional[int] = None
    text: str = ""
    source_type: str = "document"
    metadata: Dict[str, Any] = field(default_factory=dict)


# ============================================================
# SEARCH RESULT
# ============================================================

@dataclass
class SearchResult:
    document_id: Optional[int] = None
    filename: str = ""
    title: str = ""
    text: str = ""
    relevance: float = 0.0
    page_number: Optional[int] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


# ============================================================
# RETRIEVAL CONTEXT
# ============================================================

@dataclass
class RetrievalContext:
    query: str
    documents: List[SearchResult] = field(default_factory=list)
    entities: List[Entity] = field(default_factory=list)
    relationships: List[Relationship] = field(default_factory=list)
    decisions: List[Decision] = field(default_factory=list)
    sources: List[Source] = field(default_factory=list)


# ============================================================
# QUERY REQUEST
# ============================================================

@dataclass
class QueryRequest:
    query: str
    top_k: int = 5


# ============================================================
# QUERY RESPONSE
# ============================================================

@dataclass
class QueryResponse:
    answer: str
    sources: List[Dict[str, Any]] = field(default_factory=list)
    entities: List[Dict[str, Any]] = field(default_factory=list)
    decisions: List[Dict[str, Any]] = field(default_factory=list)
    timeline: List[Dict[str, Any]] = field(default_factory=list)


# ============================================================
# HELPER FUNCTIONS
# ============================================================

def dataclass_to_dict(obj: Any) -> Dict[str, Any]:
    """
    Convert a dataclass object into a dictionary.
    """
    if obj is None:
        return {}

    if isinstance(obj, dict):
        return obj

    if hasattr(obj, "__dataclass_fields__"):
        from dataclasses import asdict
        return asdict(obj)

    raise TypeError(f"Object of type {type(obj).__name__} is not a dataclass.")