"""Graph querying and evidence retrieval: deterministic keyword + graph retrieval.

This is NOT semantic or vector search. A question is split into
  * date constraints   (days, months, years, "between X and Y" ranges),
  * entity mentions    (committees, departments, people... named in the question),
  * topic terms        (the remaining meaningful words),
  * intent             (decided / proposed / due / why / history ...).

Retrieval strategy
------------------
1. DIRECT matches first: a decision qualifies only if the topic terms appear in
   its own name/aliases (direct) or in its stated reasons/actions (supporting).
   Names of committees, meetings or people alone never make a decision relevant.
2. FILTERS: mentioned entities must be linked to the decision through outcome,
   proposal, meeting or action relationships; dates must match a dated event of
   the kind asked about; "why"/"proposed"/"due" questions need that kind of fact.
3. ENRICHMENT: graph traversal only adds explicitly related decisions
   (FOLLOWS_UP / SUPERSEDES / a shared action) and only for history-style
   questions. Shared committees, meetings or documents are never a reason to
   return another decision.
4. Evidence comes only from the selected decisions' trails, ranked by topic
   relevance, and sufficiency is judged on the best single decision.

Cost: each call is linear in graph size (it builds a small term index);
traversals are bounded (one hop, or the explicit limits documented below).

Public functions:
    stem, content_tokens, find_entities, neighbors, find_path, entities_on_date,
    date_intent, find_decisions_on_date, get_decision_trail,
    list_decision_trails, retrieve_context
"""

import calendar
import datetime
import math
import re
from collections import Counter, deque
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

import networkx as nx

from .config import Config
from .extractor import DATE_PATTERN, STOPWORDS, normalize_name, normalize_text, parse_date
from .schemas import DecisionTrail, EntityType, Provenance, RetrievalResult, ScoredEntity, TrailStep


# ==========================================================================
# 1. Tokens
# ==========================================================================
_WORD_RE = re.compile(r"[^\W_]+", re.UNICODE)
_POSSESSIVE_RE = re.compile(r"[\u2019']s\b")
_DOUBLED = set("bgmnprt")  # consonants that double before -ed/-ing: planned -> plan


def tokenize(text: str) -> List[str]:
    """Lowercase words (unicode-aware); punctuation and possessives are dropped."""
    return _WORD_RE.findall(_POSSESSIVE_RE.sub("", (text or "").lower()))


def stem(token: str) -> str:
    """Small, conservative suffix stripper: approved/approve, policies/policy, committees/committee.

    Short words, numbers and words ending in -ss/-us/-is/-eed are left alone so
    that 'class', 'status', 'analysis' and 'speed' are not mangled.
    """
    t = token.lower()
    if len(t) <= 3 or not t.isalpha():
        return t
    stripped = True
    if t.endswith("ies") and len(t) > 4:
        t = t[:-3] + "y"
    elif t.endswith("ing") and len(t) >= 7:
        t = t[:-3]
        if len(t) > 3 and t[-1] == t[-2] and t[-1] in _DOUBLED:
            t = t[:-1]
    elif t.endswith("ed") and len(t) >= 5 and not t.endswith("eed"):
        t = t[:-2]
        if len(t) > 3 and t[-1] == t[-2] and t[-1] in _DOUBLED:
            t = t[:-1]
    elif t.endswith("es") and len(t) >= 5:
        t = t[:-2]
    elif t.endswith("s") and len(t) >= 5 and not t.endswith(("ss", "us", "is")):
        t = t[:-1]
    else:
        stripped = False
    if not stripped and t.endswith("e") and len(t) > 3:
        t = t[:-1]
    return t


def content_tokens(text: str) -> List[str]:
    """Stemmed words with stopwords removed (order and duplicates preserved)."""
    return [stem(t) for t in tokenize(text) if t not in STOPWORDS]


# Words that describe WHAT is asked (intent), not WHAT it is about.
_GENERIC_STEMS = {
    stem(w) for w in (
        "approve approved approves approval approving decide decided decides deciding decision "
        "decisions reject rejected rejects rejection propose proposed proposes proposal proposals "
        "defer deferred defers resolve resolved resolution ratify ratified endorse endorsed reason "
        "reasons rationale justification justified justify because meeting meetings happen happened "
        "happening held date dates made make makes take taken took give given gave result results "
        "outcome outcomes history timeline trail chronological chronology list show tell explain "
        "describe summarize summarise summary overview please due deadline deadlines deliver "
        "delivered related relate relates relating about regarding concerning concern concerns "
        "month months year years day days week weeks recent latest earlier later previous "
        "follow follows followed supersede supersedes superseded "
        "so very really actually exactly specifically currently finally ultimately eventually "
        "mainly mostly just only still yet then thus hence"
    ).split()
}
# Words that name a kind of body; only meaningful as part of a full entity name.
_ROLE_STEMS = {
    stem(w) for w in (
        "committee council board department college university institute senate organization "
        "organisation member members faculty office cell unit"
    ).split()
}

_DECIDE_VERB_RE = re.compile(r"\b(?:decid\w*|approv\w*|reject\w*|defer\w*|resolv\w*|ratif\w*|endors\w*)\b", re.I)
_DECISION_NOUN_RE = re.compile(r"\bdecisions?\b", re.I)
_PROPOSE_RE = re.compile(r"\bpropos\w*", re.I)
_DUE_RE = re.compile(r"\b(?:due|deadlines?|deliver\w*)\b", re.I)
_WHY_RE = re.compile(r"\b(?:why|reasons?|rationale|justif\w*|because)\b", re.I)
_LISTING_RE = re.compile(
    r"\b(?:list|all|every|decisions|timeline|history|chronolog\w*|overview|summar\w*|recent|latest|so far)\b", re.I)
_HISTORY_RE = re.compile(
    r"\b(?:history|timeline|chronolog\w*|related|relate\w*|follow\w*|supersed\w*|previous\w*|earlier|precede\w*)\b",
    re.I)
_OUTCOME_VERBS = (("APPROVED", re.compile(r"\bapprov\w*", re.I)),
                  ("REJECTED", re.compile(r"\breject\w*", re.I)),
                  ("DEFERRED", re.compile(r"\bdefer\w*", re.I)))


# ==========================================================================
# 2. Dates (all comparisons use ISO strings: 'YYYY-MM-DD', 'YYYY-MM' or 'YYYY')
# ==========================================================================
_DATE_CI = re.compile(DATE_PATTERN, re.IGNORECASE)
_YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")
_RANGE_BETWEEN_RE = re.compile(rf"\bbetween\s+({DATE_PATTERN})\s+and\s+({DATE_PATTERN})", re.IGNORECASE)
_RANGE_TO_RE = re.compile(
    rf"(?:\bfrom\s+)?({DATE_PATTERN})\s*(?:\bto\b|\bthrough\b|\buntil\b|\btill\b|-|\u2013|\u2014)\s*({DATE_PATTERN})",
    re.IGNORECASE)
_MONTH_WORDS = ({m.lower() for m in calendar.month_name if m}
                | {m.lower() for m in calendar.month_abbr if m} | {"sept"})
_ISO_ARG_RE = re.compile(r"^(\d{4})(?:-(\d{2})(?:-(\d{2}))?)?$")


def _parse_date_text(text: str) -> Optional[str]:
    """parse_date() that also accepts lowercase months ('april 2, 2024')."""
    fixed = re.sub(r"[A-Za-z]+", lambda m: m.group(0).capitalize()
                   if m.group(0).lower() in _MONTH_WORDS else m.group(0).lower(), text)
    return parse_date(fixed)


def _safe_span(iso: Optional[str]) -> Optional[Tuple[str, str]]:
    """(first_day, last_day) covered by 'YYYY-MM-DD' / 'YYYY-MM' / 'YYYY'; None if malformed."""
    m = _ISO_ARG_RE.match(iso or "")
    if not m:
        return None
    year, month, day = int(m.group(1)), m.group(2), m.group(3)
    try:
        if day:
            datetime.date(year, int(month), int(day))
            return iso, iso  # type: ignore[return-value]
        if month:
            last = calendar.monthrange(year, int(month))[1]
            return f"{year:04d}-{month}-01", f"{year:04d}-{month}-{last:02d}"
        return f"{year:04d}-01-01", f"{year:04d}-12-31"
    except ValueError:
        return None


def _validate_date_arg(value: Any, name: str) -> str:
    if not isinstance(value, str) or _safe_span(value) is None:
        raise ValueError(f"{name} must be 'YYYY-MM-DD', 'YYYY-MM' or 'YYYY', got {value!r}")
    return value


def _in_spans(iso: Optional[str], spans: Sequence[Tuple[str, str]]) -> bool:
    """True if the whole period `iso` lies inside one span. Imprecise dates (a month) never
    match a narrower span (a day): the missing day is not guessed."""
    span = _safe_span(iso)
    return bool(span) and any(span[0] >= a and span[1] <= b for a, b in spans)  # type: ignore[index]


# ==========================================================================
# 3. Intent
# ==========================================================================
_EVENT_KINDS = {
    "decide": {"APPROVED", "REJECTED", "DEFERRED", "DECIDED", "MEETING"},
    "propose": {"PROPOSED"},
    "due": {"DUE"},
}
_DEFAULT_KINDS = _EVENT_KINDS["decide"] | _EVENT_KINDS["propose"]


def date_intent(question: str) -> Set[str]:
    """Which dated event kinds a question asks about.

    decided/approved/rejected/deferred... -> outcome + decision-meeting events
    proposed/proposal                     -> proposal events
    due/deadline                          -> action deadlines
    Wording is combined: "proposed and approved" asks for both. The bare noun
    "decision(s)" counts as 'decide' only when no more specific word is present
    ("which decisions were proposed" is about proposals). With no intent word at all,
    outcomes, meetings and proposals count, but deadlines do not.
    """
    question = question or ""
    kinds: Set[str] = set()
    if _DECIDE_VERB_RE.search(question):
        kinds |= _EVENT_KINDS["decide"]
    if _PROPOSE_RE.search(question):
        kinds |= _EVENT_KINDS["propose"]
    if _DUE_RE.search(question):
        kinds |= _EVENT_KINDS["due"]
    if not kinds and _DECISION_NOUN_RE.search(question):
        kinds |= _EVENT_KINDS["decide"]
    return kinds or set(_DEFAULT_KINDS)


@dataclass
class _Question:
    text: str = ""                      # normalized text without dates
    tokens: Set[str] = field(default_factory=set)   # every stemmed word (for entity mentions)
    topic: List[str] = field(default_factory=list)  # topic terms (before entity removal)
    spans: List[Tuple[str, str]] = field(default_factory=list)
    years: List[str] = field(default_factory=list)
    date_error: Optional[str] = None
    kinds: Set[str] = field(default_factory=set)
    explicit_intent: bool = False
    wants_reason: bool = False
    wants_proposal: bool = False
    wants_due: bool = False
    wants_outcome: bool = False
    outcome_kinds: Set[str] = field(default_factory=set)
    listing: bool = False
    history: bool = False


def _parse_question(question: str) -> _Question:
    q = _Question()
    rest = question
    spans: List[Tuple[str, str]] = []

    def take_range(match: "re.Match[str]") -> str:
        a, b = _parse_date_text(match.group(1)), _parse_date_text(match.group(2))
        sa, sb = _safe_span(a), _safe_span(b)
        if not sa or not sb:
            q.date_error = f"'{match.group(0)}' is not a valid date range."
        elif sa[0] > sb[1]:
            q.date_error = f"The date range '{match.group(0)}' ends before it starts."
        else:
            spans.append((sa[0], sb[1]))
        return " "

    rest = _RANGE_BETWEEN_RE.sub(take_range, rest)
    rest = _RANGE_TO_RE.sub(take_range, rest)

    def take_date(match: "re.Match[str]") -> str:
        span = _safe_span(_parse_date_text(match.group(0)))
        if span:
            spans.append(span)
        else:
            q.date_error = f"'{match.group(0)}' is not a valid date."
        return " "

    rest = _DATE_CI.sub(take_date, rest)
    q.years = list(dict.fromkeys(_YEAR_RE.findall(rest)))
    rest = _YEAR_RE.sub(" ", rest)

    q.spans = list(dict.fromkeys(spans))
    q.text = normalize_text(rest)
    stems = content_tokens(rest)
    q.tokens = set(stems)
    q.topic = list(dict.fromkeys(t for t in stems if t not in _GENERIC_STEMS and t not in _ROLE_STEMS))
    q.kinds = date_intent(question)
    q.explicit_intent = bool(_DECIDE_VERB_RE.search(question) or _PROPOSE_RE.search(question)
                             or _DUE_RE.search(question) or _DECISION_NOUN_RE.search(question))
    q.wants_reason = bool(_WHY_RE.search(question))
    q.wants_proposal = bool(_PROPOSE_RE.search(question))
    q.wants_due = bool(_DUE_RE.search(question))
    q.wants_outcome = bool(_DECIDE_VERB_RE.search(question))
    q.outcome_kinds = {kind for kind, rx in _OUTCOME_VERBS if rx.search(question)}
    q.listing = bool(_LISTING_RE.search(question))
    q.history = bool(_HISTORY_RE.search(question))
    return q


# ==========================================================================
# 4. Low-level graph helpers
# ==========================================================================
_OUTCOME_KINDS = ("APPROVED", "REJECTED", "DEFERRED")
_KIND_FOR_REL = {"PROPOSED_BY": "PROPOSED", "APPROVED_BY": "APPROVED",
                 "REJECTED_BY": "REJECTED", "DEFERRED_BY": "DEFERRED"}
_VERB = {"PROPOSED": "proposed", "APPROVED": "approved", "REJECTED": "rejected", "DEFERRED": "deferred"}
_ACTOR_RELS = set(_KIND_FOR_REL)
_MENTION_TYPES = {"COMMITTEE", "DEPARTMENT", "ORGANIZATION", "PERSON", "EVENT"}


def _pkey(p: Provenance) -> Tuple[Any, ...]:
    """Identity of a source sentence (ignores the extraction mode)."""
    return (p.document_id, p.page, p.chunk_id, p.evidence)


def _provs(items: Iterable[Dict[str, Any]]) -> List[Provenance]:
    return [Provenance(**p) for p in items]


def _dedupe(provs: Iterable[Provenance]) -> List[Provenance]:
    seen: Set[Tuple[Any, ...]] = set()
    out: List[Provenance] = []
    for p in provs:
        if p.key() not in seen:
            seen.add(p.key())
            out.append(p)
    return out


def _ekeys(provs: Iterable[Provenance]) -> Set[Tuple[Any, ...]]:
    return {_pkey(p) for p in provs if p.evidence}


def _facts(G: nx.DiGraph, u: str, v: str) -> List[Dict[str, Any]]:
    """Facts of edge u->v in a deterministic order."""
    return sorted(G[u][v].get("facts", []), key=lambda f: (f["relation"], f.get("date_iso") or ""))


def _has_rel(G: nx.DiGraph, u: str, v: str, relation: str) -> bool:
    return G.has_edge(u, v) and any(f["relation"] == relation for f in G[u][v].get("facts", []))


def _real_nodes(G: nx.DiGraph) -> List[str]:
    """Node ids in sorted order, without source-document nodes."""
    return sorted(n for n, d in G.nodes(data=True) if not d.get("source_document"))


def _structural_graph(G: nx.DiGraph) -> nx.Graph:
    """Undirected view used by find_path: no source-document nodes, no MENTIONED_IN links."""
    U = nx.Graph()
    for n in _real_nodes(G):
        U.add_node(n)
    for u, v in sorted(G.edges()):
        if u in U and v in U and any(f["relation"] != "MENTIONED_IN" for f in G[u][v].get("facts", [])):
            U.add_edge(u, v)
    return U


def _name_tokens(data: Dict[str, Any]) -> List[str]:
    return content_tokens(" ".join([data["name"]] + list(data.get("aliases", []))))


def _term_in(term: str, tokens: Set[str]) -> bool:
    """Exact stem match, or prefix match for terms of 3+ letters ('lab' ~ 'laboratory')."""
    if term in tokens:
        return True
    return len(term) >= 3 and any(t.startswith(term) for t in tokens)


class _Index:
    """Per-call term statistics so rare terms count more than words found everywhere."""

    def __init__(self, G: nx.DiGraph) -> None:
        self.G = G
        self.nodes = _real_nodes(G)
        self.df: Counter = Counter()
        self.year_vocab: Set[str] = set()  # words in decision/event names (a year here is a topic, e.g. "Vision 2030")
        self.vocab: Set[str] = set()
        for n in self.nodes:
            d = G.nodes[n]
            if d["type"] == "DATE":
                continue
            toks = set(_name_tokens(d))
            self.df.update(toks)
            if d["type"] in ("DECISION", "EVENT"):
                self.year_vocab |= toks
            self.vocab |= toks | set(content_tokens(d.get("description") or ""))
            for p in d.get("provenance", []):
                self.vocab |= set(content_tokens(p.get("evidence") or ""))
        for u, v, data in G.edges(data=True):
            for fact in data.get("facts", []):
                for p in fact.get("provenance", []):
                    self.vocab |= set(content_tokens(p.get("evidence") or ""))

    def weight(self, term: str) -> float:
        return 1.0 + math.log((len(self.nodes) + 1) / (self.df.get(term, 0) + 1))

    def known(self, term: str) -> bool:
        return _term_in(term, self.vocab)


def _check_limit(value: Any, name: str, minimum: int = 1) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}, got {value!r}")
    return value


# ==========================================================================
# 5. Public graph queries
# ==========================================================================
def find_entities(
    G: nx.DiGraph, query: str, types: Optional[Sequence[Any]] = None, limit: int = 10
) -> List[ScoredEntity]:
    """Rank nodes by weighted keyword overlap with `query` (names/aliases count more than descriptions)."""
    _check_limit(limit, "limit")
    wanted: Optional[Set[str]] = None
    if types:
        wanted = set()
        for t in types:
            try:
                wanted.add(EntityType(str(getattr(t, "value", t)).upper()).value)
            except ValueError:
                raise ValueError(f"unknown entity type: {t!r}") from None
    if G is None or G.number_of_nodes() == 0 or not (query or "").strip():
        return []
    terms = list(dict.fromkeys(t for t in content_tokens(query) if t not in _GENERIC_STEMS))
    if not terms:
        return []
    phrase = normalize_text(query)
    index = _Index(G)
    found: List[ScoredEntity] = []
    for n in index.nodes:
        d = G.nodes[n]
        if wanted and d["type"] not in wanted:
            continue
        name_toks, desc_toks = set(_name_tokens(d)), set(content_tokens(d.get("description") or ""))
        score = 0.0
        for t in terms:
            if _term_in(t, name_toks):
                score += index.weight(t)
            elif _term_in(t, desc_toks):
                score += 0.3 * index.weight(t)
        key = normalize_text(d["name"])
        if score > 0 and len(key) >= 4 and key in phrase:
            score += 2.0
        if score > 0:
            found.append(ScoredEntity(id=n, name=d["name"], type=d["type"], score=round(score, 3)))
    found.sort(key=lambda e: (-e.score, e.name, e.id))
    return found[:limit]


def neighbors(
    G: nx.DiGraph, node_id: str, relation: Optional[str] = None, direction: str = "both"
) -> List[Dict[str, Any]]:
    """Adjacent nodes with the connecting facts. direction: 'out', 'in' or 'both'.

    Source-document nodes are skipped. Raises KeyError for an unknown node and
    ValueError for an invalid direction.
    """
    if direction not in ("out", "in", "both"):
        raise ValueError(f"direction must be 'out', 'in' or 'both', got {direction!r}")
    if G is None or node_id not in G:
        raise KeyError(f"unknown node: {node_id}")
    pairs: List[Tuple[str, str, str, str]] = []
    if direction in ("out", "both"):
        pairs += [(node_id, s, "out", s) for s in G.successors(node_id)]
    if direction in ("in", "both"):
        pairs += [(p, node_id, "in", p) for p in G.predecessors(node_id)]
    out: List[Dict[str, Any]] = []
    for u, v, way, other in pairs:
        if G.nodes[other].get("source_document"):
            continue
        for fact in _facts(G, u, v):
            if relation and fact["relation"] != relation:
                continue
            out.append({
                "node_id": other, "name": G.nodes[other]["name"], "type": G.nodes[other]["type"],
                "relation": fact["relation"], "direction": way, "date_iso": fact.get("date_iso"),
                "provenance": _provs(fact.get("provenance", [])),
            })
    out.sort(key=lambda r: (r["direction"], r["name"], r["relation"], r["date_iso"] or "", r["node_id"]))
    return out


def find_path(G: nx.DiGraph, source_id: str, target_id: str, max_length: int = 6) -> Optional[List[str]]:
    """Shortest path of node ids (edge direction and document nodes ignored), or None.

    The search is breadth-first and stops at `max_length` edges, so it stays bounded on large graphs.
    """
    _check_limit(max_length, "max_length")
    if G is None or source_id not in G or target_id not in G:
        return None
    U = _structural_graph(G)
    if source_id not in U or target_id not in U:
        return None
    parent: Dict[str, Optional[str]] = {source_id: None}
    queue = deque([(source_id, 0)])
    while queue:
        node, depth = queue.popleft()
        if node == target_id:
            path = [node]
            while parent[path[-1]] is not None:
                path.append(parent[path[-1]])  # type: ignore[arg-type]
            return path[::-1]
        if depth == max_length:
            continue
        for nxt in sorted(U.neighbors(node)):
            if nxt not in parent:
                parent[nxt] = node
                queue.append((nxt, depth + 1))
    return None


def entities_on_date(G: nx.DiGraph, date_iso: str) -> List[Dict[str, str]]:
    """Meetings/events/decisions/actions directly linked to a DATE node.

    A day ('2024-04-02') uses exactly that DATE node. A month ('2024-04') or year
    uses every DATE node inside it. Malformed input raises ValueError.
    """
    _validate_date_arg(date_iso, "date_iso")
    span = _safe_span(date_iso)
    out: Dict[Tuple[str, str], Dict[str, str]] = {}
    if G is None:
        return []
    for n in _real_nodes(G):
        d = G.nodes[n]
        if d["type"] != "DATE" or not _in_spans(d.get("date_iso"), [span]):  # type: ignore[list-item]
            continue
        for item in neighbors(G, n, direction="in"):
            out[(item["node_id"], item["relation"])] = {
                "id": item["node_id"], "name": item["name"], "type": item["type"], "relation": item["relation"]}
    return [out[k] for k in sorted(out)]


# ==========================================================================
# 6. Decision trails
# ==========================================================================
# order of steps that share a date / of undated steps
_DATED_ORDER = {"PROPOSED": 0, "MEETING": 1, "DECIDED": 2, "APPROVED": 3, "REJECTED": 3, "DEFERRED": 3}
_UNDATED_ORDER = {"APPROVED": 0, "REJECTED": 0, "DEFERRED": 0, "PROPOSED": 0, "MEETING": 1, "DECIDED": 1,
                  "REASON": 2, "ACTION": 3, "RELATED_DECISION": 4}


def _pick_meeting(
    G: nx.DiGraph, actor_id: str, step_date: Optional[str], step_keys: Set[Tuple[Any, ...]],
    meetings: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """The DECIDED_AT meeting an outcome belongs to, or None when it is not clearly supported.

    Candidates are meetings the actor CONVENED. A candidate is accepted when (1) exactly
    one candidate was stated in the same source sentence, else (2) exactly one candidate
    has the step's date, else (3) the step is undated and there is exactly one candidate.
    A candidate whose date contradicts the step's own date is never accepted.
    """
    cands = [m for m in meetings if _has_rel(G, actor_id, m["id"], "CONVENED")]
    if step_date:  # a meeting whose date contradicts the step's own date is never accepted
        cands = [m for m in cands if not (m["date"] and m["date"] != step_date)]
    if not cands:
        return None
    shared = [m for m in cands if m["keys"] & step_keys]
    if len(shared) == 1:
        return shared[0]
    if step_date:
        same = [m for m in cands if m["date"] == step_date]
        return same[0] if len(same) == 1 else None
    return cands[0] if len(cands) == 1 else None


def _status_of(steps: Sequence[TrailStep], superseded: bool) -> str:
    """proposed / approved / rejected / deferred / conflicting / superseded / unknown.

    The latest dated outcome decides. Outcomes on that same date that disagree, or undated
    outcomes that disagree with it (their order cannot be known), give 'conflicting'. Only
    explicit SUPERSEDES links produce 'superseded'. Nothing is guessed when no outcome exists.
    """
    if superseded:
        return "superseded"
    outcomes = [s for s in steps if s.kind in _OUTCOME_KINDS]
    if outcomes:
        dated = [s for s in outcomes if s.date_iso]
        if dated:
            last = max(s.date_iso for s in dated)  # type: ignore[type-var]
            final = {s.kind for s in dated if s.date_iso == last}
        else:
            final = {s.kind for s in outcomes}
        undated_kinds = {s.kind for s in outcomes if not s.date_iso}
        if len(final) > 1 or (dated and not undated_kinds <= final):
            return "conflicting"
        return next(iter(final)).lower()
    return "proposed" if any(s.kind == "PROPOSED" for s in steps) else "unknown"


def get_decision_trail(G: nx.DiGraph, decision_id: str) -> DecisionTrail:
    """Chronological trail of one decision: proposal, meeting, outcomes, reasons, actions, related decisions.

    Dates come only from the step's own relationship, from a meeting the acting body convened that is
    linked to the decision, or from a DECIDED_ON fact stated in the same source sentence. Anything else
    stays undated. Order is deterministic, duplicates are merged, and every step keeps its provenance.
    """
    if G is None or decision_id not in G:
        raise KeyError(f"unknown node: {decision_id}")
    node = G.nodes[decision_id]
    if node.get("type") != "DECISION":
        raise ValueError(f"{decision_id} is not a DECISION node")
    name = node["name"]

    out: List[Tuple[str, Dict[str, Any]]] = []
    for succ in sorted(G.successors(decision_id)):
        if G.nodes[succ].get("source_document"):
            continue
        out += [(succ, f) for f in _facts(G, decision_id, succ) if f["relation"] != "MENTIONED_IN"]

    meetings: List[Dict[str, Any]] = []
    decided_on: List[Tuple[str, List[Provenance]]] = []
    for succ, f in out:
        provs = _provs(f.get("provenance", []))
        date = G.nodes[succ].get("date_iso")
        if f["relation"] == "DECIDED_AT":
            meetings.append({"id": succ, "name": G.nodes[succ]["name"], "date": date,
                             "provs": provs, "keys": _ekeys(provs)})
        elif f["relation"] == "DECIDED_ON" and date:
            decided_on.append((date, provs))

    raw: List[Dict[str, Any]] = []
    used_meetings: Set[str] = set()
    reasons: Dict[str, Dict[str, Any]] = {}
    actions: Dict[str, Dict[str, Any]] = {}
    related: List[Dict[str, Any]] = []

    for succ, f in out:
        rel, sname = f["relation"], G.nodes[succ]["name"]
        provs = _provs(f.get("provenance", []))
        if rel in _KIND_FOR_REL:
            kind, date, keys = _KIND_FOR_REL[rel], f.get("date_iso"), _ekeys(provs)
            meet = None
            if kind != "PROPOSED":
                meet = _pick_meeting(G, succ, date, keys, meetings)
                if meet:
                    used_meetings.add(meet["id"])
                    date = date or meet["date"]
                if not date:
                    shared = {d for d, dp in decided_on if _ekeys(dp) & keys}
                    date = next(iter(shared)) if len(shared) == 1 else None
            desc = f"{sname} {_VERB[kind]} '{name}'" + (f" at {meet['name']}" if meet else "")
            raw.append({"kind": kind, "date": date, "desc": desc, "actor": sname, "actor_id": succ,
                        "meeting": meet["name"] if meet else None, "provs": provs})
        elif rel == "JUSTIFIED_BY":
            item = reasons.setdefault(succ, {"name": sname, "provs": []})
            item["provs"] += provs
        elif rel == "LED_TO":
            item = actions.setdefault(succ, {"name": sname, "provs": [], "assignees": [], "dues": []})
            item["provs"] += provs
            for tgt in sorted(G.successors(succ)):
                for x in _facts(G, succ, tgt):
                    if x["relation"] == "ASSIGNED_TO":
                        item["assignees"].append(G.nodes[tgt]["name"])
                        item["provs"] += _provs(x.get("provenance", []))
                    elif x["relation"] == "DUE_ON" and G.nodes[tgt].get("date_iso"):
                        item["dues"].append(G.nodes[tgt]["date_iso"])
                        item["provs"] += _provs(x.get("provenance", []))
        elif rel in ("FOLLOWS_UP", "SUPERSEDES"):
            related.append({"desc": f"This decision {rel.lower().replace('_', ' ')} '{sname}'", "provs": provs})

    superseded = False
    for pred in sorted(G.predecessors(decision_id)):
        if G.nodes[pred].get("type") != "DECISION" or G.nodes[pred].get("source_document"):
            continue
        for f in _facts(G, pred, decision_id):
            if f["relation"] in ("FOLLOWS_UP", "SUPERSEDES"):
                superseded = superseded or f["relation"] == "SUPERSEDES"
                related.append({"desc": f"Decision '{G.nodes[pred]['name']}' "
                                        f"{f['relation'].lower().replace('_', ' ')} this decision",
                                "provs": _provs(f.get("provenance", []))})

    # merge duplicate outcome/proposal steps (same actor and kind, same date or same sentence)
    merged: List[Dict[str, Any]] = []
    for step in raw:
        target = None
        for m in merged:
            if m["kind"] == step["kind"] and m["actor_id"] == step["actor_id"]:
                overlap = bool(_ekeys(m["provs"]) & _ekeys(step["provs"]))
                if m["date"] == step["date"] or (overlap and (m["date"] is None or step["date"] is None)):
                    target = m
                    break
        if target is None:
            merged.append(step)
        else:
            target["provs"] = _dedupe(target["provs"] + step["provs"])
            target["date"] = target["date"] or step["date"]
            target["meeting"] = target["meeting"] or step["meeting"]
    raw = merged

    outcome_dates = {s["date"] for s in raw if s["kind"] in _OUTCOME_KINDS and s["date"]}
    decided_by_date: Dict[str, List[Provenance]] = {}
    for date, provs in decided_on:
        if date not in outcome_dates:
            decided_by_date.setdefault(date, []).extend(provs)
    for date, provs in sorted(decided_by_date.items()):
        raw.append({"kind": "DECIDED", "date": date, "desc": f"Decision dated {date}", "actor": None,
                    "actor_id": None, "meeting": None, "provs": provs})
    for m in meetings:
        if m["id"] not in used_meetings:
            raw.append({"kind": "MEETING", "date": m["date"], "desc": f"Considered at {m['name']}",
                        "actor": None, "actor_id": None, "meeting": m["name"], "provs": m["provs"]})
    for item in reasons.values():
        raw.append({"kind": "REASON", "date": None, "desc": f"Reason: {item['name']}", "actor": None,
                    "actor_id": None, "meeting": None, "provs": item["provs"], "reason": item["name"]})
    for item in actions.values():
        assignees = sorted(set(item["assignees"]))
        dues = sorted(set(item["dues"]))
        desc = f"Action: {item['name']}"
        if assignees:
            desc += f" (assigned to {', '.join(assignees)})"
        if dues:
            desc += f" (due {', '.join(dues)})"
        raw.append({"kind": "ACTION", "date": None, "desc": desc, "actor": assignees[0] if assignees else None,
                    "actor_id": None, "meeting": None, "provs": item["provs"]})
    for item in related:
        raw.append({"kind": "RELATED_DECISION", "date": None, "desc": item["desc"], "actor": None,
                    "actor_id": None, "meeting": None, "provs": item["provs"]})

    dated = sorted((s for s in raw if s["date"]),
                   key=lambda s: (s["date"], _DATED_ORDER.get(s["kind"], 9), s["actor"] or "", s["desc"]))
    undated = sorted((s for s in raw if not s["date"]),
                     key=lambda s: (_UNDATED_ORDER.get(s["kind"], 9), s["actor"] or "", s["desc"]))
    steps = [TrailStep(date_iso=s["date"], kind=s["kind"], description=s["desc"], actor=s["actor"],
                       meeting=s["meeting"], decision_id=decision_id, decision_name=name,
                       provenance=_dedupe(s["provs"])) for s in dated + undated]
    return DecisionTrail(
        decision_id=decision_id, decision_name=name, status=_status_of(steps, superseded),
        first_date=next((s.date_iso for s in steps if s.date_iso), None), steps=steps,
        reasons=list(dict.fromkeys(s["reason"] for s in undated if s.get("reason"))),
    )


def _decision_events(G: nx.DiGraph, trail: DecisionTrail) -> List[Tuple[str, str]]:
    """(kind, date_iso) pairs of a decision. Every date comes from the trail or a graph relationship.

    Kinds: PROPOSED/APPROVED/REJECTED/DEFERRED (trail steps), DECIDED (DECIDED_ON),
    MEETING (DECIDED_AT meeting date), DUE (deadline of an action the decision led to).
    """
    events = [(s.kind, s.date_iso) for s in trail.steps
              if s.date_iso and s.kind in ("PROPOSED", "APPROVED", "REJECTED", "DEFERRED", "DECIDED")]
    for succ in sorted(G.successors(trail.decision_id)):
        date = G.nodes[succ].get("date_iso")
        for f in _facts(G, trail.decision_id, succ):
            if f["relation"] == "DECIDED_AT" and date:
                events.append(("MEETING", date))
            elif f["relation"] == "LED_TO":
                for tgt in sorted(G.successors(succ)):
                    due = G.nodes[tgt].get("date_iso")
                    if due and _has_rel(G, succ, tgt, "DUE_ON"):
                        events.append(("DUE", due))
    return sorted(set(events))


def _matches_spans(events: Sequence[Tuple[str, str]], spans: Sequence[Tuple[str, str]], kinds: Set[str]) -> bool:
    return any(kind in kinds and _in_spans(d, spans) for kind, d in events)


def _sort_trails(trails: List[DecisionTrail]) -> List[DecisionTrail]:
    return sorted(trails, key=lambda t: (t.first_date or "9999-99-99", t.decision_name, t.decision_id))


def _decision_ids(G: nx.DiGraph) -> List[str]:
    return [n for n in _real_nodes(G) if G.nodes[n]["type"] == "DECISION"]


def find_decisions_on_date(
    G: nx.DiGraph, date_iso: str, intent: Optional[str] = None
) -> List[DecisionTrail]:
    """Decisions with a dated event on `date_iso` ('YYYY-MM-DD', 'YYYY-MM' or 'YYYY'); full trails, chronological.

    intent: 'decide' (outcomes + decision meetings), 'propose', 'due' (action deadlines) or None
    (= decide + propose). Deadlines never count as decision dates unless intent='due'.
    A month-level event date only matches a month or year, never a single day inside it.
    """
    _validate_date_arg(date_iso, "date_iso")
    if intent is not None and intent not in _EVENT_KINDS:
        raise ValueError(f"intent must be one of {sorted(_EVENT_KINDS)} or None, got {intent!r}")
    kinds = _EVENT_KINDS[intent] if intent else _DEFAULT_KINDS
    spans = [_safe_span(date_iso)]
    found = []
    for n in _decision_ids(G or nx.DiGraph()):
        trail = get_decision_trail(G, n)
        if _matches_spans(_decision_events(G, trail), spans, kinds):  # type: ignore[arg-type]
            found.append(trail)
    return _sort_trails(found)


def list_decision_trails(
    G: nx.DiGraph, start_date: Optional[str] = None, end_date: Optional[str] = None
) -> List[DecisionTrail]:
    """All decisions chronologically, optionally limited to events inside [start_date, end_date].

    Boundaries may be days, months or years: a month start means its first day and a month end
    means its last day, so end_date='2024-04' includes 2024-04-30. start_date after end_date raises
    ValueError. Proposal, outcome and meeting events count; action deadlines do not.
    """
    lo = _safe_span(_validate_date_arg(start_date, "start_date"))[0] if start_date is not None else None  # type: ignore[index]
    hi = _safe_span(_validate_date_arg(end_date, "end_date"))[1] if end_date is not None else None  # type: ignore[index]
    if lo and hi and lo > hi:
        raise ValueError(f"start_date {start_date!r} is after end_date {end_date!r}")
    trails = [get_decision_trail(G, n) for n in _decision_ids(G or nx.DiGraph())]
    if lo or hi:
        span = [(lo or "0000-01-01", hi or "9999-12-31")]
        trails = [t for t in trails if _matches_spans(_decision_events(G, t), span, _DEFAULT_KINDS)]
    return _sort_trails(trails)


# ==========================================================================
# 7. Relevance model for questions
# ==========================================================================
_DIRECT_MIN = 0.5      # share of topic-term weight that must hit a decision's NAME ...
_SUPPORT_MIN = 0.6     # ... or its name + stated reasons/actions
_KEEP_RATIO = 0.75     # drop decisions scoring below this share of the best one
_EVIDENCE_LIMIT = 12


@dataclass
class _Profile:
    name: Set[str]
    support: Set[str]   # reasons and actions of the decision
    context: Set[str]   # acting bodies, meetings, assignees
    evidence: Set[str]  # words of its own source sentences


def _profile(G: nx.DiGraph, did: str) -> _Profile:
    p = _Profile(set(_name_tokens(G.nodes[did])), set(), set(), set())
    for prov in G.nodes[did].get("provenance", []):
        p.evidence |= set(content_tokens(prov.get("evidence") or ""))
    for succ in G.successors(did):
        sd = G.nodes[succ]
        if sd.get("source_document"):
            continue
        facts = _facts(G, did, succ)
        rels = {f["relation"] for f in facts}
        toks = set(_name_tokens(sd))
        for f in facts:
            for prov in f.get("provenance", []):
                p.evidence |= set(content_tokens(prov.get("evidence") or ""))
        if rels & {"JUSTIFIED_BY", "LED_TO"}:
            p.support |= toks
        if rels & (_ACTOR_RELS | {"DECIDED_AT"}):
            p.context |= toks
        if "LED_TO" in rels:
            for tgt in G.successors(succ):
                if _has_rel(G, succ, tgt, "ASSIGNED_TO"):
                    p.context |= set(_name_tokens(G.nodes[tgt]))
    return p


@dataclass
class _Match:
    direct: float = 0.0
    support: float = 0.0
    coverage: float = 0.0
    score: float = 0.0
    unmatched: List[str] = field(default_factory=list)


def _evaluate(prof: _Profile, terms: Sequence[str], index: _Index, phrase: str, name: str) -> _Match:
    total = sum(index.weight(t) for t in terms)
    direct = support = covered = 0.0
    unmatched = []
    for t in terms:
        w = index.weight(t)
        in_name = _term_in(t, prof.name)
        in_support = in_name or _term_in(t, prof.support)
        in_any = in_support or _term_in(t, prof.context) or _term_in(t, prof.evidence)
        direct += w if in_name else 0.0
        support += w if in_support else 0.0
        covered += w if in_any else 0.0
        if not in_any:
            unmatched.append(t)
    m = _Match(direct / total, support / total, covered / total, 0.0, unmatched)
    key = normalize_text(name)
    bonus = 2.0 if len(key) >= 6 and key in phrase else 0.0
    m.score = 3 * m.direct + 1.5 * m.support + m.coverage + bonus
    return m


def _find_mentions(G: nx.DiGraph, index: _Index, q_tokens: Set[str]) -> List[str]:
    """Entities (committees, departments, organizations, people, events) whose full name is in the question."""
    found = []
    for n in index.nodes:
        d = G.nodes[n]
        if d["type"] not in _MENTION_TYPES:
            continue
        etype = EntityType(d["type"])
        for nm in [d["name"]] + list(d.get("aliases", [])):
            toks = set(content_tokens(normalize_name(nm, etype)))
            if toks and toks <= q_tokens:
                found.append(n)
                break
    return found


def _linked_entities(G: nx.DiGraph, did: str) -> Set[str]:
    """Entities tied to a decision by outcome/proposal, decision meeting (+ who convened it) or assigned action."""
    linked: Set[str] = set()
    for succ in G.successors(did):
        rels = {f["relation"] for f in G[did][succ].get("facts", [])}
        if rels & _ACTOR_RELS:
            linked.add(succ)
        if "DECIDED_AT" in rels:
            linked.add(succ)
            linked |= {p for p in G.predecessors(succ) if _has_rel(G, p, succ, "CONVENED")}
        if "LED_TO" in rels:
            linked |= {t for t in G.successors(succ) if _has_rel(G, succ, t, "ASSIGNED_TO")}
    return linked


def _is_linked(G: nx.DiGraph, did: str, mention: str) -> bool:
    linked = _linked_entities(G, did)
    if mention in linked:
        return True
    if G.nodes[mention]["type"] == "ORGANIZATION":  # decisions of bodies that are PART_OF the organization
        return any(_has_rel(G, a, mention, "PART_OF") for a in linked if a in G)
    return False


def _related_decisions(G: nx.DiGraph, did: str) -> List[str]:
    """Explicit links only: FOLLOWS_UP / SUPERSEDES in either direction, or a shared action. One hop."""
    found: Set[str] = set()
    for succ in G.successors(did):
        rels = {f["relation"] for f in G[did][succ].get("facts", [])}
        if rels & {"FOLLOWS_UP", "SUPERSEDES"} and G.nodes[succ]["type"] == "DECISION":
            found.add(succ)
        if "LED_TO" in rels:
            found |= {p for p in G.predecessors(succ) if G.nodes[p]["type"] == "DECISION" and _has_rel(G, p, succ, "LED_TO")}
    for pred in G.predecessors(did):
        if G.nodes[pred]["type"] == "DECISION" and (
                _has_rel(G, pred, did, "FOLLOWS_UP") or _has_rel(G, pred, did, "SUPERSEDES")):
            found.add(pred)
    found.discard(did)
    return sorted(found)


def _overlap(text: str, terms: Sequence[str], index: _Index) -> float:
    if not terms:
        return 0.0
    toks = set(content_tokens(text))
    total = sum(index.weight(t) for t in terms)
    return sum(index.weight(t) for t in terms if _term_in(t, toks)) / total


def _step_has_kind(trail: DecisionTrail, kinds: Iterable[str]) -> bool:
    return any(s.kind in kinds and any(p.evidence for p in s.provenance) for s in trail.steps)


# ==========================================================================
# 8. retrieve_context
# ==========================================================================
def retrieve_context(
    G: nx.DiGraph,
    question: str,
    config: Optional[Config] = None,
    top_k: Optional[int] = None,
    min_coverage: Optional[float] = None,
    max_decisions: Optional[int] = None,
) -> RetrievalResult:
    """Find decision trails, entities and evidence relevant to `question`.

    `sufficient` is False when the graph does not substantiate the question: nothing matches the
    topic, the named entity is not linked to the topic, no decision has a matching dated event, the
    needed kind of fact (reason / outcome / proposal / deadline) is missing, a question term does not
    exist in the graph, or the best decision covers too little of the question.
    Explicit limits are validated (0 is rejected, not replaced by a default).
    """
    if not isinstance(question, str):
        raise TypeError("question must be a string")
    cfg = config if config is not None else Config()
    top_k = _check_limit(cfg.top_k if top_k is None else top_k, "top_k")
    max_decisions = _check_limit(cfg.max_decisions if max_decisions is None else max_decisions, "max_decisions")
    min_coverage = cfg.min_coverage if min_coverage is None else min_coverage
    if isinstance(min_coverage, bool) or not isinstance(min_coverage, (int, float)) or not 0 <= min_coverage <= 1:
        raise ValueError(f"min_coverage must be between 0 and 1, got {min_coverage!r}")

    def fail(reason: str, **extra: Any) -> RetrievalResult:
        return RetrievalResult(question=question, sufficient=False, reason=reason, **extra)

    if G is None or G.number_of_nodes() == 0:
        return fail("The knowledge graph is empty.")
    q = _parse_question(question)
    if not q.text and not q.spans and not q.years:
        return fail("The question is empty." if not question.strip() else "The question contains no searchable words.")
    if q.date_error:
        return fail(q.date_error)

    index = _Index(G)
    spans = list(q.spans)
    topic = list(q.topic)
    for y in q.years:  # a year is a topic if a decision/event name contains it ("Vision 2030"), else a date range
        if y in index.year_vocab:
            topic.append(y)
        else:
            span = _safe_span(y)
            spans.append(span)  # type: ignore[arg-type]
    spans = list(dict.fromkeys(spans))

    mentions = _find_mentions(G, index, q.tokens)
    mention_tokens: Set[str] = set()
    for m in mentions:
        mention_tokens |= set(content_tokens(normalize_name(G.nodes[m]["name"], EntityType(G.nodes[m]["type"]))))
    terms = [t for t in dict.fromkeys(topic) if t not in mention_tokens]
    foreign = [t for t in terms if not index.known(t)]
    if foreign:
        return fail("Question terms not found in the knowledge graph: " + ", ".join(foreign) + ".")

    decisions = _decision_ids(G)
    trails: Dict[str, DecisionTrail] = {}

    def trail_of(did: str) -> DecisionTrail:
        if did not in trails:
            trails[did] = get_decision_trail(G, did)
        return trails[did]

    # ---- 1. topic match (direct first) --------------------------------------------------
    matches: Dict[str, _Match] = {}
    if terms:
        for did in decisions:
            m = _evaluate(_profile(G, did), terms, index, q.text, G.nodes[did]["name"])
            if m.direct >= _DIRECT_MIN or m.support >= _SUPPORT_MIN:
                matches[did] = m
        if not matches:
            return fail("No decision matches the topic terms: " + ", ".join(terms) + ".")
    elif mentions or spans or q.listing:
        matches = {did: _Match(coverage=1.0) for did in decisions}
    else:
        return fail("The question does not name a topic, an entity or a date to search for.")

    # ---- 2. filters: entity, date, kind of fact ----------------------------------------
    # A filter may not "rescue" the question with a weaker topic match: if the best topic match
    # is removed, the question is not substantiated and we say so instead of returning a lookalike.
    def narrow(current: Dict[str, _Match], keep: Any) -> Optional[Dict[str, _Match]]:
        kept = {d: m for d, m in current.items() if keep(d)}
        if not kept:
            return None
        if terms and max(m.direct for m in kept.values()) < max(m.direct for m in current.values()) - 1e-9:
            return None
        return kept

    if mentions:
        kept = narrow(matches, lambda d: any(_is_linked(G, d, e) for e in mentions))
        if kept is None:
            names = ", ".join(G.nodes[e]["name"] for e in mentions)
            return fail(f"No decision matching the question is linked to {names}.")
        matches = kept
    fallback_events: List[str] = []
    if spans:
        kept = narrow(matches, lambda d: _matches_spans(_decision_events(G, trail_of(d)), spans, q.kinds))
        if kept is None:
            if not q.explicit_intent and not terms and not mentions:
                fallback_events = [n for n in index.nodes if G.nodes[n]["type"] in ("MEETING", "EVENT")
                                   and _in_spans(G.nodes[n].get("date_iso"), spans)]
            if not fallback_events:
                return fail("No decision with a matching dated event was found for " + ", ".join(
                    a if a == b else f"{a}..{b}" for a, b in spans) + ".")
            matches = {}
        else:
            matches = kept
    if matches:
        checks: List[Tuple[bool, Any, str]] = [
            (q.wants_reason, lambda d: _step_has_kind(trail_of(d), ["REASON"]),
             "The matching decision has no stated reason in the graph."),
        ]
        if not spans:  # with a date, the dated-event filter above already requires the right kind of event
            checks += [
                (q.wants_proposal, lambda d: _step_has_kind(trail_of(d), ["PROPOSED"]),
                 "No proposal is recorded for the matching decision."),
                (q.wants_outcome, lambda d: _step_has_kind(trail_of(d), _OUTCOME_KINDS),
                 "No approval, rejection or deferral is recorded for the matching decision."),
                (q.wants_due, lambda d: any(k == "DUE" for k, _ in _decision_events(G, trail_of(d))),
                 "No action deadline is recorded for the matching decision."),
                (not terms and not mentions and bool(q.outcome_kinds),  # "which decisions were rejected?"
                 lambda d: _step_has_kind(trail_of(d), q.outcome_kinds), "No decision with that outcome is recorded."),
            ]
        for wanted, keep, message in checks:
            if wanted:
                kept = narrow(matches, keep)
                if kept is None:
                    return fail(message)
                matches = kept

    # ---- 3. rank, cut, enrich ----------------------------------------------------------
    ranked = sorted(matches, key=lambda d: (-matches[d].score, trail_of(d).first_date or "9999-99-99",
                                            G.nodes[d]["name"], d))
    if terms and ranked:
        top_score = matches[ranked[0]].score
        ranked = [d for d in ranked if matches[d].score >= _KEEP_RATIO * top_score]
    selected = ranked[:max_decisions]
    if q.history:  # explicit links only; never merely shared committees or meetings
        for d in list(selected):
            for rel in _related_decisions(G, d):
                if rel not in selected and len(selected) < max_decisions:
                    selected.append(rel)
    chosen = [trail_of(d) for d in selected]

    # ---- 4. sufficiency: judged on the best single decision --------------------------------
    best = matches[selected[0]] if selected else None
    coverage = best.coverage if best else (1.0 if fallback_events else 0.0)
    event_evidence: List[Provenance] = []
    for n in fallback_events:
        event_evidence += _provs(G.nodes[n].get("provenance", []))
        for succ in G.successors(n):
            if _has_rel(G, n, succ, "HELD_ON"):
                event_evidence += _provs(next(f for f in _facts(G, n, succ) if f["relation"] == "HELD_ON")
                                         .get("provenance", []))
    evidence = _rank_evidence(G, chosen, terms, index, spans, q) if chosen else \
        [p for p in sorted(_dedupe(event_evidence), key=lambda p: (str(p.document_id), p.page or 0, p.chunk_id or ""))
         if p.evidence][:_EVIDENCE_LIMIT]

    # ---- 5. entities (topic entities first; date nodes get reserved, not unlimited, slots) ----
    scored: Dict[str, float] = {}
    for rank, d in enumerate(selected):
        scored[d] = round((matches[d].score if d in matches else 0.5) + 1.0 / (1 + rank), 3)
    for e in mentions:
        if any(_is_linked(G, d, e) for d in selected):
            scored[e] = max(scored.get(e, 0.0), 2.0)
    for n in fallback_events:
        scored[n] = 1.0
    date_nodes = [n for n in index.nodes if G.nodes[n]["type"] == "DATE" and spans
                  and _in_spans(G.nodes[n].get("date_iso"), spans)]
    matched_dates = sorted({G.nodes[n]["date_iso"] for n in date_nodes})
    topic_ids = sorted(scored, key=lambda n: (-scored[n], G.nodes[n]["name"], n))
    date_slots = min(len(date_nodes), max(1, top_k // 4)) if date_nodes else 0
    chosen_ids = topic_ids[: max(top_k - date_slots, 0)]
    chosen_ids += sorted(date_nodes)[: top_k - len(chosen_ids)]
    entities = [ScoredEntity(id=n, name=G.nodes[n]["name"], type=G.nodes[n]["type"], score=scored.get(n, 1.0))
                for n in chosen_ids]

    reason = None
    sufficient = bool(evidence) and bool(chosen or fallback_events) and coverage >= min_coverage
    if not evidence:
        reason = "The matching decision has no source evidence in the graph."
    elif coverage < min_coverage:
        reason = (f"Only {coverage:.0%} of the question's key terms were found in the best matching decision"
                  + (f" (missing: {', '.join(best.unmatched)})." if best and best.unmatched else "."))
    elif best and best.unmatched:
        reason = "Some question terms were not found in the evidence: " + ", ".join(best.unmatched) + "."
    return RetrievalResult(
        question=question, query_tokens=terms, matched_dates=matched_dates, entities=entities,
        decisions=chosen, evidence=evidence, coverage=round(coverage, 3), sufficient=sufficient, reason=reason,
    )


def _rank_evidence(
    G: nx.DiGraph, trails: Sequence[DecisionTrail], terms: Sequence[str], index: _Index,
    spans: Sequence[Tuple[str, str]], q: _Question,
) -> List[Provenance]:
    """Evidence of the selected trails only, ranked by relevance. The best item of every decision is kept."""
    best: Dict[Tuple[Any, ...], Tuple[float, int, Provenance]] = {}

    def consider(p: Provenance, score: float, rank: int) -> None:
        if p.evidence and (p.key() not in best or score > best[p.key()][0]):
            best[p.key()] = (score, rank, p)

    for rank, trail in enumerate(trails):
        base = 1.0 / (1 + rank)
        for p in _provs(G.nodes[trail.decision_id].get("provenance", [])):
            consider(p, base + 0.8 * _overlap(p.evidence or "", terms, index), rank)
        for s in trail.steps:
            bonus = 0.0
            if s.kind in _OUTCOME_KINDS or s.kind == "PROPOSED":
                bonus += 0.4
            if s.kind == "REASON" and q.wants_reason:
                bonus += 0.6
            if s.kind == "ACTION" and q.wants_due:
                bonus += 0.6
            if spans and s.date_iso and _in_spans(s.date_iso, spans):
                bonus += 0.8
            for p in s.provenance:
                consider(p, base + bonus + 0.8 * _overlap(p.evidence or "", terms, index), rank)
    order = sorted(best.values(), key=lambda t: (-t[0], t[1], str(t[2].document_id), t[2].page or 0,
                                                 t[2].chunk_id or "", t[2].evidence or ""))
    picked: List[Provenance] = []
    for rank in range(len(trails)):  # guarantee: each decision's own best evidence survives the limit
        top = next((p for _, r, p in order if r == rank), None)
        if top is not None and top not in picked:
            picked.append(top)
    for _, _, p in order:
        if len(picked) >= _EVIDENCE_LIMIT:
            break
        if p not in picked:
            picked.append(p)
    rank_of = {p.key(): i for i, (_, _, p) in enumerate(order)}
    return sorted(picked, key=lambda p: rank_of[p.key()])
