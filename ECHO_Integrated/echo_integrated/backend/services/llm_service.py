"""
ECHO - Institutional Memory & Decision Intelligence Engine

File: backend/services/llm_service.py
Purpose:
    Local LLM service using Ollama.
"""

import json
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional


# ============================================================
# CONFIGURATION
# ============================================================

OLLAMA_URL = "http://127.0.0.1:11434"
OLLAMA_GENERATE_URL = f"{OLLAMA_URL}/api/generate"

# Change this only if a different Ollama model is installed.
DEFAULT_MODEL = "gemma3:4b"

REQUEST_TIMEOUT = 120


# ============================================================
# OLLAMA REQUEST
# ============================================================

def _ollama_request(
    prompt: str,
    model: str = DEFAULT_MODEL,
    temperature: float = 0.2
) -> Optional[str]:
    """
    Send a prompt to the local Ollama server.

    Returns:
        Generated text if successful.
        None if Ollama is unavailable or request fails.
    """

    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": temperature
        }
    }

    data = json.dumps(payload).encode("utf-8")

    request = urllib.request.Request(
        OLLAMA_GENERATE_URL,
        data=data,
        headers={
            "Content-Type": "application/json"
        },
        method="POST"
    )

    try:
        with urllib.request.urlopen(
            request,
            timeout=REQUEST_TIMEOUT
        ) as response:

            response_data = response.read().decode("utf-8")

            result = json.loads(response_data)

            return result.get("response", "").strip()

    except (
        urllib.error.URLError,
        urllib.error.HTTPError,
        TimeoutError,
        json.JSONDecodeError,
        OSError,
        Exception
    ):
        return None


# ============================================================
# HEALTH CHECK
# ============================================================

def is_ollama_available() -> bool:
    """
    Check whether the local Ollama server is running.
    """

    request = urllib.request.Request(
        OLLAMA_URL,
        method="GET"
    )

    try:
        with urllib.request.urlopen(
            request,
            timeout=5
        ) as response:

            return response.status == 200

    except (
        urllib.error.URLError,
        urllib.error.HTTPError,
        TimeoutError,
        OSError,
        Exception
    ):
        return False


# ============================================================
# MODEL CHECK
# ============================================================

def is_model_available(
    model: str = DEFAULT_MODEL
) -> bool:
    """
    Check whether the requested model is available in Ollama.
    """

    request = urllib.request.Request(
        f"{OLLAMA_URL}/api/tags",
        method="GET"
    )

    try:
        with urllib.request.urlopen(
            request,
            timeout=5
        ) as response:

            data = json.loads(
                response.read().decode("utf-8")
            )

            models = data.get("models", [])

            for item in models:
                model_name = item.get("name", "")

                if model_name == model:
                    return True

            return False

    except (
        urllib.error.URLError,
        urllib.error.HTTPError,
        TimeoutError,
        json.JSONDecodeError,
        OSError,
        Exception
    ):
        return False


# ============================================================
# GENERATE TEXT
# ============================================================

def generate_text(
    prompt: str,
    model: str = DEFAULT_MODEL,
    temperature: float = 0.2
) -> str:
    """
    Generate text using the local Ollama model.
    """

    if not prompt or not prompt.strip():
        return "Please provide a valid prompt."

    response = _ollama_request(
        prompt=prompt.strip(),
        model=model,
        temperature=temperature
    )

    if response is None:
        return (
            "Local AI service is currently unavailable. "
            "Please make sure Ollama is running."
        )

    return response


# ============================================================
# CONTEXT FORMATTER
# ============================================================

def format_context(
    documents: Optional[List[Dict[str, Any]]] = None,
    entities: Optional[List[Dict[str, Any]]] = None,
    relationships: Optional[List[Dict[str, Any]]] = None,
    decisions: Optional[List[Dict[str, Any]]] = None
) -> str:
    """
    Convert retrieved ECHO data into LLM-readable context.
    """

    documents = documents or []
    entities = entities or []
    relationships = relationships or []
    decisions = decisions or []

    sections = []

    # --------------------------------------------------------
    # Documents
    # --------------------------------------------------------
    if documents:
        document_text = ["DOCUMENTS:"]

        for index, document in enumerate(documents, start=1):
            title = document.get("title", "")
            filename = document.get("filename", "")
            content = document.get("content", "")

            document_text.append(
                f"\nDocument {index}:"
                f"\nFilename: {filename}"
                f"\nTitle: {title}"
                f"\nContent: {content}"
            )

        sections.append("\n".join(document_text))

    # --------------------------------------------------------
    # Entities
    # --------------------------------------------------------
    if entities:
        entity_text = ["ENTITIES:"]

        for entity in entities:
            entity_text.append(
                f"- {entity.get('name', '')} "
                f"({entity.get('entity_type', '')})"
            )

        sections.append("\n".join(entity_text))

    # --------------------------------------------------------
    # Relationships
    # --------------------------------------------------------
    if relationships:
        relationship_text = ["RELATIONSHIPS:"]

        for relationship in relationships:
            relationship_text.append(
                f"- "
                f"{relationship.get('source_entity', '')} "
                f"--[{relationship.get('relation', '')}]--> "
                f"{relationship.get('target_entity', '')}"
            )

        sections.append("\n".join(relationship_text))

    # --------------------------------------------------------
    # Decisions
    # --------------------------------------------------------
    if decisions:
        decision_text = ["DECISIONS:"]

        for decision in decisions:
            decision_text.append(
                f"\nDecision: {decision.get('title', '')}"
                f"\nDescription: {decision.get('description', '')}"
                f"\nReason: {decision.get('reason', '')}"
                f"\nDate: {decision.get('date', '')}"
                f"\nMeeting: {decision.get('meeting', '')}"
            )

        sections.append("\n".join(decision_text))

    if not sections:
        return "No relevant institutional context was retrieved."

    return "\n\n".join(sections)


# ============================================================
# ECHO QUESTION ANSWERING
# ============================================================

def answer_query(
    query: str,
    context: str,
    model: str = DEFAULT_MODEL
) -> str:
    """
    Generate an answer to a user query using retrieved
    institutional context.
    """

    if not query or not query.strip():
        return "Please provide a valid query."

    if not context or not context.strip():
        context = "No relevant context was found."

    prompt = f"""
You are ECHO, an offline institutional memory and
decision intelligence assistant.

Answer the user's question using ONLY the provided
institutional context.

Rules:
1. Do not invent facts.
2. Do not use information outside the provided context.
3. If the answer is not present in the context, clearly say
   that the information was not found.
4. Keep the answer clear and concise.
5. Mention relevant documents, people, meetings, decisions,
   or relationships when supported by the context.
6. For decisions, explain the reason only when it is present
   in the provided context.

USER QUERY:
{query}

INSTITUTIONAL CONTEXT:
{context}

ANSWER:
"""

    return generate_text(
        prompt=prompt,
        model=model,
        temperature=0.1
    )


# ============================================================
# SUMMARIZATION
# ============================================================

def summarize_text(
    text: str,
    model: str = DEFAULT_MODEL
) -> str:
    """
    Summarize institutional text.
    """

    if not text or not text.strip():
        return "No text was provided."

    prompt = f"""
Summarize the following institutional document.

Focus on:
- Main topic
- Important people or entities
- Meetings
- Decisions
- Reasons
- Important actions
- Key facts

Do not invent information.

DOCUMENT:
{text}

SUMMARY:
"""

    return generate_text(
        prompt=prompt,
        model=model,
        temperature=0.2
    )


def _parse_json_list(text: str) -> List[Any]:
    """
    Robustly extract and parse a JSON list from LLM output.
    """
    if not text or not text.strip():
        return []

    cleaned = text.strip()

    # If code fence is present, extract contents between fences
    if "```" in cleaned:
        parts = cleaned.split("```")
        for part in parts:
            part = part.strip()
            if part.startswith("json"):
                part = part[4:].strip()
            if part.startswith("[") and part.endswith("]"):
                cleaned = part
                break

    # Strip any extra preamble or trailing text
    start = cleaned.find("[")
    end = cleaned.rfind("]")
    if start != -1 and end != -1 and end > start:
        cleaned = cleaned[start:end + 1]

    try:
        result = json.loads(cleaned)
        if isinstance(result, list):
            return result
        return []
    except (json.JSONDecodeError, TypeError):
        return []


# ============================================================
# ENTITY EXTRACTION
# ============================================================

def extract_entities(
    text: str,
    model: str = DEFAULT_MODEL
) -> List[Dict[str, str]]:
    """
    Extract important entities from text.

    Expected entity types:
    PERSON, ORGANIZATION, MEETING, PROJECT,
    DECISION, DOCUMENT, DATE, LOCATION, OTHER
    """

    if not text or not text.strip():
        return []

    prompt = f"""
Extract important entities from the following institutional
document.

Return ONLY valid JSON.

Required format:
[
  {{
    "name": "entity name",
    "entity_type": "PERSON"
  }}
]

Allowed entity types:
PERSON
ORGANIZATION
MEETING
PROJECT
DECISION
DOCUMENT
DATE
LOCATION
OTHER

Do not add explanations outside JSON.

TEXT:
{text}
"""

    response = generate_text(
        prompt=prompt,
        model=model,
        temperature=0.0
    )

    result = _parse_json_list(response)

    valid_entities = []

    for item in result:
        if not isinstance(item, dict):
            continue

        name = str(item.get("name", "")).strip()
        entity_type = str(
            item.get("entity_type", "OTHER")
        ).strip()

        if name:
            valid_entities.append({
                "name": name,
                "entity_type": entity_type
            })

    return valid_entities


# ============================================================
# DECISION EXTRACTION
# ============================================================

def extract_decisions(
    text: str,
    model: str = DEFAULT_MODEL
) -> List[Dict[str, Any]]:
    """
    Extract decisions from institutional text.
    """

    if not text or not text.strip():
        return []

    prompt = f"""
Extract important decisions from the following institutional
document.

Return ONLY valid JSON.

Required format:
[
  {{
    "title": "decision title",
    "description": "what was decided",
    "reason": "why it was decided",
    "date": "",
    "meeting": ""
  }}
]

Do not invent missing information.
Use an empty string when a field is not available.

TEXT:
{text}
"""

    response = generate_text(
        prompt=prompt,
        model=model,
        temperature=0.0
    )

    result = _parse_json_list(response)

    return [
        item for item in result
        if isinstance(item, dict)
    ]


# ============================================================
# SERVICE STATUS
# ============================================================

def get_llm_status(
    model: str = DEFAULT_MODEL
) -> Dict[str, Any]:
    """
    Return current local LLM service status.
    """

    ollama_running = is_ollama_available()

    model_installed = False

    if ollama_running:
        model_installed = is_model_available(model)

    return {
        "ollama": ollama_running,
        "model": model,
        "model_available": model_installed,
        "offline": True
    }
