"""
ECHO - Institutional Memory & Decision Intelligence Engine

File: backend/routes/search_routes.py
Purpose:
    Search API for documents and institutional records.
"""

from flask import Blueprint, jsonify, request
import sqlite3
from pathlib import Path


# ============================================================
# BLUEPRINT
# ============================================================

search_bp = Blueprint(
    "search",
    __name__,
    url_prefix="/api/search"
)


# ============================================================
# DATABASE PATH
# ============================================================

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATABASE_PATH = PROJECT_ROOT / "database" / "echo.db"


# ============================================================
# DATABASE CONNECTION
# ============================================================

def get_db_connection():
    """Create a SQLite connection."""

    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(str(DATABASE_PATH))
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")

    return connection


# ============================================================
# TABLE INITIALIZATION
# ============================================================

def initialize_documents_table():
    """Ensure the documents table exists before searching."""
    connection = get_db_connection()
    try:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                filename TEXT NOT NULL,
                title TEXT DEFAULT '',
                content TEXT DEFAULT '',
                file_path TEXT DEFAULT '',
                file_type TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                metadata TEXT DEFAULT '{}'
            )
            """
        )
        connection.commit()
    finally:
        connection.close()


# ============================================================
# SEARCH DOCUMENTS
# ============================================================

@search_bp.route("", methods=["GET"])
def search_documents():
    """
    Search documents using filename, title, or content.

    Example:
        GET /api/search?q=meeting

    Optional:
        ?limit=20
    """

    initialize_documents_table()

    query = request.args.get("q", "").strip()

    if not query:
        return jsonify({
            "success": False,
            "error": "Search query 'q' is required."
        }), 400

    limit = request.args.get("limit", default=20, type=int)

    if limit is None or limit < 1:
        limit = 20

    limit = min(limit, 100)

    try:
        connection = get_db_connection()

        # Search across filename, title and content.
        search_pattern = f"%{query}%"

        rows = connection.execute(
            """
            SELECT
                id,
                filename,
                title,
                content,
                file_path,
                file_type,
                created_at
            FROM documents
            WHERE
                filename LIKE ?
                OR title LIKE ?
                OR content LIKE ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (
                search_pattern,
                search_pattern,
                search_pattern,
                limit
            )
        ).fetchall()

        connection.close()

        results = []

        for row in rows:
            content = row["content"] or ""

            # Return a small preview instead of the complete
            # document content.
            preview = content[:300]

            if len(content) > 300:
                preview += "..."

            results.append({
                "id": row["id"],
                "filename": row["filename"],
                "title": row["title"],
                "preview": preview,
                "file_path": row["file_path"],
                "file_type": row["file_type"],
                "created_at": row["created_at"]
            })

        return jsonify({
            "success": True,
            "query": query,
            "count": len(results),
            "results": results
        }), 200

    except sqlite3.Error as error:
        return jsonify({
            "success": False,
            "error": f"Database error: {error}"
        }), 500


# ============================================================
# SEARCH HEALTH CHECK
# ============================================================

@search_bp.route("/health", methods=["GET"])
def search_health():
    """Check whether the search API is available."""

    return jsonify({
        "success": True,
        "service": "search",
        "status": "available"
    }), 200
