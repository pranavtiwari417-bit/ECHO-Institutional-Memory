"""Prompt templates for Gemma (extraction and answer generation)."""

from .schemas import RELATION_RULES, EntityType, SourceChunk


def describe_relations() -> str:
    """One line per relation: NAME: SOURCE_TYPES -> TARGET_TYPES."""
    lines = []
    for rel, (src, tgt) in RELATION_RULES.items():
        s = "ANY" if src is None else "/".join(sorted(t.value for t in src))
        t = "ANY" if tgt is None else "/".join(sorted(t.value for t in tgt))
        lines.append(f"- {rel.value}: {s} -> {t}")
    return "\n".join(lines)


EXTRACTION_SYSTEM_PROMPT = f"""You extract institutional knowledge from meeting minutes and official documents.
Return ONE JSON object and nothing else.

ENTITY TYPES: {", ".join(t.value for t in EntityType)}

RELATION TYPES (direction is SOURCE -> TARGET):
{describe_relations()}

JSON FORMAT:
{{"entities": [{{"name": "...", "type": "PERSON", "date": null, "description": null, "evidence": "sentence copied from the text"}}],
 "relationships": [{{"source": "entity name", "relation": "APPROVED_BY", "target": "entity name", "date": null, "evidence": "sentence copied from the text"}}]}}

STRICT RULES:
1. Use ONLY facts stated in the text. Never invent people, dates, reasons or decisions.
2. Copy names and dates exactly as written in the text. For DATE entities, name = the date as written.
3. "evidence" MUST be a sentence copied word for word from the text.
4. Use "date" only for a date written in the text; otherwise null.
5. A DECISION is a short noun phrase (e.g. "BSc in Data Science program"), not a full sentence.
6. A REASON is the stated justification for a decision. An ACTION is a task assigned to someone.
7. Every relationship endpoint must also appear in "entities".
8. If there is nothing to extract, return {{"entities": [], "relationships": []}}.
"""

_EXTRACTION_EXAMPLE = """EXAMPLE TEXT:
The Library Committee met on January 9, 2023. The Library Committee approved the extension of library hours on January 9, 2023 because students requested evening access.
EXAMPLE OUTPUT:
{"entities": [
 {"name": "Library Committee", "type": "COMMITTEE", "evidence": "The Library Committee met on January 9, 2023."},
 {"name": "Library Committee meeting on January 9, 2023", "type": "MEETING", "evidence": "The Library Committee met on January 9, 2023."},
 {"name": "January 9, 2023", "type": "DATE", "evidence": "The Library Committee met on January 9, 2023."},
 {"name": "extension of library hours", "type": "DECISION", "evidence": "The Library Committee approved the extension of library hours on January 9, 2023 because students requested evening access."},
 {"name": "students requested evening access", "type": "REASON", "evidence": "The Library Committee approved the extension of library hours on January 9, 2023 because students requested evening access."}],
 "relationships": [
 {"source": "Library Committee", "relation": "CONVENED", "target": "Library Committee meeting on January 9, 2023", "evidence": "The Library Committee met on January 9, 2023."},
 {"source": "Library Committee meeting on January 9, 2023", "relation": "HELD_ON", "target": "January 9, 2023", "evidence": "The Library Committee met on January 9, 2023."},
 {"source": "extension of library hours", "relation": "APPROVED_BY", "target": "Library Committee", "date": "January 9, 2023", "evidence": "The Library Committee approved the extension of library hours on January 9, 2023 because students requested evening access."},
 {"source": "extension of library hours", "relation": "DECIDED_AT", "target": "Library Committee meeting on January 9, 2023", "evidence": "The Library Committee approved the extension of library hours on January 9, 2023 because students requested evening access."},
 {"source": "extension of library hours", "relation": "JUSTIFIED_BY", "target": "students requested evening access", "evidence": "The Library Committee approved the extension of library hours on January 9, 2023 because students requested evening access."}]}
"""


def build_extraction_prompt(chunk: SourceChunk) -> str:
    return (
        f"{_EXTRACTION_EXAMPLE}\n"
        "NOW EXTRACT FROM THIS SOURCE.\n"
        f"document_id: {chunk.document_id}\n"
        f"filename: {chunk.filename}\n"
        f"page: {chunk.page}\n"
        f"chunk_id: {chunk.chunk_id}\n"
        "TEXT:\n"
        f"{chunk.text}\n\n"
        "Return the JSON object only."
    )


ANSWER_SYSTEM_PROMPT = """You answer questions for a college decision-intelligence system.
Use ONLY the DECISION TRAIL and EVIDENCE provided. Do not use outside knowledge.
Return ONE JSON object and nothing else:
{"answer": "...", "sufficient_evidence": true, "used_sources": ["S1", "S2"]}

RULES:
1. Cite source labels like [S1] inside the answer for every claim.
2. List the labels you relied on in "used_sources".
3. If the evidence does not answer the question, set "sufficient_evidence" to false and say what is missing. Do not guess.
4. Never invent dates, names, reasons or decisions that are not in the evidence.
5. Be concise (2-5 sentences).
"""


def build_answer_prompt(question: str, trail_text: str, evidence_text: str) -> str:
    return (
        f"QUESTION:\n{question}\n\n"
        f"DECISION TRAIL (chronological, from the knowledge graph):\n{trail_text or '(none)'}\n\n"
        f"EVIDENCE (numbered sources):\n{evidence_text or '(none)'}\n\n"
        "Return the JSON object only."
    )
