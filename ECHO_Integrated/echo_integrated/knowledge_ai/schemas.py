"""Pydantic schemas shared by every knowledge_ai module."""

from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


# --------------------------------------------------------------------------
# Enumerations
# --------------------------------------------------------------------------
class EntityType(str, Enum):
    PERSON = "PERSON"
    ORGANIZATION = "ORGANIZATION"
    COMMITTEE = "COMMITTEE"
    DEPARTMENT = "DEPARTMENT"
    EVENT = "EVENT"
    MEETING = "MEETING"
    DECISION = "DECISION"
    REASON = "REASON"
    ACTION = "ACTION"
    DATE = "DATE"
    DOCUMENT = "DOCUMENT"


class RelationType(str, Enum):
    HELD_ON = "HELD_ON"  # MEETING/EVENT -> DATE
    CONVENED = "CONVENED"  # COMMITTEE/DEPARTMENT/ORGANIZATION -> MEETING/EVENT
    ATTENDED = "ATTENDED"  # PERSON -> MEETING/EVENT
    CHAIRED = "CHAIRED"  # PERSON -> MEETING/EVENT/COMMITTEE
    MEMBER_OF = "MEMBER_OF"  # PERSON -> COMMITTEE/DEPARTMENT/ORGANIZATION
    PART_OF = "PART_OF"  # COMMITTEE/DEPARTMENT/ORGANIZATION -> same
    PROPOSED_BY = "PROPOSED_BY"  # DECISION -> PERSON/COMMITTEE/...
    APPROVED_BY = "APPROVED_BY"  # DECISION -> PERSON/COMMITTEE/...
    REJECTED_BY = "REJECTED_BY"  # DECISION -> PERSON/COMMITTEE/...
    DEFERRED_BY = "DEFERRED_BY"  # DECISION -> PERSON/COMMITTEE/...
    DECIDED_AT = "DECIDED_AT"  # DECISION -> MEETING/EVENT
    DECIDED_ON = "DECIDED_ON"  # DECISION -> DATE
    JUSTIFIED_BY = "JUSTIFIED_BY"  # DECISION -> REASON
    LED_TO = "LED_TO"  # DECISION -> ACTION
    ASSIGNED_TO = "ASSIGNED_TO"  # ACTION -> PERSON/DEPARTMENT/...
    DUE_ON = "DUE_ON"  # ACTION -> DATE
    FOLLOWS_UP = "FOLLOWS_UP"  # DECISION -> DECISION
    SUPERSEDES = "SUPERSEDES"  # DECISION -> DECISION
    MENTIONED_IN = "MENTIONED_IN"  # anything -> DOCUMENT
    RELATED_TO = "RELATED_TO"  # anything -> anything (fallback)


_E = EntityType
_GROUPS = {_E.COMMITTEE, _E.DEPARTMENT, _E.ORGANIZATION}
_ACTORS = _GROUPS | {_E.PERSON}
_MEET = {_E.MEETING, _E.EVENT}

# relation -> (allowed source types, allowed target types); None = anything
RELATION_RULES: Dict[RelationType, Tuple[Optional[Set[EntityType]], Optional[Set[EntityType]]]] = {
    RelationType.HELD_ON: (_MEET, {_E.DATE}),
    RelationType.CONVENED: (_GROUPS, _MEET),
    RelationType.ATTENDED: ({_E.PERSON}, _MEET),
    RelationType.CHAIRED: ({_E.PERSON}, _MEET | {_E.COMMITTEE}),
    RelationType.MEMBER_OF: ({_E.PERSON}, _GROUPS),
    RelationType.PART_OF: (_GROUPS, _GROUPS),
    RelationType.PROPOSED_BY: ({_E.DECISION}, _ACTORS),
    RelationType.APPROVED_BY: ({_E.DECISION}, _ACTORS),
    RelationType.REJECTED_BY: ({_E.DECISION}, _ACTORS),
    RelationType.DEFERRED_BY: ({_E.DECISION}, _ACTORS),
    RelationType.DECIDED_AT: ({_E.DECISION}, _MEET),
    RelationType.DECIDED_ON: ({_E.DECISION}, {_E.DATE}),
    RelationType.JUSTIFIED_BY: ({_E.DECISION}, {_E.REASON}),
    RelationType.LED_TO: ({_E.DECISION}, {_E.ACTION}),
    RelationType.ASSIGNED_TO: ({_E.ACTION}, _ACTORS),
    RelationType.DUE_ON: ({_E.ACTION}, {_E.DATE}),
    RelationType.FOLLOWS_UP: ({_E.DECISION}, {_E.DECISION}),
    RelationType.SUPERSEDES: ({_E.DECISION}, {_E.DECISION}),
    RelationType.MENTIONED_IN: (None, {_E.DOCUMENT}),
    RelationType.RELATED_TO: (None, None),
}

ENTITY_TYPE_ALIASES = {
    "ORG": "ORGANIZATION", "INSTITUTION": "ORGANIZATION", "UNIVERSITY": "ORGANIZATION",
    "COLLEGE": "ORGANIZATION", "PEOPLE": "PERSON", "INDIVIDUAL": "PERSON",
    "BOARD": "COMMITTEE", "COUNCIL": "COMMITTEE", "DEPT": "DEPARTMENT", "DOC": "DOCUMENT",
    "RESOLUTION": "DECISION", "TASK": "ACTION", "ACTION_ITEM": "ACTION",
    "RATIONALE": "REASON", "JUSTIFICATION": "REASON",
}

RELATION_ALIASES = {
    "APPROVED": "APPROVED_BY", "APPROVES": "APPROVED_BY", "REJECTED": "REJECTED_BY",
    "PROPOSED": "PROPOSED_BY", "DEFERRED": "DEFERRED_BY", "HELD": "HELD_ON",
    "DECIDED_IN": "DECIDED_AT", "DECIDED_DURING": "DECIDED_AT", "JUSTIFIED": "JUSTIFIED_BY",
    "REASON": "JUSTIFIED_BY", "BECAUSE_OF": "JUSTIFIED_BY", "RESULTED_IN": "LED_TO",
    "ASSIGNED": "ASSIGNED_TO", "RESPONSIBLE_FOR": "ASSIGNED_TO", "ATTENDEE_OF": "ATTENDED",
    "SUPERSEDED": "SUPERSEDES", "ORGANIZED": "CONVENED", "ORGANISED": "CONVENED",
}


def coerce_entity_type(value: Any) -> EntityType:
    """Convert free text to EntityType. Raises ValueError if unknown."""
    if isinstance(value, EntityType):
        return value
    key = str(value or "").strip().upper().replace(" ", "_").replace("-", "_")
    key = ENTITY_TYPE_ALIASES.get(key, key)
    try:
        return EntityType(key)
    except ValueError:
        raise ValueError(f"unknown entity type: {value!r}")


def coerce_relation_type(value: Any) -> RelationType:
    """Convert free text to RelationType. Unknown values become RELATED_TO."""
    if isinstance(value, RelationType):
        return value
    key = str(value or "").strip().upper().replace(" ", "_").replace("-", "_")
    key = RELATION_ALIASES.get(key, key)
    try:
        return RelationType(key)
    except ValueError:
        return RelationType.RELATED_TO


def fix_direction(
    relation: RelationType, source_type: EntityType, target_type: EntityType
) -> Optional[bool]:
    """Check endpoint types against RELATION_RULES.

    Returns False if the direction is fine, True if source/target must be
    swapped, None if the combination is invalid.
    """
    src_ok, tgt_ok = RELATION_RULES[relation]
    if (src_ok is None or source_type in src_ok) and (tgt_ok is None or target_type in tgt_ok):
        return False
    if (src_ok is None or target_type in src_ok) and (tgt_ok is None or source_type in tgt_ok):
        return True
    return None


def _clean_optional(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = " ".join(str(value).split())
    if text.lower() in ("", "null", "none", "n/a", "unknown"):
        return None
    return text


# --------------------------------------------------------------------------
# Input documents
# --------------------------------------------------------------------------
class SourceChunk(BaseModel):
    """A piece of cleaned document text plus its source metadata."""

    text: str
    document_id: Optional[str] = None
    filename: Optional[str] = None
    page: Optional[int] = None
    chunk_id: Optional[str] = None


class SourceDocument(BaseModel):
    """A cleaned document. Give `pages` (page numbers = 1..n) or plain `text`."""

    document_id: str
    filename: Optional[str] = None
    pages: Optional[List[str]] = None
    text: Optional[str] = None

    @model_validator(mode="after")
    def _need_content(self) -> "SourceDocument":
        if self.pages is None and self.text is None:
            raise ValueError("SourceDocument needs `pages` or `text`")
        return self


# --------------------------------------------------------------------------
# Raw (model output) schemas - lenient on input
# --------------------------------------------------------------------------
class RawEntity(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    type: EntityType
    date: Optional[str] = None
    description: Optional[str] = None
    evidence: Optional[str] = None

    @field_validator("name", mode="before")
    @classmethod
    def _name(cls, v: Any) -> str:
        text = _clean_optional(v)
        if not text:
            raise ValueError("name is required")
        return text

    @field_validator("type", mode="before")
    @classmethod
    def _type(cls, v: Any) -> EntityType:
        return coerce_entity_type(v)

    @field_validator("date", "description", "evidence", mode="before")
    @classmethod
    def _optional(cls, v: Any) -> Optional[str]:
        return _clean_optional(v)


class RawRelationship(BaseModel):
    model_config = ConfigDict(extra="ignore")

    source: str
    target: str
    relation: RelationType
    source_type: Optional[EntityType] = None
    target_type: Optional[EntityType] = None
    date: Optional[str] = None
    evidence: Optional[str] = None

    @field_validator("source", "target", mode="before")
    @classmethod
    def _endpoint(cls, v: Any) -> str:
        text = _clean_optional(v)
        if not text:
            raise ValueError("endpoint name is required")
        return text

    @field_validator("relation", mode="before")
    @classmethod
    def _relation(cls, v: Any) -> RelationType:
        return coerce_relation_type(v)

    @field_validator("source_type", "target_type", mode="before")
    @classmethod
    def _hint(cls, v: Any) -> Optional[EntityType]:
        if v is None or str(v).strip() == "":
            return None
        try:
            return coerce_entity_type(v)
        except ValueError:
            return None

    @field_validator("date", "evidence", mode="before")
    @classmethod
    def _optional(cls, v: Any) -> Optional[str]:
        return _clean_optional(v)


class RawAnswer(BaseModel):
    """Expected JSON from the answer-generation prompt."""

    model_config = ConfigDict(extra="ignore")

    answer: str = ""
    sufficient_evidence: bool = True
    used_sources: List[str] = Field(default_factory=list)

    @field_validator("used_sources", mode="before")
    @classmethod
    def _sources(cls, v: Any) -> List[str]:
        if v is None:
            return []
        if isinstance(v, str):
            v = [v]
        return [str(x).strip().strip("[]").upper() for x in v]


# --------------------------------------------------------------------------
# Validated, normalized knowledge
# --------------------------------------------------------------------------
class Provenance(BaseModel):
    """Where a fact came from. Fields are None when unknown - never invented."""

    document_id: Optional[str] = None
    filename: Optional[str] = None
    page: Optional[int] = None
    chunk_id: Optional[str] = None
    evidence: Optional[str] = None
    mode: str = "real"  # "real" (Ollama), "mock" (rule-based) or another label

    def key(self) -> Tuple[Any, ...]:
        return (self.document_id, self.page, self.chunk_id, self.evidence, self.mode)


class SourceRef(Provenance):
    """A Provenance with a citation label such as S1 (used in answers)."""

    label: str = ""


class Entity(BaseModel):
    id: str
    name: str
    type: EntityType
    aliases: List[str] = Field(default_factory=list)
    date_iso: Optional[str] = None  # YYYY-MM-DD (or YYYY-MM) when text supports it
    description: Optional[str] = None
    provenance: List[Provenance] = Field(default_factory=list)


class Relationship(BaseModel):
    source_id: str
    target_id: str
    relation: RelationType
    date_iso: Optional[str] = None
    provenance: List[Provenance] = Field(default_factory=list)


class ExtractionResult(BaseModel):
    document_id: Optional[str] = None
    entities: List[Entity] = Field(default_factory=list)
    relationships: List[Relationship] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)  # dropped items / failures
    warnings: List[str] = Field(default_factory=list)  # ignored evidence/dates etc.
    mode: str = "real"  # "mock", "real", "mixed" ...
    model: Optional[str] = None
    chunks_processed: int = 0
    chunks_failed: int = 0
    llm_unavailable: bool = False

    @property
    def ok(self) -> bool:
        return self.chunks_failed == 0 and not self.llm_unavailable


# --------------------------------------------------------------------------
# Retrieval / answer schemas
# --------------------------------------------------------------------------
class TrailStep(BaseModel):
    date_iso: Optional[str] = None
    kind: str  # PROPOSED, APPROVED, REJECTED, DEFERRED, MEETING, REASON, ACTION, RELATED_DECISION
    description: str
    actor: Optional[str] = None
    meeting: Optional[str] = None
    decision_id: str
    decision_name: str
    provenance: List[Provenance] = Field(default_factory=list)


class DecisionTrail(BaseModel):
    decision_id: str
    decision_name: str
    status: str = "unknown"  # proposed / approved / rejected / deferred / superseded / unknown
    first_date: Optional[str] = None
    steps: List[TrailStep] = Field(default_factory=list)
    reasons: List[str] = Field(default_factory=list)


class ScoredEntity(BaseModel):
    id: str
    name: str
    type: str
    score: float


class RetrievalResult(BaseModel):
    question: str
    query_tokens: List[str] = Field(default_factory=list)
    matched_dates: List[str] = Field(default_factory=list)
    entities: List[ScoredEntity] = Field(default_factory=list)
    decisions: List[DecisionTrail] = Field(default_factory=list)
    evidence: List[Provenance] = Field(default_factory=list)
    coverage: float = 0.0
    sufficient: bool = False
    reason: Optional[str] = None


class AnswerResult(BaseModel):
    question: str
    answer: str
    sufficient_evidence: bool
    decision_trail: List[TrailStep] = Field(default_factory=list)
    sources: List[SourceRef] = Field(default_factory=list)
    mode: str = "real"  # "mock" results are rule-based, NOT AI-generated
    llm_used: bool = False
    model: Optional[str] = None
    warnings: List[str] = Field(default_factory=list)
    error: Optional[str] = None
