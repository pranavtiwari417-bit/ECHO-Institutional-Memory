# ECHO — Integrated Full-Stack Application

ECHO is packaged as one web application. The Flask server serves the frontend and exposes the API from the same origin, so the browser does not need a separate frontend/backend connection.

## Architecture

Browser → Flask → SQLite / Document Processing / Knowledge AI / NetworkX Knowledge Graph

## Run locally

### Windows
Double-click `run.bat`.

### macOS/Linux
Run `./run.sh`.

Then open `http://127.0.0.1:5000`.

The frontend uses `/api` automatically; no API URL editing is required.

## Optional AI
The supplied Knowledge AI package can use local Ollama with Gemma 3 4B. If Ollama/model is unavailable, document processing and storage still work and the application keeps the document-processing/NLP fallback path.

## Optional OCR
Scanned PDFs/images require Tesseract OCR to be installed on the host machine. Normal text PDFs do not need Tesseract.

## Deployment
Deploy this project as one Python web service. The same service serves the frontend and `/api/*` routes, which is the website-style single-origin setup.
