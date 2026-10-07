"""ECHO - single-origin full-stack web application entry point."""
from __future__ import annotations
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
BACKEND_DIR=Path(__file__).resolve().parent
for p in (str(ROOT),str(BACKEND_DIR)):
    if p not in sys.path: sys.path.insert(0,p)
from flask import Flask,jsonify,request,send_from_directory
from services.database import initialize_database,get_all_documents
from services.graph_service import initialize_graph,graph_to_dict
from routes.documents_routes import documents_bp
from routes.query_routes import query_bp
from routes.search_routes import search_bp
from services.integration_service import start_document_job,get_job
FRONTEND_DIR=ROOT/"frontend"

def create_app():
    app=Flask(__name__,static_folder=str(FRONTEND_DIR),static_url_path="")
    app.config["MAX_CONTENT_LENGTH"]=20*1024*1024
    app.config["JSON_SORT_KEYS"]=False
    initialize_database(); initialize_graph()
    app.register_blueprint(documents_bp); app.register_blueprint(query_bp); app.register_blueprint(search_bp)
    @app.get("/")
    def frontend(): return send_from_directory(FRONTEND_DIR,"index.html")
    @app.get("/api/health")
    def health(): return jsonify(success=True,status="healthy",database="connected",knowledge_graph="initialized")
    @app.post("/api/documents/upload")
    def upload_document():
        file=request.files.get("file")
        if file is None or not file.filename: return jsonify(success=False,error="No file uploaded."),400
        try:
            job_id,document_id=start_document_job(file)
            return jsonify(success=True,documentId=job_id,databaseDocumentId=document_id,status="processing",fileName=file.filename),202
        except ValueError as exc: return jsonify(success=False,error=str(exc)),400
        except Exception as exc: return jsonify(success=False,error=str(exc)),500
    @app.get("/api/documents/<job_id>/status")
    def document_status(job_id):
        job=get_job(job_id)
        if not job: return jsonify(success=False,error="Processing job not found."),404
        return jsonify(success=True,**job)
    @app.get("/api/graph/topology")
    def graph_topology():
        from services.graph_service import load_graph
        data = graph_to_dict(load_graph())
        data["links"] = data.get("edges", [])
        return jsonify(data)
    @app.get("/api/user/profile")
    def profile(): return jsonify(name="Dr. Alex Mercer",role="Decision Intelligence Analyst",email="alex.mercer@echo-intelligence.io",organization="ECHO Intelligence Labs",clearance="Admin Clearance")
    @app.get("/api/notifications")
    def notifications():
        return jsonify([{"id":f"doc-{d['id']}","title":"Document Indexed","message":f"{d['filename']} is available in institutional memory.","time":d.get("created_at",""),"read":False,"type":"success"} for d in get_all_documents(limit=10)])
    @app.errorhandler(404)
    def not_found(error):
        if not request.path.startswith("/api/") and "." not in Path(request.path).name: return send_from_directory(FRONTEND_DIR,"index.html")
        return jsonify(success=False,error="Not found"),404
    return app
app=create_app()
if __name__=="__main__": app.run(host="0.0.0.0",port=5000,debug=False)
