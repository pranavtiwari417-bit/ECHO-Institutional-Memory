"""
ECHO - Query Routes

Handles user queries and connects:
Query -> Retrieval -> Response
"""

from flask import Blueprint, jsonify, request

from services.retrieval import retrieve


query_bp = Blueprint(
    "query",
    __name__,
    url_prefix="/api/query"
)


def validate_query(data):
    """Validate incoming query request."""

    if not isinstance(data, dict):
        return False, "Request body must contain valid JSON."

    query = data.get("query")

    if not query:
        return False, "Query is required."

    if not isinstance(query, str):
        return False, "Query must be a string."

    if not query.strip():
        return False, "Query cannot be empty."

    return True, ""


@query_bp.route("", methods=["POST"])
def process_query():
    """Process a natural-language user query."""

    data = request.get_json(silent=True)

    valid, error_message = validate_query(data)

    if not valid:
        return jsonify({
            "success": False,
            "error": error_message
        }), 400

    query = data["query"].strip()

    try:
        top_k = int(data.get("top_k", 5))
    except (TypeError, ValueError):
        top_k = 5

    top_k = max(1, min(top_k, 20))

    try:
        result = retrieve(
            query=query,
            top_k=top_k
        )

        return jsonify({
            "success": True,
            "query": query,
            "top_k": top_k,
            "message": "Query processed successfully.",

            "documents": result.get(
                "documents", []
            ),

            "entities": result.get(
                "entities", []
            ),

            "relationships": result.get(
                "relationships", []
            ),

            "decisions": result.get(
                "decisions", []
            ),

            "sources": result.get(
                "sources", []
            ),

            "graph_context": result.get(
                "graph_context", {}
            ),

            "context": result.get(
                "context_text", ""
            ),

            "answer": (
                "Relevant information retrieved successfully."
                if (
                    result.get("documents")
                    or result.get("entities")
                    or result.get("decisions")
                    or result.get("relationships")
                )
                else "Information was not found."
            )

        }), 200

    except Exception as error:

        return jsonify({
            "success": False,
            "error": "Query processing failed.",
            "details": str(error)
        }), 500


@query_bp.route("/health", methods=["GET"])
def query_health():
    """Health check for query service."""

    return jsonify({
        "success": True,
        "service": "query",
        "status": "healthy"
    }), 200