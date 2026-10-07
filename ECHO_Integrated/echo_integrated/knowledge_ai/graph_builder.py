"""Build and persist the NetworkX DiGraph.

Graph layout
------------
Node id  : "<TYPE>:<normalized name>" (dates: "DATE:YYYY-MM-DD"; source documents:
           "DOCUMENT:source:<document_id>").
Node data: name, type, aliases, date_iso, description, provenance (list of dicts),
           and source_document=True for nodes created from document metadata.
Edge data: ``facts`` - a list of {"relation", "date_iso", "provenance": [...]}.
           A DiGraph holds one edge per (source, target) pair, so several
           relations between the same two nodes are stored as several facts.
Graph data: ``modes`` - sorted list of extraction modes present ("mock", "real", ...).
"""

import json
from collections import Counter
from typing import Any, Dict, Iterable, Optional, Union

import networkx as nx

from .config import Config
from .extractor import extract_document, merge_extractions
from .llm_service import LLMService
from .schemas import EntityType, ExtractionResult, Provenance, SourceDocument

SOURCE_PREFIX = "DOCUMENT:source:"


def _add_fact(G: nx.DiGraph, source: str, target: str, fact: Dict[str, Any]) -> None:
    if G.has_edge(source, target):
        facts = G[source][target]["facts"]
        for existing in facts:
            if existing["relation"] == fact["relation"] and existing["date_iso"] == fact["date_iso"]:
                seen = {Provenance(**p).key() for p in existing["provenance"]}
                for p in fact["provenance"]:
                    if Provenance(**p).key() not in seen:
                        existing["provenance"].append(p)
                        seen.add(Provenance(**p).key())
                return
        facts.append(fact)
    else:
        G.add_edge(source, target, facts=[fact])


def build_graph(
    extractions: Union[ExtractionResult, Iterable[ExtractionResult]],
    add_document_nodes: bool = True,
) -> nx.DiGraph:
    """Merge extraction results (deduplicating) and build the knowledge graph."""
    if isinstance(extractions, ExtractionResult):
        extractions = [extractions]
    merged = merge_extractions(list(extractions))
    G = nx.DiGraph()
    modes = set()
    for ent in merged.entities:
        G.add_node(
            ent.id,
            name=ent.name,
            type=ent.type.value,
            aliases=list(ent.aliases),
            date_iso=ent.date_iso,
            description=ent.description,
            provenance=[p.model_dump() for p in ent.provenance],
        )
        modes.update(p.mode for p in ent.provenance)
    for rel in merged.relationships:
        if rel.source_id not in G or rel.target_id not in G:
            continue
        fact = {
            "relation": rel.relation.value,
            "date_iso": rel.date_iso,
            "provenance": [p.model_dump() for p in rel.provenance],
        }
        modes.update(p.mode for p in rel.provenance)
        _add_fact(G, rel.source_id, rel.target_id, fact)
    _propagate_meeting_dates(G)
    if add_document_nodes:
        _add_document_nodes(G)
    G.graph["modes"] = sorted(modes)
    G.graph["extraction_errors"] = list(merged.errors)
    G.graph["extraction_warnings"] = list(merged.warnings)
    return G


def build_graph_from_documents(
    documents: Iterable[Union[SourceDocument, Dict[str, Any]]],
    llm: Optional[LLMService] = None,
    config: Optional[Config] = None,
) -> nx.DiGraph:
    """Convenience pipeline: extract every document, then build the graph."""
    llm = llm or LLMService(config)
    results = [extract_document(doc, llm=llm, config=config) for doc in documents]
    return build_graph(results)


def _propagate_meeting_dates(G: nx.DiGraph) -> None:
    """Copy the date of a HELD_ON edge onto the meeting/event node."""
    for node, data in G.nodes(data=True):
        if data["type"] not in ("MEETING", "EVENT") or data.get("date_iso"):
            continue
        for succ in G.successors(node):
            if any(f["relation"] == "HELD_ON" for f in G[node][succ]["facts"]):
                if G.nodes[succ].get("date_iso"):
                    data["date_iso"] = G.nodes[succ]["date_iso"]
                    break


def _add_document_nodes(G: nx.DiGraph) -> None:
    """Add one DOCUMENT node per source document and MENTIONED_IN edges from entities."""
    for node in list(G.nodes):
        data = G.nodes[node]
        if data["type"] in ("DATE", "DOCUMENT"):
            continue
        for prov in list(data["provenance"]):
            doc_id = prov.get("document_id")
            if not doc_id:
                continue
            doc_node = SOURCE_PREFIX + str(doc_id)
            if doc_node not in G:
                G.add_node(
                    doc_node,
                    name=prov.get("filename") or str(doc_id),
                    type=EntityType.DOCUMENT.value,
                    aliases=[],
                    date_iso=None,
                    description=None,
                    source_document=True,
                    document_id=doc_id,
                    filename=prov.get("filename"),
                    provenance=[Provenance(document_id=doc_id, filename=prov.get("filename"),
                                           mode=prov.get("mode", "real")).model_dump()],
                )
            _add_fact(G, node, doc_node, {"relation": "MENTIONED_IN", "date_iso": None, "provenance": [prov]})


# --------------------------------------------------------------------------
# Inspection helpers
# --------------------------------------------------------------------------
def graph_stats(G: nx.DiGraph) -> Dict[str, Any]:
    types = Counter(d["type"] for _, d in G.nodes(data=True))
    relations = Counter(f["relation"] for _, _, d in G.edges(data=True) for f in d.get("facts", []))
    return {
        "nodes": G.number_of_nodes(),
        "edges": G.number_of_edges(),
        "facts": sum(relations.values()),
        "node_types": dict(types),
        "relations": dict(relations),
        "modes": list(G.graph.get("modes", [])),
    }


def graph_has_mock_data(G: nx.DiGraph) -> bool:
    return "mock" in G.graph.get("modes", [])


# --------------------------------------------------------------------------
# JSON persistence (no extra database needed; store the string in SQLite if you like)
# --------------------------------------------------------------------------
def graph_to_dict(G: nx.DiGraph) -> Dict[str, Any]:
    return {
        "graph": dict(G.graph),
        "nodes": [{"id": n, **d} for n, d in G.nodes(data=True)],
        "edges": [{"source": u, "target": v, "facts": d.get("facts", [])} for u, v, d in G.edges(data=True)],
    }


def graph_from_dict(payload: Dict[str, Any]) -> nx.DiGraph:
    G = nx.DiGraph()
    G.graph.update(payload.get("graph", {}))
    for node in payload.get("nodes", []):
        data = dict(node)
        G.add_node(data.pop("id"), **data)
    for edge in payload.get("edges", []):
        G.add_edge(edge["source"], edge["target"], facts=edge.get("facts", []))
    return G


def save_graph(G: nx.DiGraph, path: str) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(graph_to_dict(G), fh, ensure_ascii=False, indent=2)


def load_graph(path: str) -> nx.DiGraph:
    with open(path, "r", encoding="utf-8") as fh:
        return graph_from_dict(json.load(fh))
