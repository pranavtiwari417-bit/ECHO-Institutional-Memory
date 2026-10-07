"""
ECHO - Institutional Memory & Decision Intelligence Engine

File: backend/services/database.py
Purpose:
    SQLite database management for ECHO.
"""

import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional


# ============================================================
# DATABASE PATH
# ============================================================

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATABASE_DIR = PROJECT_ROOT / "database"
DATABASE_PATH = DATABASE_DIR / "echo.db"


# ============================================================
# DATABASE CONNECTION
# ============================================================

def get_connection() -> sqlite3.Connection:
    """
    Create and return a SQLite database connection.
    """

    DATABASE_DIR.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(str(DATABASE_PATH))
    connection.row_factory = sqlite3.Row

    # Enable foreign-key constraints.
    connection.execute("PRAGMA foreign_keys = ON")

    return connection


# ============================================================
# DATABASE INITIALIZATION
# ============================================================

def initialize_database() -> None:
    """
    Create all ECHO database tables if they do not exist.
    """

    connection = get_connection()

    try:
        cursor = connection.cursor()

        # ----------------------------------------------------
        # Documents
        # ----------------------------------------------------
        cursor.execute(
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

        # ----------------------------------------------------
        # Entities
        # ----------------------------------------------------
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS entities (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                entity_type TEXT NOT NULL,
                document_id INTEGER,
                metadata TEXT DEFAULT '{}',

                FOREIGN KEY (document_id)
                    REFERENCES documents(id)
                    ON DELETE CASCADE
            )
            """
        )

        # ----------------------------------------------------
        # Relationships
        # ----------------------------------------------------
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS relationships (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_entity TEXT NOT NULL,
                relation TEXT NOT NULL,
                target_entity TEXT NOT NULL,
                document_id INTEGER,
                metadata TEXT DEFAULT '{}',

                FOREIGN KEY (document_id)
                    REFERENCES documents(id)
                    ON DELETE CASCADE
            )
            """
        )

        # ----------------------------------------------------
        # Decisions
        # ----------------------------------------------------
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS decisions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                description TEXT DEFAULT '',
                reason TEXT DEFAULT '',
                date TEXT,
                meeting TEXT,
                document_id INTEGER,
                metadata TEXT DEFAULT '{}',

                FOREIGN KEY (document_id)
                    REFERENCES documents(id)
                    ON DELETE SET NULL
            )
            """
        )

        # ----------------------------------------------------
        # Sources / Evidence
        # ----------------------------------------------------
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS sources (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                document_id INTEGER,
                filename TEXT DEFAULT '',
                page_number INTEGER,
                text TEXT DEFAULT '',
                source_type TEXT DEFAULT 'document',
                metadata TEXT DEFAULT '{}',

                FOREIGN KEY (document_id)
                    REFERENCES documents(id)
                    ON DELETE CASCADE
            )
            """
        )

        # ----------------------------------------------------
        # Useful indexes for faster searching.
        # ----------------------------------------------------
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_documents_filename
            ON documents(filename)
            """
        )

        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_documents_title
            ON documents(title)
            """
        )

        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_entities_name
            ON entities(name)
            """
        )

        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_entities_type
            ON entities(entity_type)
            """
        )

        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_decisions_date
            ON decisions(date)
            """
        )

        connection.commit()

    finally:
        connection.close()


# ============================================================
# DOCUMENT FUNCTIONS
# ============================================================

def add_document(
    filename: str,
    title: str = "",
    content: str = "",
    file_path: str = "",
    file_type: str = "",
    created_at: str = "",
    metadata: Optional[Dict[str, Any]] = None
) -> int:
    """
    Insert a document and return its database ID.
    """

    if not filename or not filename.strip():
        raise ValueError("filename is required")

    if not created_at:
        from datetime import datetime
        created_at = datetime.now().isoformat(timespec="seconds")

    if metadata is None:
        metadata = {}

    connection = get_connection()

    try:
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
                filename.strip(),
                title,
                content,
                file_path,
                file_type,
                created_at,
                json.dumps(metadata)
            )
        )

        connection.commit()

        return cursor.lastrowid

    finally:
        connection.close()


def get_document(document_id: int) -> Optional[Dict[str, Any]]:
    """
    Retrieve one document by ID.
    """

    connection = get_connection()

    try:
        row = connection.execute(
            """
            SELECT *
            FROM documents
            WHERE id = ?
            """,
            (document_id,)
        ).fetchone()

        if row is None:
            return None

        return row_to_dict(row)

    finally:
        connection.close()


def get_all_documents(limit: int = 100) -> List[Dict[str, Any]]:
    """
    Retrieve documents from the database.
    """

    limit = max(1, min(int(limit), 500))

    connection = get_connection()

    try:
        rows = connection.execute(
            """
            SELECT *
            FROM documents
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,)
        ).fetchall()

        return [row_to_dict(row) for row in rows]

    finally:
        connection.close()


def search_documents(
    query: str,
    limit: int = 20
) -> List[Dict[str, Any]]:
    """
    Perform basic keyword search across documents.
    """

    query = query.strip()

    if not query:
        return []

    limit = max(1, min(int(limit), 100))
    pattern = f"%{query}%"

    connection = get_connection()

    try:
        rows = connection.execute(
            """
            SELECT *
            FROM documents
            WHERE
                filename LIKE ?
                OR title LIKE ?
                OR content LIKE ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (
                pattern,
                pattern,
                pattern,
                limit
            )
        ).fetchall()

        return [row_to_dict(row) for row in rows]

    finally:
        connection.close()


def update_document(
    document_id: int,
    filename: Optional[str] = None,
    title: Optional[str] = None,
    content: Optional[str] = None,
    file_path: Optional[str] = None,
    file_type: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None
) -> bool:
    """
    Update fields of an existing document. Returns True if updated, False otherwise.
    """
    updates = {}
    if filename is not None:
        if not filename.strip():
            raise ValueError("filename cannot be empty")
        updates["filename"] = filename.strip()
    if title is not None:
        updates["title"] = title
    if content is not None:
        updates["content"] = content
    if file_path is not None:
        updates["file_path"] = file_path
    if file_type is not None:
        updates["file_type"] = file_type
    if metadata is not None:
        updates["metadata"] = json.dumps(metadata)

    if not updates:
        return False

    connection = get_connection()
    try:
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        params = list(updates.values()) + [document_id]
        cursor = connection.execute(
            f"UPDATE documents SET {set_clause} WHERE id = ?",
            params
        )
        connection.commit()
        return cursor.rowcount > 0
    finally:
        connection.close()


def delete_document(document_id: int) -> bool:
    """
    Delete a document by ID. Returns True if deleted, False otherwise.
    """
    connection = get_connection()
    try:
        cursor = connection.execute(
            "DELETE FROM documents WHERE id = ?",
            (document_id,)
        )
        connection.commit()
        return cursor.rowcount > 0
    finally:
        connection.close()


# ============================================================
# ENTITY FUNCTIONS
# ============================================================

def add_entity(
    name: str,
    entity_type: str,
    document_id: Optional[int] = None,
    metadata: Optional[Dict[str, Any]] = None
) -> int:
    """
    Add an entity to the database.
    """

    if not name.strip():
        raise ValueError("Entity name is required.")

    if not entity_type.strip():
        raise ValueError("Entity type is required.")

    if metadata is None:
        metadata = {}

    connection = get_connection()

    try:
        cursor = connection.execute(
            """
            INSERT INTO entities
            (
                name,
                entity_type,
                document_id,
                metadata
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                name.strip(),
                entity_type.strip(),
                document_id,
                json.dumps(metadata)
            )
        )

        connection.commit()

        return cursor.lastrowid

    finally:
        connection.close()


def get_entities(
    document_id: Optional[int] = None
) -> List[Dict[str, Any]]:
    """
    Retrieve entities, optionally filtered by document.
    """

    connection = get_connection()

    try:
        if document_id is None:
            rows = connection.execute(
                """
                SELECT *
                FROM entities
                ORDER BY id DESC
                """
            ).fetchall()
        else:
            rows = connection.execute(
                """
                SELECT *
                FROM entities
                WHERE document_id = ?
                ORDER BY id DESC
                """,
                (document_id,)
            ).fetchall()

        return [row_to_dict(row) for row in rows]

    finally:
        connection.close()


# ============================================================
# RELATIONSHIP FUNCTIONS
# ============================================================

def add_relationship(
    source_entity: str,
    relation: str,
    target_entity: str,
    document_id: Optional[int] = None,
    metadata: Optional[Dict[str, Any]] = None
) -> int:
    """
    Add an entity relationship.
    """

    if not source_entity.strip():
        raise ValueError("source_entity is required.")

    if not relation.strip():
        raise ValueError("relation is required.")

    if not target_entity.strip():
        raise ValueError("target_entity is required.")

    if metadata is None:
        metadata = {}

    connection = get_connection()

    try:
        cursor = connection.execute(
            """
            INSERT INTO relationships
            (
                source_entity,
                relation,
                target_entity,
                document_id,
                metadata
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                source_entity.strip(),
                relation.strip(),
                target_entity.strip(),
                document_id,
                json.dumps(metadata)
            )
        )

        connection.commit()

        return cursor.lastrowid

    finally:
        connection.close()


def get_relationships(
    document_id: Optional[int] = None
) -> List[Dict[str, Any]]:
    """
    Retrieve relationships.
    """

    connection = get_connection()

    try:
        if document_id is None:
            rows = connection.execute(
                """
                SELECT *
                FROM relationships
                ORDER BY id DESC
                """
            ).fetchall()
        else:
            rows = connection.execute(
                """
                SELECT *
                FROM relationships
                WHERE document_id = ?
                ORDER BY id DESC
                """,
                (document_id,)
            ).fetchall()

        return [row_to_dict(row) for row in rows]

    finally:
        connection.close()


# ============================================================
# DECISION FUNCTIONS
# ============================================================

def add_decision(
    title: str,
    description: str = "",
    reason: str = "",
    date: Optional[str] = None,
    meeting: Optional[str] = None,
    document_id: Optional[int] = None,
    metadata: Optional[Dict[str, Any]] = None
) -> int:
    """
    Add a decision record.
    """

    if not title.strip():
        raise ValueError("Decision title is required.")

    if metadata is None:
        metadata = {}

    connection = get_connection()

    try:
        cursor = connection.execute(
            """
            INSERT INTO decisions
            (
                title,
                description,
                reason,
                date,
                meeting,
                document_id,
                metadata
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                title.strip(),
                description,
                reason,
                date,
                meeting,
                document_id,
                json.dumps(metadata)
            )
        )

        connection.commit()

        return cursor.lastrowid

    finally:
        connection.close()


def get_decisions(
    document_id: Optional[int] = None
) -> List[Dict[str, Any]]:
    """
    Retrieve decisions.
    """

    connection = get_connection()

    try:
        if document_id is None:
            rows = connection.execute(
                """
                SELECT *
                FROM decisions
                ORDER BY id DESC
                """
            ).fetchall()
        else:
            rows = connection.execute(
                """
                SELECT *
                FROM decisions
                WHERE document_id = ?
                ORDER BY id DESC
                """,
                (document_id,)
            ).fetchall()

        return [row_to_dict(row) for row in rows]

    finally:
        connection.close()


# ============================================================
# SOURCE FUNCTIONS
# ============================================================

def add_source(
    document_id: Optional[int],
    filename: str = "",
    page_number: Optional[int] = None,
    text: str = "",
    source_type: str = "document",
    metadata: Optional[Dict[str, Any]] = None
) -> int:
    """
    Add a source/evidence record.
    """

    if metadata is None:
        metadata = {}

    connection = get_connection()

    try:
        cursor = connection.execute(
            """
            INSERT INTO sources
            (
                document_id,
                filename,
                page_number,
                text,
                source_type,
                metadata
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                document_id,
                filename,
                page_number,
                text,
                source_type,
                json.dumps(metadata)
            )
        )

        connection.commit()

        return cursor.lastrowid

    finally:
        connection.close()


def get_sources(
    document_id: Optional[int] = None
) -> List[Dict[str, Any]]:
    """
    Retrieve source/evidence records.
    """

    connection = get_connection()

    try:
        if document_id is None:
            rows = connection.execute(
                """
                SELECT *
                FROM sources
                ORDER BY id DESC
                """
            ).fetchall()
        else:
            rows = connection.execute(
                """
                SELECT *
                FROM sources
                WHERE document_id = ?
                ORDER BY id DESC
                """,
                (document_id,)
            ).fetchall()

        return [row_to_dict(row) for row in rows]

    finally:
        connection.close()


# ============================================================
# SEARCH ALL INSTITUTIONAL DATA
# ============================================================

def search_all(
    query: str,
    limit: int = 20
) -> Dict[str, List[Dict[str, Any]]]:
    """
    Search documents, entities and decisions.
    """

    query = query.strip()

    if not query:
        return {
            "documents": [],
            "entities": [],
            "decisions": []
        }

    limit = max(1, min(int(limit), 100))
    pattern = f"%{query}%"

    connection = get_connection()

    try:
        document_rows = connection.execute(
            """
            SELECT *
            FROM documents
            WHERE
                filename LIKE ?
                OR title LIKE ?
                OR content LIKE ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (pattern, pattern, pattern, limit)
        ).fetchall()

        entity_rows = connection.execute(
            """
            SELECT *
            FROM entities
            WHERE
                name LIKE ?
                OR entity_type LIKE ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (pattern, pattern, limit)
        ).fetchall()

        decision_rows = connection.execute(
            """
            SELECT *
            FROM decisions
            WHERE
                title LIKE ?
                OR description LIKE ?
                OR reason LIKE ?
                OR meeting LIKE ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (
                pattern,
                pattern,
                pattern,
                pattern,
                limit
            )
        ).fetchall()

        return {
            "documents": [row_to_dict(row) for row in document_rows],
            "entities": [row_to_dict(row) for row in entity_rows],
            "decisions": [row_to_dict(row) for row in decision_rows]
        }

    finally:
        connection.close()


# ============================================================
# HELPER
# ============================================================

def row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
    """
    Convert SQLite Row into a normal dictionary.

    JSON metadata is automatically decoded.
    """

    result = dict(row)

    if "metadata" in result:
        try:
            result["metadata"] = json.loads(
                result["metadata"] or "{}"
            )
        except (json.JSONDecodeError, TypeError):
            result["metadata"] = {}

    return result


# ============================================================
# INITIALIZE DATABASE
# ============================================================

initialize_database()