"""
ECHO - Institutional Memory & Decision Intelligence Engine

File: backend/routes/documents_routes.py
Purpose:
    Document routes module alias for plural import naming.
"""

from .document_routes import (
    documents_bp,
    get_db_connection,
    initialize_documents_table,
    document_to_dict,
    get_documents,
    get_document,
    create_document,
    update_document,
    delete_document,
)

__all__ = [
    "documents_bp",
    "get_db_connection",
    "initialize_documents_table",
    "document_to_dict",
    "get_documents",
    "get_document",
    "create_document",
    "update_document",
    "delete_document",
]
