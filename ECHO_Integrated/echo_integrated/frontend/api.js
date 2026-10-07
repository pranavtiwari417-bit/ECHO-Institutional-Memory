/**
 * ECHO: Institutional Memory & Decision Intelligence Engine
 * Dedicated API Service Layer Architecture Module
 * Connects frontend components to real backend server (Node.js/Express or Python FastAPI).
 * Includes transparent fallback persistence adapter for standalone client execution.
 */

const API_BASE_URL = window.ENV_API_URL || '/api';

class EchoApiService {
    constructor(baseUrl = API_BASE_URL) {
        this.baseUrl = baseUrl;
        this.isBackendAvailable = false;
        this.checkBackendHealth();
    }

    async checkBackendHealth() {
        try {
            const controller = new AbortController();
            const timeoutId = setTimeout(() => controller.abort(), 1200);
            const res = await fetch(`${this.baseUrl}/health`, { signal: controller.signal });
            clearTimeout(timeoutId);
            this.isBackendAvailable = res.ok;
            if (this.isBackendAvailable) {
                console.info(`[ECHO API] Connected to live backend server at ${this.baseUrl}`);
                updateBackendStatusUI(true);
            }
        } catch (e) {
            this.isBackendAvailable = false;
            console.info(`[ECHO API] Live backend offline at ${this.baseUrl}. Operating in Fallback Client Mode.`);
            updateBackendStatusUI(false);
        }
    }

    // 1. UPLOAD DOCUMENT (POST /api/documents/upload)
    async uploadDocument(file) {
        if (this.isBackendAvailable) {
            try {
                const formData = new FormData();
                formData.append('file', file);

                const response = await fetch(`${this.baseUrl}/documents/upload`, {
                    method: 'POST',
                    body: formData
                });

                if (!response.ok) throw new Error(`HTTP Error ${response.status}`);
                return await response.json();
            } catch (err) {
                console.warn('[ECHO API] Upload endpoint error, falling back:', err);
            }
        }

        // Fallback local document upload simulation object
        const docId = `doc_${Date.now()}`;
        return {
            documentId: docId,
            status: 'processing',
            stage: 1,
            fileName: file.name,
            fileSize: file.size,
            fileType: file.name.split('.').pop().toLowerCase()
        };
    }

    // 2. POLL DOCUMENT PROCESSING STATUS (GET /api/documents/{id}/status)
    async getDocumentStatus(documentId, progressStep = 1) {
        if (this.isBackendAvailable) {
            try {
                const response = await fetch(`${this.baseUrl}/documents/${documentId}/status`);
                if (response.ok) return await response.json();
            } catch (err) {
                console.warn('[ECHO API] Status polling error:', err);
            }
        }

        // Fallback simulated progress status response
        let progress = 20;
        let stage = 'Step 1 of 3: Extracting Text & Metadata...';
        let isComplete = false;

        if (progressStep === 2) {
            progress = 65;
            stage = 'Step 2 of 3: Building Knowledge Graph Entities...';
        } else if (progressStep >= 3) {
            progress = 100;
            stage = 'Step 3 of 3: Vector Search Indexing Complete!';
            isComplete = true;
        }

        return {
            documentId,
            progress,
            stage,
            isComplete
        };
    }

    normalizeDocument(doc) {
        const metadata = doc.metadata || {};
        const entities = metadata.entities || [];
        return {
            id: String(doc.id),
            name: doc.filename || doc.name || 'Untitled document',
            date: doc.created_at || doc.date || '',
            timestamp: Date.parse(doc.created_at || '') || Date.now(),
            size: metadata.size || doc.size || '—',
            type: (doc.file_type || doc.type || '').replace('.', ''),
            category: metadata.category || doc.category || 'Operations',
            summary: metadata.summary || doc.summary || (doc.content ? doc.content.slice(0, 240) + (doc.content.length > 240 ? '…' : '') : ''),
            entities: entities.map(e => typeof e === 'string' ? e : (e.name || e.text || 'Entity')),
            status: metadata.status || doc.status || 'Indexed & Processed'
        };
    }

    // 3. FETCH DOCUMENT REPOSITORY (GET /api/documents)
    async getDocuments(params = {}) {
        if (this.isBackendAvailable) {
            try {
                const queryString = new URLSearchParams(params).toString();
                const response = await fetch(`${this.baseUrl}/documents?${queryString}`);
                if (response.ok) {
                    const payload = await response.json();
                    return (payload.documents || []).map(this.normalizeDocument);
                }
            } catch (err) {
                console.warn('[ECHO API] Fetch documents endpoint error:', err);
            }
        }

        return App ? App.documents : [];
    }

    // 4. DELETE DOCUMENT RECORD (DELETE /api/documents/{id})
    async deleteDocument(documentId) {
        if (this.isBackendAvailable) {
            try {
                const response = await fetch(`${this.baseUrl}/documents/${documentId}`, {
                    method: 'DELETE'
                });
                if (response.ok) return await response.json();
            } catch (err) {
                console.warn('[ECHO API] Delete document endpoint error:', err);
            }
        }

        if (App) App.deleteDocument(documentId);
        return { success: true, documentId };
    }

    // 5. AI SEMANTIC SEARCH (GET /api/search?query=...)
    async searchDocuments(query = '', filters = {}) {
        if (this.isBackendAvailable) {
            try {
                const queryParams = new URLSearchParams({ q: query, ...filters });
                const response = await fetch(`${this.baseUrl}/search?${queryParams}`);
                if (response.ok) {
                    const payload = await response.json();
                    return (payload.results || []).map(this.normalizeDocument);
                }
            } catch (err) {
                console.warn('[ECHO API] Search endpoint error:', err);
            }
        }

        const q = query.toLowerCase();
        if (!App) return [];
        return App.documents.filter(doc => {
            if (filters.category && filters.category !== 'all' && doc.category.toLowerCase() !== filters.category.toLowerCase()) return false;
            if (filters.type && filters.type !== 'all' && doc.type.toLowerCase() !== filters.type.toLowerCase()) return false;
            if (!q) return true;
            return doc.name.toLowerCase().includes(q) || doc.summary.toLowerCase().includes(q) || doc.entities.some(e => e.toLowerCase().includes(q));
        });
    }

    // 6. KNOWLEDGE GRAPH TOPOLOGY (GET /api/graph/topology)
    async getGraphTopology() {
        if (this.isBackendAvailable) {
            try {
                const response = await fetch(`${this.baseUrl}/graph/topology`);
                if (response.ok) return await response.json();
            } catch (err) {
                console.warn('[ECHO API] Graph topology endpoint error:', err);
            }
        }

        return App ? App.getGraphTopology() : { nodes: [], links: [] };
    }

    // 7. USER PROFILE (GET /api/user/profile)
    async getUserProfile() {
        if (this.isBackendAvailable) {
            try {
                const response = await fetch(`${this.baseUrl}/user/profile`);
                if (response.ok) return await response.json();
            } catch (err) {}
        }

        return {
            name: "Dr. Alex Mercer",
            role: "Decision Intelligence Analyst",
            email: "alex.mercer@echo-intelligence.io",
            organization: "ECHO Intelligence Labs",
            clearance: "Admin Clearance"
        };
    }

    // 8. NOTIFICATIONS (GET /api/notifications)
    async getNotifications() {
        if (this.isBackendAvailable) {
            try {
                const response = await fetch(`${this.baseUrl}/notifications`);
                if (response.ok) return await response.json();
            } catch (err) {}
        }

        return App ? App.notifications : [];
    }
}

function updateBackendStatusUI(isLive) {
    const badge = document.getElementById('backend-status-indicator');
    if (badge) {
        if (isLive) {
            badge.className = 'text-[11px] font-bold text-emerald-600 bg-emerald-50 px-2 py-0.5 rounded-full flex items-center gap-1';
            badge.innerHTML = '<span class="w-2 h-2 rounded-full bg-emerald-500 animate-pulse"></span> REST API Server Online';
        } else {
            badge.className = 'text-[11px] font-bold text-indigo-600 bg-indigo-50 px-2 py-0.5 rounded-full flex items-center gap-1';
            badge.innerHTML = '<span class="w-2 h-2 rounded-full bg-indigo-500"></span> Client Fallback Storage';
        }
    }
}

// Global Export Singleton
window.apiService = new EchoApiService();
