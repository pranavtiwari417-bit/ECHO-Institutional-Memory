"""
ECHO - Institutional Memory & Decision Intelligence Engine

Routes package initialization.
"""

from .document_routes import documents_bp
from .query_routes import query_bp
from .search_routes import search_bp

__all__ = [
    "documents_bp",
    "query_bp",
    "search_bp",
]
