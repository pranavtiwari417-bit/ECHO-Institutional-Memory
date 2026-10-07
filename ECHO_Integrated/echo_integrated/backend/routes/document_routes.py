"""
ECHO - Institutional Memory & Decision Intelligence Engine

File: backend/routes/document_routes.py
Purpose:
    Document management REST API.

Endpoints:
    GET    /api/documents
    GET    /api/documents/<id>
    POST   /api/documents
    PUT    /api/documents/<id>
    DELETE /api/documents/<id>
"""

from flask import Blueprint, jsonify, request
import sqlite3
import json
from pathlib import Path
from datetime import datetime


# ============================================================
# BLUEPRINT
# ============================================================

documents_bp = Blueprint("documents", __name__, url_prefix="/api/documents")


# ============================================================
# DATABASE PATH
# ============================================================

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATABASE_PATH = PROJECT_ROOT / "database" / "echo.db"


# ============================================================
# DATABASE CONNECTION
# ============================================================

def get_db_connection():
    """Create and return a SQLite database connection."""

    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(str(DATABASE_PATH))
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")

    return connection


# ============================================================
# TABLE INITIALIZATION
# ============================================================

def initialize_documents_table():
    """Create the documents table if it does not already exist."""

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
# ROW CONVERTER
# ============================================================

def document_to_dict(row):
    """Convert SQLite row into a JSON-compatible dictionary."""

    if row is None:
        return None

    try:
        metadata = json.loads(row["metadata"] or "{}")
    except (json.JSONDecodeError, TypeError):
        metadata = {}

    return {
        "id": row["id"],
        "filename": row["filename"],
        "title": row["title"],
        "content": row["content"],
        "file_path": row["file_path"],
        "file_type": row["file_type"],
        "created_at": row["created_at"],
        "metadata": metadata
    }


# ============================================================
# GET ALL DOCUMENTS
# ============================================================

@documents_bp.route("", methods=["GET"])
def get_documents():
    """
    Return all stored documents.

    Optional query parameter:
        ?limit=20
    """

    initialize_documents_table()

    try:
        limit = request.args.get("limit", default=50, type=int)

        if limit < 1:
            limit = 50

        # Prevent unnecessarily large requests.
        limit = min(limit, 500)

        connection = get_db_connection()

        rows = connection.execute(
            """
            SELECT id, filename, title, content,
                   file_path, file_type, created_at, metadata
            FROM documents
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,)
        ).fetchall()

        connection.close()

        documents = [document_to_dict(row) for row in rows]

        return jsonify({
            "success": True,
            "count": len(documents),
            "documents": documents
        }), 200

    except sqlite3.Error as error:
        return jsonify({
            "success": False,
            "error": f"Database error: {error}"
        }), 500


# ============================================================
# GET SINGLE DOCUMENT
# ============================================================

@documents_bp.route("/<int:document_id>", methods=["GET"])
def get_document(document_id):
    """Return a single document by ID."""

    initialize_documents_table()

    try:
        connection = get_db_connection()

        row = connection.execute(
            """
            SELECT id, filename, title, content,
                   file_path, file_type, created_at, metadata
            FROM documents
            WHERE id = ?
            """,
            (document_id,)
        ).fetchone()

        connection.close()

        if row is None:
            return jsonify({
                "success": False,
                "error": "Document not found."
            }), 404

        return jsonify({
            "success": True,
            "document": document_to_dict(row)
        }), 200

    except sqlite3.Error as error:
        return jsonify({
            "success": False,
            "error": f"Database error: {error}"
        }), 500


# ============================================================
# CREATE DOCUMENT
# ============================================================

@documents_bp.route("", methods=["POST"])
def create_document():
    """
    Create a document record.

    Expected JSON:

    {
        "filename": "meeting.pdf",
        "title": "Meeting Minutes",
        "content": "Meeting content...",
        "file_path": "uploads/meeting.pdf",
        "file_type": "pdf",
        "metadata": {
            "department": "CSE"
        }
    }
    """

    initialize_documents_table()

    data = request.get_json(silent=True)

    if not isinstance(data, dict):
        return jsonify({
            "success": False,
            "error": "Request body must contain valid JSON."
        }), 400

    filename = str(data.get("filename", "")).strip()

    if not filename:
        return jsonify({
            "success": False,
            "error": "filename is required."
        }), 400

    title = str(data.get("title", "")).strip()
    content = str(data.get("content", ""))
    file_path = str(data.get("file_path", ""))
    file_type = str(data.get("file_type", ""))

    metadata = data.get("metadata", {})

    if not isinstance(metadata, dict):
        metadata = {}

    created_at = datetime.now().isoformat(timespec="seconds")

    try:
        connection = get_db_connection()

        cursor = connection.execute(
            """
            INSERT INTO documents
            (
                filename,
                title,
                content,
                file_path,
                file_type,
                created_at,
                metadata
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                filename,
                title,
                content,
                file_path,
                file_type,
                created_at,
                json.dumps(metadata)
            )
        )

        connection.commit()

        document_id = cursor.lastrowid

        connection.close()

        return jsonify({
            "success": True,
            "message": "Document created successfully.",
            "document_id": document_id
        }), 201

    except sqlite3.Error as error:
        return jsonify({
            "success": False,
            "error": f"Database error: {error}"
        }), 500


# ============================================================
# UPDATE DOCUMENT
# ============================================================

@documents_bp.route("/<int:document_id>", methods=["PUT"])
def update_document(document_id):
    """Update an existing document."""

    initialize_documents_table()

    data = request.get_json(silent=True)

    if not isinstance(data, dict):
        return jsonify({
            "success": False,
            "error": "Request body must contain valid JSON."
        }), 400

    allowed_fields = {
        "filename",
        "title",
        "content",
        "file_path",
        "file_type",
        "metadata"
    }

    updates = {}
    parameters = []

    for field in allowed_fields:

        if field not in data:
            continue

        value = data[field]

        if field == "filename":
            value = str(value).strip()
            if not value:
                return jsonify({
                    "success": False,
                    "error": "filename cannot be empty."
                }), 400

        if field == "metadata":
            if not isinstance(value, dict):
                return jsonify({
                    "success": False,
                    "error": "metadata must be a JSON object."
                }), 400

            value = json.dumps(value)

        updates[field] = value

    if not updates:
        return jsonify({
            "success": False,
            "error": "No valid fields provided for update."
        }), 400

    try:
        connection = get_db_connection()

        # Check document exists.
        existing = connection.execute(
            "SELECT id FROM documents WHERE id = ?",
            (document_id,)
        ).fetchone()

        if existing is None:
            connection.close()

            return jsonify({
                "success": False,
                "error": "Document not found."
            }), 404

        set_clause = ", ".join(
            f"{field} = ?" for field in updates
        )

        parameters.extend(updates.values())
        parameters.append(document_id)

        connection.execute(
            f"""
            UPDATE documents
            SET {set_clause}
            WHERE id = ?
            """,
            parameters
        )

        connection.commit()
        connection.close()

        return jsonify({
            "success": True,
            "message": "Document updated successfully.",
            "document_id": document_id
        }), 200

    except sqlite3.Error as error:
        return jsonify({
            "success": False,
            "error": f"Database error: {error}"
        }), 500


# ============================================================
# DELETE DOCUMENT
# ============================================================

@documents_bp.route("/<int:document_id>", methods=["DELETE"])
def delete_document(document_id):
    """Delete a document record."""

    initialize_documents_table()

    try:
        connection = get_db_connection()

        cursor = connection.execute(
            """
            DELETE FROM documents
            WHERE id = ?
            """,
            (document_id,)
        )

        connection.commit()

        deleted = cursor.rowcount

        connection.close()

        if deleted == 0:
            return jsonify({
                "success": False,
                "error": "Document not found."
            }), 404

        return jsonify({
            "success": True,
            "message": "Document deleted successfully.",
            "document_id": document_id
        }), 200

    except sqlite3.Error as error:
        return jsonify({
            "success": False,
            "error": f"Database error: {error}"
        }), 500


# ============================================================
# INITIALIZE TABLE WHEN MODULE IS LOADED
# ============================================================

initialize_documents_table()
