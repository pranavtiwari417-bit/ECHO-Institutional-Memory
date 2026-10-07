"""Extraction pipeline: chunk -> Gemma (or mock) -> Pydantic validation ->
grounding checks -> normalization -> deduplication.

Public functions:
    chunk_text, iter_document_chunks, validate_extraction_payload,
    extract_from_chunk, extract_document, merge_extractions,
    parse_date, dates_in_text, normalize_name, make_entity_id
"""

import re
from datetime import datetime
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple, Union

from pydantic import ValidationError

from .config import Config, load_config
from .llm_service import LLMError, LLMService, LLMUnavailableError
from .prompts import EXTRACTION_SYSTEM_PROMPT, build_extraction_prompt
from .schemas import (
    Entity,
    EntityType,
    ExtractionResult,
    Provenance,
    RawEntity,
    RawRelationship,
    Relationship,
    SourceChunk,
    SourceDocument,
    fix_direction,
)

# --------------------------------------------------------------------------
# Text helpers
# --------------------------------------------------------------------------
STOPWORDS = {
    "a", "an", "the", "of", "in", "on", "at", "to", "for", "from", "by", "with", "and", "or",
    "but", "is", "are", "was", "were", "be", "been", "being", "did", "do", "does", "done",
    "has", "have", "had", "it", "its", "this", "that", "these", "those", "as", "into", "than",
    "then", "there", "their", "they", "he", "she", "his", "her", "we", "our", "you", "your",
    "i", "me", "my", "not", "no", "if", "so", "such", "can", "could", "would", "should",
    "will", "shall", "may", "might", "must", "also", "all", "any", "each", "every", "both",
    "more", "most", "other", "some", "very", "who", "whom", "what", "when", "why", "how",
    "which", "where", "about", "after", "before", "during", "per", "up", "out", "over",
}

_MONTHS = (
    "January|February|March|April|May|June|July|August|September|October|November|December|"
    "Sept|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Oct|Nov|Dec"
)
DATE_PATTERN = (
    r"\b(?:\d{4}-\d{2}-\d{2}"
    rf"|(?:{_MONTHS})\.? \d{{1,2}}(?:st|nd|rd|th)?,? \d{{4}}"
    rf"|\d{{1,2}}(?:st|nd|rd|th)? (?:{_MONTHS})\.?,? \d{{4}}"
    rf"|(?:{_MONTHS})\.? \d{{4}})\b"
)
DATE_RE = re.compile(DATE_PATTERN)

_TITLE_RE = re.compile(r"^(?:dr|prof|professor|mr|mrs|ms|shri|smt)\.?\s+", re.IGNORECASE)
_ARTICLE_RE = re.compile(r"^(?:the|a|an)\s+", re.IGNORECASE)


def normalize_text(text: str) -> str:
    """Lowercase, replace punctuation with single spaces."""
    return " ".join(re.sub(r"[\W_]+", " ", (text or "").lower()).split())


def parse_date(text: Optional[str]) -> Optional[str]:
    """Parse the first date found in `text` into 'YYYY-MM-DD' (or 'YYYY-MM').

    Returns None when no valid date is present. Pure Python - never asks the model.
    """
    if not text:
        return None
    match = DATE_RE.search(text)
    if not match:
        return None
    s = re.sub(r"(?<=\d)(?:st|nd|rd|th)\b", "", match.group(0))
    s = " ".join(s.replace(",", " ").replace(".", " ").split())
    s = re.sub(r"\bSept\b", "Sep", s)
    for fmt in ("%Y-%m-%d", "%B %d %Y", "%b %d %Y", "%d %B %Y", "%d %b %Y"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    for fmt in ("%B %Y", "%b %Y"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m")
        except ValueError:
            pass
    return None


def dates_in_text(text: str) -> Set[str]:
    """All valid ISO dates mentioned in `text`."""
    found = set()
    for m in DATE_RE.finditer(text or ""):
        iso = parse_date(m.group(0))
        if iso:
            found.add(iso)
    return found


def normalize_name(name: str, etype: Optional[EntityType] = None) -> str:
    """Canonical comparison key for an entity name."""
    s = " ".join((name or "").split()).strip(" .,:;\"'")
    s = _ARTICLE_RE.sub("", s)
    if etype == EntityType.PERSON:
        while _TITLE_RE.match(s):
            s = _TITLE_RE.sub("", s, count=1)
    return normalize_text(s)


def clean_display_name(name: str) -> str:
    """Tidy a name for display (collapse spaces, drop leading 'The', trailing punctuation)."""
    s = " ".join((name or "").split()).strip(" ,:;\"'")
    s = s.rstrip(".") if not re.search(r"\b[A-Z]\.$", s) else s
    stripped = _ARTICLE_RE.sub("", s)
    return stripped or s


def make_entity_id(etype: EntityType, name: str, date_iso: Optional[str] = None) -> str:
    if etype == EntityType.DATE and date_iso:
        return f"DATE:{date_iso}"
    return f"{etype.value}:{normalize_name(name, etype)}"


def text_supports(name: str, text: str, threshold: float = 0.6) -> bool:
    """True if enough of the name's content words occur in the source text."""
    tokens = [t for t in normalize_text(name).split() if t not in STOPWORDS]
    if not tokens:
        return False
    present = set(normalize_text(text).split())
    return sum(t in present for t in tokens) / len(tokens) >= threshold


def evidence_in_text(evidence: Optional[str], text: str) -> bool:
    """True if the quoted evidence really appears (near-verbatim) in the source text."""
    ne, nt = normalize_text(evidence or ""), normalize_text(text)
    if len(ne.split()) < 2:
        return False
    if ne in nt:
        return True
    match = SequenceMatcher(None, ne, nt, autojunk=False).find_longest_match(0, len(ne), 0, len(nt))
    return match.size / len(ne) >= 0.85


# --------------------------------------------------------------------------
# Chunking
# --------------------------------------------------------------------------
def _split_long(paragraph: str, max_chars: int) -> List[str]:
    pieces, buf = [], ""
    for sentence in re.split(r"(?<=[.!?])\s+", paragraph):
        while len(sentence) > max_chars:
            if buf:
                pieces.append(buf)
                buf = ""
            pieces.append(sentence[:max_chars])
            sentence = sentence[max_chars:]
        if buf and len(buf) + 1 + len(sentence) > max_chars:
            pieces.append(buf)
            buf = sentence
        else:
            buf = f"{buf} {sentence}".strip()
    if buf:
        pieces.append(buf)
    return pieces


def chunk_text(
    text: str,
    document_id: Optional[str],
    filename: Optional[str] = None,
    page: Optional[int] = None,
    max_chars: int = 1500,
) -> List[SourceChunk]:
    """Split text into chunks on paragraph boundaries. chunk_id is deterministic."""
    paragraphs: List[str] = []
    for p in re.split(r"\n\s*\n", text or ""):
        p = p.strip()
        if not p:
            continue
        paragraphs.extend(_split_long(p, max_chars) if len(p) > max_chars else [p])
    chunks: List[SourceChunk] = []
    buf = ""
    prefix = f"{document_id}-p{page}" if page is not None else f"{document_id}"

    def flush() -> None:
        nonlocal buf
        if buf.strip():
            chunks.append(
                SourceChunk(
                    text=buf.strip(),
                    document_id=document_id,
                    filename=filename,
                    page=page,
                    chunk_id=f"{prefix}-c{len(chunks) + 1}",
                )
            )
        buf = ""

    for p in paragraphs:
        if buf and len(buf) + 2 + len(p) > max_chars:
            flush()
        buf = f"{buf}\n\n{p}" if buf else p
    flush()
    return chunks


def iter_document_chunks(document: SourceDocument, max_chars: int = 1500) -> List[SourceChunk]:
    """Chunk a SourceDocument; page numbers are only set when `pages` was given."""
    chunks: List[SourceChunk] = []
    if document.pages is not None:
        for number, page_text in enumerate(document.pages, start=1):
            chunks.extend(chunk_text(page_text, document.document_id, document.filename, number, max_chars))
    else:
        chunks.extend(chunk_text(document.text or "", document.document_id, document.filename, None, max_chars))
    return chunks


# --------------------------------------------------------------------------
# Validation of raw model output
# --------------------------------------------------------------------------
def _short_error(exc: ValidationError) -> str:
    parts = []
    for err in exc.errors()[:3]:
        loc = ".".join(str(x) for x in err.get("loc", ()))
        parts.append(f"{loc}: {err.get('msg')}")
    return "; ".join(parts)


def validate_extraction_payload(
    data: Any,
) -> Tuple[List[RawEntity], List[RawRelationship], List[str]]:
    """Validate a model payload item by item. Bad items are skipped and reported."""
    errors: List[str] = []
    if not isinstance(data, dict):
        return [], [], ["payload is not a JSON object"]
    raw_entities = data.get("entities")
    raw_relations = data.get("relationships", data.get("relations"))
    if raw_entities is None:
        errors.append("payload has no 'entities' list")
        raw_entities = []
    if raw_relations is None:
        raw_relations = []
    if not isinstance(raw_entities, list):
        errors.append("'entities' is not a list")
        raw_entities = []
    if not isinstance(raw_relations, list):
        errors.append("'relationships' is not a list")
        raw_relations = []
    entities: List[RawEntity] = []
    for i, item in enumerate(raw_entities):
        try:
            entities.append(RawEntity.model_validate(item))
        except ValidationError as exc:
            errors.append(f"entities[{i}] invalid: {_short_error(exc)}")
    relationships: List[RawRelationship] = []
    for i, item in enumerate(raw_relations):
        try:
            relationships.append(RawRelationship.model_validate(item))
        except ValidationError as exc:
            errors.append(f"relationships[{i}] invalid: {_short_error(exc)}")
    return entities, relationships, errors


# --------------------------------------------------------------------------
# Provenance merging
# --------------------------------------------------------------------------
def _dedupe_provenance(items: Sequence[Provenance]) -> List[Provenance]:
    seen, out = set(), []
    for p in items:
        if p.key() not in seen:
            seen.add(p.key())
            out.append(p)
    return out


def _merge_entity(target: Entity, other: Entity) -> None:
    """Merge `other` into `target` in place."""
    if other.name != target.name:
        if len(other.name) > len(target.name) and normalize_name(other.name, other.type) == normalize_name(
            target.name, target.type
        ):
            if target.name not in target.aliases:
                target.aliases.append(target.name)
            target.name = other.name
        elif other.name not in target.aliases:
            target.aliases.append(other.name)
    for alias in other.aliases:
        if alias != target.name and alias not in target.aliases:
            target.aliases.append(alias)
    target.description = target.description or other.description
    target.date_iso = target.date_iso or other.date_iso
    target.provenance = _dedupe_provenance(list(target.provenance) + list(other.provenance))


# --------------------------------------------------------------------------
# Per-chunk builder (grounding + normalization)
# --------------------------------------------------------------------------
class _ChunkBuilder:
    def __init__(self, chunk: SourceChunk, mode: str, cfg: Config) -> None:
        self.chunk, self.mode, self.cfg = chunk, mode, cfg
        self.entities: Dict[str, Entity] = {}
        self.relationships: List[Relationship] = []
        self.errors: List[str] = []
        self.warnings: List[str] = []
        self.chunk_dates = dates_in_text(chunk.text)

    def _prov(self, evidence: Optional[str]) -> Provenance:
        c = self.chunk
        return Provenance(
            document_id=c.document_id, filename=c.filename, page=c.page,
            chunk_id=c.chunk_id, evidence=evidence, mode=self.mode,
        )

    def _verified_evidence(self, evidence: Optional[str], label: str) -> Optional[str]:
        if not evidence:
            return None
        if evidence_in_text(evidence, self.chunk.text):
            return evidence
        self.warnings.append(f"{label}: evidence quote not found in source text; ignored")
        return None

    def _verified_date(self, value: Optional[str], label: str) -> Optional[str]:
        if not value:
            return None
        iso = parse_date(value)
        if iso is None or iso not in self.chunk_dates:
            self.warnings.append(f"{label}: date '{value}' not found in source text; ignored")
            return None
        return iso

    def add_entity(self, raw: RawEntity) -> Optional[Entity]:
        label = f"entity '{raw.name}'"
        aliases: List[str] = []
        date_iso: Optional[str] = None
        if raw.type == EntityType.DATE:
            iso = parse_date(raw.name)
            if iso is None:
                self.errors.append(f"{label}: unparseable date; dropped")
                return None
            if iso not in self.chunk_dates:
                self.errors.append(f"{label}: date not found in source text; dropped")
                return None
            name, date_iso = iso, iso
            if raw.name != iso:
                aliases.append(raw.name)
        else:
            if not text_supports(raw.name, self.chunk.text):
                self.errors.append(f"{label}: not supported by source text; dropped")
                return None
            name = clean_display_name(raw.name)
            date_iso = self._verified_date(raw.date, label)
        evidence = self._verified_evidence(raw.evidence, label)
        entity = Entity(
            id=make_entity_id(raw.type, name, date_iso),
            name=name,
            type=raw.type,
            aliases=aliases,
            date_iso=date_iso,
            description=raw.description,
            provenance=[self._prov(evidence)],
        )
        if entity.id in self.entities:
            _merge_entity(self.entities[entity.id], entity)
        else:
            self.entities[entity.id] = entity
        return self.entities[entity.id]

    def _find(self, name: str, hint: Optional[EntityType]) -> Optional[Entity]:
        for ent in self.entities.values():
            if hint and ent.type != hint:
                continue
            key = normalize_name(name, ent.type)
            if key and key in {normalize_name(x, ent.type) for x in [ent.name] + ent.aliases}:
                return ent
        return None

    def resolve(self, name: str, hint: Optional[EntityType]) -> Optional[Entity]:
        if DATE_RE.fullmatch(name.strip()):
            iso = parse_date(name)
            if iso and f"DATE:{iso}" in self.entities:
                return self.entities[f"DATE:{iso}"]
            return self.add_entity(RawEntity(name=name, type=EntityType.DATE))
        found = self._find(name, hint)
        if found:
            return found
        if hint and hint != EntityType.DATE and text_supports(name, self.chunk.text):
            return self.add_entity(RawEntity(name=name, type=hint))
        return None

    def add_relationship(self, raw: RawRelationship) -> None:
        label = f"relationship '{raw.source}' -{raw.relation.value}-> '{raw.target}'"
        src = self.resolve(raw.source, raw.source_type)
        tgt = self.resolve(raw.target, raw.target_type)
        if src is None or tgt is None:
            self.errors.append(f"{label}: endpoint not found among extracted entities; dropped")
            return
        if src.id == tgt.id:
            self.errors.append(f"{label}: self-loop; dropped")
            return
        flip = fix_direction(raw.relation, src.type, tgt.type)
        if flip is None:
            self.errors.append(
                f"{label}: incompatible entity types ({src.type.value} -> {tgt.type.value}); dropped"
            )
            return
        if flip:
            src, tgt = tgt, src
            self.warnings.append(f"{label}: direction corrected")
        evidence = self._verified_evidence(raw.evidence, label)
        if evidence is None and self.cfg.require_evidence:
            self.errors.append(f"{label}: no verifiable evidence in source text; dropped")
            return
        self.relationships.append(
            Relationship(
                source_id=src.id,
                target_id=tgt.id,
                relation=raw.relation,
                date_iso=self._verified_date(raw.date, label),
                provenance=[self._prov(evidence)],
            )
        )


# --------------------------------------------------------------------------
# MOCK extractor (rule-based; NOT an AI model)
# --------------------------------------------------------------------------
_ABBR = re.compile(r"\b(Dr|Prof|Mr|Mrs|Ms|Shri|Smt|St|No)\.")
_PERSON_RE = re.compile(r"\b(?:Dr|Prof|Mr|Mrs|Ms|Shri|Smt)\.? [A-Z][a-z]+(?: [A-Z][a-z]+)*")
_BODY_RE = re.compile(
    r"\b(?:(?:[A-Z][A-Za-z&]+ )*Board of Governors"
    r"|(?:[A-Z][A-Za-z&]+ )+(?:Council|Committee|Senate|Department(?! of\b))"
    r"|Department of [A-Z][A-Za-z&]+(?: [A-Z][A-Za-z&]+)*)\b"
)
_ORG_RE = re.compile(r"\b(?:[A-Z][a-z]+ )+(?:College|University|Institute)\b")
_MEET_RE = re.compile(r"\b(?:met|convened|held (?:a|its) meeting)\b")
_DECISION_RE = re.compile(
    r"\b(?P<verb>approved|ratified|endorsed|rejected|deferred|proposed)\s+(?P<obj>.+?)"
    r"(?=\s+(?:on|because|due to|owing to|as|by|after|during|at|recommended)\b|[,;.]|$)"
)
_REASON_RE = re.compile(r"\b(?:because|due to|owing to)\s+(?P<reason>.+?)\s*(?:[;.]|$)")
_ACTION_RE = re.compile(
    r"\b(?:was|is|were|are)\s+(?:tasked with|tasked to|assigned to|responsible for|directed to|"
    r"asked to|requested to)\s+"
)
_VERB_REL = {
    "approved": "APPROVED_BY", "ratified": "APPROVED_BY", "endorsed": "APPROVED_BY",
    "rejected": "REJECTED_BY", "deferred": "DEFERRED_BY", "proposed": "PROPOSED_BY",
}
_VAGUE_OBJECTS = {"it", "this", "that", "them", "these", "those", "proposal", "motion",
                  "resolution", "recommendation", "plan", "request"}


def _split_sentences(text: str) -> List[str]:
    out: List[str] = []
    for para in re.split(r"\n\s*\n", text):
        para = " ".join(para.split())
        if not para:
            continue
        protected = _ABBR.sub(lambda m: m.group(1) + "\x00", para)
        for sent in re.split(r"(?<=[.!?])\s+(?=[A-Z0-9\"'])", protected):
            sent = sent.replace("\x00", ".").strip()
            if sent:
                out.append(sent)
    return out


def _clean_decision_object(obj: str) -> str:
    s = obj.strip(" ,.;")
    for _ in range(3):
        n = re.sub(r"^(?:the|a|an)\s+", "", s, flags=re.IGNORECASE)
        n = re.sub(r"^(?:proposal|proposed|recommendation|motion|resolution|plan)\s+(?:to|for|of|on)\s+",
                   "", n, flags=re.IGNORECASE)
        n = re.sub(r"^(?:introduction|establishment|creation|launch)\s+of\s+", "", n, flags=re.IGNORECASE)
        if n == s:
            break
        s = n
    return s.strip()


def mock_extract_payload(text: str) -> Dict[str, Any]:
    """Rule-based stand-in for Gemma. Returns the same JSON shape as the real model.

    It only understands simple active-voice minutes ("X approved Y on DATE because Z").
    It exists for testing the pipeline; its output is labelled mode="mock".
    """
    entities: List[Dict[str, Any]] = []
    relationships: List[Dict[str, Any]] = []
    seen: Set[Tuple[str, str]] = set()
    meetings: Dict[Tuple[str, Optional[str]], str] = {}
    last_meeting: Optional[Tuple[str, str]] = None  # (meeting name, body key)
    last_decision: Optional[str] = None

    def add_entity(name: str, etype: str, evidence: str) -> None:
        key = (etype, normalize_name(name, EntityType(etype)))
        if key not in seen:
            seen.add(key)
            entities.append({"name": name, "type": etype, "evidence": evidence})

    def add_rel(src: str, rel: str, tgt: str, evidence: str, date: Optional[str] = None) -> None:
        relationships.append(
            {"source": src, "relation": rel, "target": tgt, "evidence": evidence, "date": date}
        )

    def body_type(name: str) -> str:
        return "DEPARTMENT" if "Department" in name else "COMMITTEE"

    for sent in _split_sentences(text):
        low = sent.lower()
        persons = [(m.start(), m.group(0)) for m in _PERSON_RE.finditer(sent)]
        bodies = [(m.start(), m.group(0)) for m in _BODY_RE.finditer(sent)]
        orgs = [m.group(0) for m in _ORG_RE.finditer(sent)]
        dates = [m.group(0) for m in DATE_RE.finditer(sent)]
        for _, p in persons:
            add_entity(p, "PERSON", sent)
        for _, b in bodies:
            add_entity(b, body_type(b), sent)
        for o in orgs:
            add_entity(o, "ORGANIZATION", sent)
        for d in dates:
            add_entity(d, "DATE", sent)
        for _, b in bodies:
            for o in orgs:
                if re.search(re.escape(b) + r"\s+of\s+" + re.escape(o), sent):
                    add_rel(b, "PART_OF", o, sent)
        candidates = sorted(persons + bodies)

        # meetings
        if bodies and dates and _MEET_RE.search(sent):
            body, date = bodies[0][1], dates[0]
            m_name = f"{clean_display_name(body)} meeting on {date}"
            add_entity(m_name, "MEETING", sent)
            add_rel(m_name, "HELD_ON", date, sent)
            add_rel(body, "CONVENED", m_name, sent)
            body_key = normalize_name(body, EntityType.COMMITTEE)
            meetings[(body_key, parse_date(date))] = m_name
            last_meeting = (m_name, body_key)
        if last_meeting and persons:
            if "chaired" in low:
                add_rel(persons[0][1], "CHAIRED", last_meeting[0], sent)
            if re.search(r"\b(?:attended|attendees|present|participated)\b", low):
                for _, p in persons:
                    add_rel(p, "ATTENDED", last_meeting[0], sent)
        if persons and bodies and re.search(r"\bmember of\b", low):
            add_rel(persons[0][1], "MEMBER_OF", bodies[0][1], sent)

        # decisions
        dm = _DECISION_RE.search(sent)
        if dm:
            obj = _clean_decision_object(dm.group("obj"))
            before = [c for c in candidates if c[0] < dm.start()]
            ok = 3 <= len(obj) <= 120 and obj.lower() not in _VAGUE_OBJECTS and before
            if ok:
                verb = dm.group("verb").lower()
                actor_name = before[-1][1]
                date = dates[0] if dates else None
                add_entity(obj, "DECISION", sent)
                add_rel(obj, _VERB_REL[verb], actor_name, sent, date)
                if verb != "proposed":
                    if date:
                        add_rel(obj, "DECIDED_ON", date, sent, date)
                    if before[-1] in bodies:
                        a_key = normalize_name(actor_name, EntityType.COMMITTEE)
                        m_name = (
                            meetings.get((a_key, parse_date(date)))
                            if date
                            else (last_meeting[0] if last_meeting and last_meeting[1] == a_key else None)
                        )
                        if m_name:
                            add_rel(obj, "DECIDED_AT", m_name, sent)
                rm = _REASON_RE.search(sent)
                if rm and 3 <= len(rm.group("reason")) <= 250:
                    reason = rm.group("reason").strip(" .;")
                    add_entity(reason, "REASON", sent)
                    add_rel(obj, "JUSTIFIED_BY", reason, sent)
                last_decision = obj

        # actions
        am = _ACTION_RE.search(sent)
        if am:
            before = [c for c in candidates if c[0] < am.start()]
            act = sent[am.end():].rstrip(" .;")
            due = None
            due_match = re.search(r"\s+by\s+(" + DATE_PATTERN + r")\s*$", act)
            if due_match:
                due = due_match.group(1)
                act = act[: due_match.start()]
            if before and 3 <= len(act) <= 200:
                add_entity(act, "ACTION", sent)
                add_rel(act, "ASSIGNED_TO", before[-1][1], sent)
                if due:
                    add_rel(act, "DUE_ON", due, sent)
                if last_decision and re.search(r"\b(?:this|the) decision\b|\bto implement\b", low):
                    add_rel(last_decision, "LED_TO", act, sent)
    return {"entities": entities, "relationships": relationships}


# --------------------------------------------------------------------------
# Public extraction API
# --------------------------------------------------------------------------
def extract_from_chunk(
    chunk: SourceChunk,
    llm: Optional[LLMService] = None,
    config: Optional[Config] = None,
) -> ExtractionResult:
    """Extract, validate and normalize knowledge from one chunk. Never raises for model problems."""
    llm = llm or LLMService(config or load_config())
    cfg = config or llm.config
    result = ExtractionResult(document_id=chunk.document_id, mode=llm.mode, chunks_processed=1,
                              model=None if llm.is_mock else cfg.model)
    if not (chunk.text or "").strip():
        result.warnings.append("empty chunk skipped")
        return result
    if llm.is_mock:
        data: Any = mock_extract_payload(chunk.text)
    else:
        try:
            data = llm.generate_json(build_extraction_prompt(chunk), system=EXTRACTION_SYSTEM_PROMPT)
        except LLMUnavailableError as exc:
            result.errors.append(f"LLM unavailable: {exc}")
            result.chunks_failed, result.llm_unavailable = 1, True
            return result
        except LLMError as exc:
            result.errors.append(f"LLM failure on chunk {chunk.chunk_id}: {exc}")
            result.chunks_failed = 1
            return result
    raw_entities, raw_relations, errors = validate_extraction_payload(data)
    builder = _ChunkBuilder(chunk, llm.mode, cfg)
    for raw in raw_entities:
        builder.add_entity(raw)
    for raw in raw_relations:
        builder.add_relationship(raw)
    result.entities = list(builder.entities.values())
    result.relationships = builder.relationships
    result.errors = errors + builder.errors
    result.warnings = builder.warnings
    return result


def extract_document(
    document: Union[SourceDocument, Dict[str, Any]],
    llm: Optional[LLMService] = None,
    config: Optional[Config] = None,
) -> ExtractionResult:
    """Chunk a document, extract every chunk and return one merged, deduplicated result.

    If Ollama is unavailable, extraction stops early and the result has
    llm_unavailable=True with an explanatory error (no exception is raised).
    """
    if isinstance(document, dict):
        document = SourceDocument.model_validate(document)
    llm = llm or LLMService(config or load_config())
    results: List[ExtractionResult] = []
    for chunk in iter_document_chunks(document, (config or llm.config).chunk_max_chars):
        res = extract_from_chunk(chunk, llm=llm, config=config)
        results.append(res)
        if res.llm_unavailable:
            break
    if not results:
        return ExtractionResult(document_id=document.document_id, mode=llm.mode,
                                warnings=["document has no text"])
    merged = merge_extractions(results)
    merged.document_id = document.document_id
    return merged


# --------------------------------------------------------------------------
# Merging / deduplication
# --------------------------------------------------------------------------
_DATED_TYPES = (EntityType.MEETING, EntityType.EVENT)


def _explicit_dates(entity: Entity) -> Set[str]:
    """Dates an entity states explicitly: in its name/aliases ('June 1, 2024') or in date_iso."""
    found: Set[str] = set()
    for text in [entity.name] + list(entity.aliases):
        found |= dates_in_text(text)
    if entity.date_iso:
        found.add(entity.date_iso)
    return found


def _dates_conflict(a: Entity, b: Entity) -> bool:
    """True if two entities must NOT be fuzzy-merged because of their dates.

    * Both state dates and none is shared -> conflict (June 1 vs June 15). A month ('2024-06') is
      compatible with a day inside it ('2024-06-01').
    * Only one states a date: for meetings/events that is also a conflict (we cannot tell whether
      they are the same meeting, and a wrong merge loses data); other types may still merge.
    * Neither states a date -> no conflict.
    """
    da, db = _explicit_dates(a), _explicit_dates(b)
    if da and db:
        return not any(x == y or x.startswith(y) or y.startswith(x) for x in da for y in db)
    if da or db:
        return a.type in _DATED_TYPES
    return False


def _fuzzy_remap(entities: Dict[str, Entity]) -> Dict[str, str]:
    """Map near-duplicate ids (same type, very similar names, compatible dates) onto one canonical id."""
    remap: Dict[str, str] = {}
    ids = sorted(entities)
    keys = {i: normalize_name(entities[i].name, entities[i].type) for i in ids}
    for a_idx, a in enumerate(ids):
        if a in remap or entities[a].type in (EntityType.DATE, EntityType.DOCUMENT):
            continue
        for b in ids[a_idx + 1:]:
            if b in remap or entities[b].type != entities[a].type:
                continue
            ka, kb = keys[a], keys[b]
            if min(len(ka), len(kb)) >= 8 and SequenceMatcher(None, ka, kb).ratio() >= 0.92:
                if _dates_conflict(entities[a], entities[b]):
                    continue
                remap[b] = a
    return remap


def merge_extractions(results: Sequence[ExtractionResult]) -> ExtractionResult:
    """Combine extraction results, deduplicating entities and relationships.

    Entities with the same type + normalized name (or a near-identical name)
    become one node; their provenance lists are merged.
    """
    results = list(results)
    entities: Dict[str, Entity] = {}
    for res in results:
        for ent in res.entities:
            if ent.id in entities:
                _merge_entity(entities[ent.id], ent)
            else:
                entities[ent.id] = ent.model_copy(deep=True)
    remap = _fuzzy_remap(entities)
    for old, new in remap.items():
        _merge_entity(entities[new], entities.pop(old))

    relationships: Dict[Tuple[str, str, str, Optional[str]], Relationship] = {}
    for res in results:
        for rel in res.relationships:
            s, t = remap.get(rel.source_id, rel.source_id), remap.get(rel.target_id, rel.target_id)
            if s == t or s not in entities or t not in entities:
                continue
            key = (s, rel.relation.value, t, rel.date_iso)
            if key in relationships:
                relationships[key].provenance = _dedupe_provenance(
                    relationships[key].provenance + rel.provenance
                )
            else:
                relationships[key] = Relationship(
                    source_id=s, target_id=t, relation=rel.relation, date_iso=rel.date_iso,
                    provenance=_dedupe_provenance(rel.provenance),
                )
    modes = {r.mode for r in results}
    models = {r.model for r in results if r.model}
    return ExtractionResult(
        document_id=results[0].document_id if len({r.document_id for r in results}) == 1 and results else None,
        entities=list(entities.values()),
        relationships=list(relationships.values()),
        errors=[e for r in results for e in r.errors],
        warnings=[w for r in results for w in r.warnings],
        mode=modes.pop() if len(modes) == 1 else ("mixed" if modes else "real"),
        model=models.pop() if len(models) == 1 else None,
        chunks_processed=sum(r.chunks_processed for r in results),
        chunks_failed=sum(r.chunks_failed for r in results),
        llm_unavailable=any(r.llm_unavailable for r in results),
    )
