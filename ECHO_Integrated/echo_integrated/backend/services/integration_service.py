"""ECHO integration layer: upload -> document processing -> Knowledge AI -> DB/graph."""
from __future__ import annotations
import threading, uuid
from datetime import datetime
from pathlib import Path
from typing import Any
from services.database import add_decision, add_document, add_entity, add_relationship
from services.graph_service import rebuild_graph
ROOT = Path(__file__).resolve().parents[2]
UPLOAD_DIR = ROOT / "storage" / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
_jobs: dict[str, dict[str, Any]] = {}
_lock = threading.Lock()
_nlp = None
_nlp_lock = threading.Lock()

def _set_job(job_id: str, **values: Any) -> None:
    with _lock: _jobs.setdefault(job_id, {}).update(values)
def get_job(job_id: str):
    with _lock:
        return dict(_jobs[job_id]) if job_id in _jobs else None

def _get_nlp():
    global _nlp
    if _nlp is not None: return _nlp
    with _nlp_lock:
        if _nlp is not None: return _nlp
        try:
            from document_processing import load_nlp_model
            _nlp = load_nlp_model()
        except Exception:
            try:
                import spacy
                _nlp = spacy.blank("en")
            except Exception: _nlp = None
        return _nlp

def _extract_file(path: Path):
    ext = path.suffix.lower()
    if ext == ".pdf":
        from document_processing import process_document
        result = process_document(path, _get_nlp())
        return result["cleaned_text"], result["structured_data"].get("entities", [])
    if ext in {".txt", ".md"}:
        return path.read_text(encoding="utf-8", errors="ignore"), []
    if ext in {".png", ".jpg", ".jpeg"}:
        from PIL import Image
        import pytesseract
        return pytesseract.image_to_string(Image.open(path)), []
    raise ValueError(f"Unsupported file type: {ext}")

def _run_knowledge_ai(document_id: int, filename: str, text: str):
    try:
        from knowledge_ai import SourceDocument, extract_document
        result = extract_document(SourceDocument(document_id=str(document_id), filename=filename, text=text))
        return result.model_dump()
    except Exception as exc:
        return {"mode":"unavailable", "errors":[str(exc)], "entities":[], "relationships":[]}

def _persist_ai(document_id: int, ai_result: dict):
    for ent in ai_result.get("entities") or []:
        name = str(ent.get("name", "")).strip()
        if not name: continue
        etype = ent.get("type", "unknown")
        etype = getattr(etype, "value", etype)
        try: add_entity(name, str(etype), document_id, {"source":"knowledge_ai", "date_iso":ent.get("date_iso")})
        except Exception: pass
    for rel in ai_result.get("relationships") or []:
        src = str(rel.get("source_id", "")); tgt = str(rel.get("target_id", ""))
        relation = getattr(rel.get("relation", "related_to"), "value", rel.get("relation", "related_to"))
        src_name = src.split(":", 1)[-1]; tgt_name = tgt.split(":", 1)[-1]
        if src_name and tgt_name:
            try: add_relationship(src_name, str(relation), tgt_name, document_id, {"source":"knowledge_ai"})
            except Exception: pass
    for ent in ai_result.get("entities") or []:
        if str(ent.get("type", "")).upper().endswith("DECISION"):
            try: add_decision(ent.get("name", "Decision"), ent.get("description", ""), document_id=document_id, metadata={"source":"knowledge_ai", "date_iso":ent.get("date_iso")})
            except Exception: pass

def _process_job(job_id, document_id, path, filename, size):
    try:
        _set_job(job_id, progress=20, stage="Step 1 of 3: Extracting Text & Metadata...")
        text, nlp_entities = _extract_file(path)
        if not text.strip(): raise RuntimeError("No text could be extracted from the uploaded document.")
        _set_job(job_id, progress=55, stage="Step 2 of 3: Building Knowledge Graph Entities...")
        ai_result = _run_knowledge_ai(document_id, filename, text)
        _persist_ai(document_id, ai_result)
        if not ai_result.get("entities"):
            for ent in nlp_entities:
                name = str(ent.get("text", "")).strip()
                if name:
                    try: add_entity(name, ent.get("type", "unknown"), document_id, {"source":"document_processing"})
                    except Exception: pass
        metadata = {"size":f"{size/(1024*1024):.1f} MB", "status":"Indexed & Processed", "category":"Operations", "summary":text[:240]+("…" if len(text)>240 else ""), "entities":[e.get("name") for e in ai_result.get("entities",[]) if e.get("name")], "knowledge_ai_mode":ai_result.get("mode","unavailable")}
        from services.database import update_document
        update_document(document_id, content=text, metadata=metadata)
        rebuild_graph()
        _set_job(job_id, progress=100, stage="Step 3 of 3: Knowledge Graph Indexing Complete!", isComplete=True, status="complete")
    except Exception as exc:
        _set_job(job_id, progress=100, stage=f"Processing failed: {exc}", isComplete=True, status="failed", error=str(exc))

def start_document_job(file_storage):
    filename = Path(file_storage.filename or "document").name
    ext = Path(filename).suffix.lower()
    if ext not in {".pdf",".png",".jpg",".jpeg",".txt",".md"}: raise ValueError("Supported files: PDF, PNG, JPG, JPEG, TXT and MD")
    job_id = uuid.uuid4().hex
    destination = UPLOAD_DIR / f"{job_id}{ext}"
    file_storage.save(destination)
    size = destination.stat().st_size
    document_id = add_document(filename, title=Path(filename).stem, file_path=str(destination.relative_to(ROOT)), file_type=ext.lstrip("."), created_at=datetime.now().isoformat(timespec="seconds"), metadata={"status":"Processing","size":f"{size/(1024*1024):.1f} MB"})
    _set_job(job_id, documentId=str(document_id), progress=10, stage="Initiating document upload...", isComplete=False, status="processing", fileName=filename)
    threading.Thread(target=_process_job, args=(job_id, document_id, destination, filename, size), daemon=True).start()
    return job_id, document_id
