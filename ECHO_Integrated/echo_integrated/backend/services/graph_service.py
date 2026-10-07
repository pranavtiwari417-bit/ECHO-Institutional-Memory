"""
ECHO - Institutional Memory & Decision Intelligence Engine

File: backend/services/graph_service.py
Purpose:
    Build, manage, save and query the ECHO knowledge graph.
"""

import pickle
from pathlib import Path
from typing import Any, Dict, List, Optional

import networkx as nx  # type: ignore

try:
    from .database import (
        get_entities,
        get_relationships,
    )
except ImportError:
    try:
        from services.database import (
            get_entities,
            get_relationships,
        )
    except ImportError:
        from database import (
            get_entities,
            get_relationships,
        )


# ============================================================
# PATHS
# ============================================================

PROJECT_ROOT = Path(__file__).resolve().parents[2]

GRAPH_DIR = PROJECT_ROOT / "knowledge-graph"
if not GRAPH_DIR.exists() and (Path(__file__).resolve().parents[1] / "knowledge-graph").exists():
    GRAPH_DIR = Path(__file__).resolve().parents[1] / "knowledge-graph"

GRAPH_FILE = GRAPH_DIR / "graph-data.pkl"


# ============================================================
# GRAPH CREATION
# ============================================================

def create_graph() -> nx.DiGraph:
    """
    Create a directed knowledge graph from database entities
    and relationships.
    """

    graph = nx.DiGraph()

    entities = get_entities()
    relationships = get_relationships()

    # --------------------------------------------------------
    # Add entity nodes
    # --------------------------------------------------------
    for entity in entities:
        entity_name = entity.get("name", "").strip()

        if not entity_name:
            continue

        graph.add_node(
            entity_name,
            entity_type=entity.get("entity_type", ""),
            document_id=entity.get("document_id"),
            metadata=entity.get("metadata", {})
        )

    # --------------------------------------------------------
    # Add relationships
    # --------------------------------------------------------
    for relationship in relationships:
        source = relationship.get("source_entity", "").strip()
        target = relationship.get("target_entity", "").strip()
        relation = relationship.get("relation", "").strip()

        if not source or not target:
            continue

        # Automatically create missing nodes.
        if source not in graph:
            graph.add_node(
                source,
                entity_type="unknown"
            )

        if target not in graph:
            graph.add_node(
                target,
                entity_type="unknown"
            )

        graph.add_edge(
            source,
            target,
            relation=relation,
            document_id=relationship.get("document_id"),
            metadata=relationship.get("metadata", {})
        )

    return graph


# ============================================================
# SAVE GRAPH
# ============================================================

def save_graph(graph: nx.DiGraph) -> str:
    """
    Save NetworkX graph to graph-data.pkl.
    """

    GRAPH_DIR.mkdir(parents=True, exist_ok=True)

    with open(GRAPH_FILE, "wb") as file:
        pickle.dump(graph, file)

    return str(GRAPH_FILE)


# ============================================================
# LOAD GRAPH
# ============================================================

def load_graph() -> nx.DiGraph:
    """
    Load the saved graph.

    If no saved graph exists, create a fresh graph.
    """

    if not GRAPH_FILE.exists() or GRAPH_FILE.stat().st_size == 0:
        graph = create_graph()
        save_graph(graph)
        return graph

    try:
        with open(GRAPH_FILE, "rb") as file:
            graph = pickle.load(file)

        if isinstance(graph, nx.DiGraph):
            return graph

        # If an unexpected graph type is stored,
        # rebuild it safely.
        graph = create_graph()
        save_graph(graph)

        return graph

    except (pickle.PickleError, EOFError, OSError):
        graph = create_graph()
        save_graph(graph)

        return graph


# ============================================================
# REBUILD GRAPH
# ============================================================

def rebuild_graph() -> nx.DiGraph:
    """
    Rebuild the knowledge graph from the latest database data.
    """

    graph = create_graph()
    save_graph(graph)

    return graph


# ============================================================
# ADD NODE
# ============================================================

def add_entity_node(
    graph: nx.DiGraph,
    name: str,
    entity_type: str = "unknown",
    document_id: Optional[int] = None,
    metadata: Optional[Dict[str, Any]] = None
) -> nx.DiGraph:
    """
    Add or update an entity node.
    """

    name = name.strip()

    if not name:
        return graph

    if metadata is None:
        metadata = {}

    graph.add_node(
        name,
        entity_type=entity_type,
        document_id=document_id,
        metadata=metadata
    )

    return graph


# ============================================================
# ADD RELATIONSHIP
# ============================================================

def add_relationship_edge(
    graph: nx.DiGraph,
    source: str,
    relation: str,
    target: str,
    document_id: Optional[int] = None,
    metadata: Optional[Dict[str, Any]] = None
) -> nx.DiGraph:
    """
    Add a relationship between two entities.
    """

    source = source.strip()
    target = target.strip()
    relation = relation.strip()

    if not source or not target:
        return graph

    if metadata is None:
        metadata = {}

    # Create nodes if they don't exist.
    if source not in graph:
        graph.add_node(source, entity_type="unknown")

    if target not in graph:
        graph.add_node(target, entity_type="unknown")

    graph.add_edge(
        source,
        target,
        relation=relation,
        document_id=document_id,
        metadata=metadata
    )

    return graph


# ============================================================
# GRAPH STATISTICS
# ============================================================

def get_graph_stats(
    graph: Optional[nx.DiGraph] = None
) -> Dict[str, Any]:
    """
    Return basic graph statistics.
    """

    if graph is None:
        graph = load_graph()

    return {
        "nodes": graph.number_of_nodes(),
        "edges": graph.number_of_edges(),
        "density": nx.density(graph),
        "is_empty": graph.number_of_nodes() == 0
    }


# ============================================================
# GET NODE DETAILS
# ============================================================

def get_node(
    name: str,
    graph: Optional[nx.DiGraph] = None
) -> Optional[Dict[str, Any]]:
    """
    Return details of a specific entity node.
    """

    if graph is None:
        graph = load_graph()

    name = name.strip()

    if name not in graph:
        return None

    data = dict(graph.nodes[name])

    return {
        "name": name,
        **data
    }


# ============================================================
# GET NEIGHBOURS
# ============================================================

def get_related_entities(
    name: str,
    graph: Optional[nx.DiGraph] = None
) -> List[Dict[str, Any]]:
    """
    Return entities directly connected to the given entity.
    """

    if graph is None:
        graph = load_graph()

    name = name.strip()

    if name not in graph:
        return []

    related = []

    # Outgoing relationships.
    for target in graph.successors(name):
        edge_data = graph.get_edge_data(name, target, default={})

        related.append({
            "entity": target,
            "direction": "outgoing",
            "relation": edge_data.get("relation", ""),
            "metadata": edge_data.get("metadata", {})
        })

    # Incoming relationships.
    for source in graph.predecessors(name):
        edge_data = graph.get_edge_data(source, name, default={})

        related.append({
            "entity": source,
            "direction": "incoming",
            "relation": edge_data.get("relation", ""),
            "metadata": edge_data.get("metadata", {})
        })

    return related


# ============================================================
# FIND PATH
# ============================================================

def find_path(
    source: str,
    target: str,
    graph: Optional[nx.DiGraph] = None
) -> List[str]:
    """
    Find a relationship path between two entities.
    """

    if graph is None:
        graph = load_graph()

    source = source.strip()
    target = target.strip()

    if source not in graph or target not in graph:
        return []

    try:
        return nx.shortest_path(
            graph,
            source=source,
            target=target
        )
    except nx.NetworkXNoPath:
        return []


# ============================================================
# GRAPH JSON
# ============================================================

def graph_to_dict(
    graph: Optional[nx.DiGraph] = None
) -> Dict[str, Any]:
    """
    Convert the NetworkX graph into JSON-friendly data.
    """

    if graph is None:
        graph = load_graph()

    nodes = []

    for node, data in graph.nodes(data=True):
        nodes.append({
            "id": node,
            "label": node,
            **data
        })

    edges = []

    for source, target, data in graph.edges(data=True):
        edges.append({
            "source": source,
            "target": target,
            "relation": data.get("relation", ""),
            "document_id": data.get("document_id"),
            "metadata": data.get("metadata", {})
        })

    return {
        "nodes": nodes,
        "edges": edges,
        "stats": get_graph_stats(graph)
    }


# ============================================================
# INITIAL GRAPH
# ============================================================

def initialize_graph() -> nx.DiGraph:
    """
    Initialize graph from current database state.
    """

    graph = load_graph()

    return graph
