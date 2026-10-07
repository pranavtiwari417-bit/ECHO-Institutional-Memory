/**
 * ECHO: Institutional Memory & Decision Intelligence Engine
 * Master Application Controller Script
 * Integrated with API Service Layer (api.js) & Real-Time Status Polling Engine
 */

// --- INITIAL DEFAULT DATASETS ---
const INITIAL_DOCUMENTS = [
    {
        id: "doc_1",
        name: "Q3 Financial Strategy.pdf",
        date: "2026-09-15 14:30",
        timestamp: 1789462800000,
        size: "2.4 MB",
        type: "pdf",
        category: "Financial",
        summary: "Outlines Q3 revenue targets of $14.2M (+18% YoY), strategic budget allocation for R&D expansion, cost optimization initiatives across cloud infrastructure, and net margin projections of 32%.",
        entities: ["Q3 Revenue ($14.2M)", "R&D Expansion", "Cost Optimization", "Margin Target (32%)", "CFO Board Report"],
        status: "Indexed & Processed"
    },
    {
        id: "doc_2",
        name: "System Architecture.png",
        date: "2026-09-18 09:15",
        timestamp: 1789703700000,
        size: "1.8 MB",
        type: "png",
        category: "Technical",
        summary: "Technical architectural blueprint detailing microservices deployment, Kafka event-driven message bus, PostgreSQL primary database cluster, Redis cache layer, and Kubernetes orchestrator.",
        entities: ["Microservices", "Kafka Event Bus", "PostgreSQL Cluster", "Redis Cache", "Kubernetes Orchestrator"],
        status: "Indexed & Processed"
    },
    {
        id: "doc_3",
        name: "Market Research.pdf",
        date: "2026-09-22 16:45",
        timestamp: 1790077500000,
        size: "3.1 MB",
        type: "pdf",
        category: "Research",
        summary: "Comprehensive market study analyzing enterprise AI adoption trends, decision intelligence TAM expansion ($24B by 2028), competitor positioning analysis, and customer sentiment metrics.",
        entities: ["AI Adoption Trends", "Decision Intelligence", "$24B Market Size", "Competitor Benchmark"],
        status: "Indexed & Processed"
    }
];

const INITIAL_NOTIFICATIONS = [
    {
        id: "notif_1",
        title: "Document Processed",
        message: "Document 'Q3 Financial Strategy.pdf' processed successfully into Knowledge Graph.",
        time: "10m ago",
        read: false,
        type: "success"
    },
    {
        id: "notif_2",
        title: "Entities Mapped",
        message: "18 new knowledge entities mapped in Knowledge Graph topology.",
        time: "45m ago",
        read: false,
        type: "info"
    },
    {
        id: "notif_3",
        title: "Vector Index Active",
        message: "System initialized with decision memory vectors and 99.8% precision.",
        time: "2h ago",
        read: false,
        type: "system"
    }
];

// --- CENTRAL APPLICATION STATE STORE ---
class EchoAppState {
    constructor() {
        this.documents = [];
        this.notifications = [];
        this.activities = [];
        this.activeTab = 'home';
        this.graphSimulation = null;
        this.loadFromStorage();
    }

    loadFromStorage() {
        try {
            const storedDocs = localStorage.getItem('ECHO_INTELLIGENCE_DATA');
            if (storedDocs) {
                this.documents = JSON.parse(storedDocs);
            } else {
                this.documents = [...INITIAL_DOCUMENTS];
                this.saveDocsToStorage();
            }

            const storedNotifs = localStorage.getItem('ECHO_NOTIFICATIONS');
            if (storedNotifs) {
                this.notifications = JSON.parse(storedNotifs);
            } else {
                this.notifications = [...INITIAL_NOTIFICATIONS];
                this.saveNotifsToStorage();
            }
        } catch (e) {
            console.warn('Storage read error:', e);
            this.documents = [...INITIAL_DOCUMENTS];
            this.notifications = [...INITIAL_NOTIFICATIONS];
        }

        this.generateActivitiesTimeline();
    }

    saveDocsToStorage() {
        try {
            localStorage.setItem('ECHO_INTELLIGENCE_DATA', JSON.stringify(this.documents));
        } catch (e) {}
    }

    saveNotifsToStorage() {
        try {
            localStorage.setItem('ECHO_NOTIFICATIONS', JSON.stringify(this.notifications));
        } catch (e) {}
    }

    addDocument(docObj) {
        this.documents.unshift(docObj);
        this.saveDocsToStorage();

        this.addNotification({
            id: `notif_${Date.now()}`,
            title: "Document Processed",
            message: `Document '${docObj.name}' processed successfully into Knowledge Graph.`,
            time: "Just now",
            read: false,
            type: "success"
        });

        this.generateActivitiesTimeline();
    }

    addNotification(notifObj) {
        this.notifications.unshift(notifObj);
        this.saveNotifsToStorage();
        renderNotifications();
    }

    markAllNotificationsRead() {
        this.notifications.forEach(n => n.read = true);
        this.saveNotifsToStorage();
        renderNotifications();
    }

    clearNotifications() {
        this.notifications = [];
        this.saveNotifsToStorage();
        renderNotifications();
    }

    deleteDocument(docId) {
        this.documents = this.documents.filter(d => d.id !== docId);
        this.saveDocsToStorage();
        this.generateActivitiesTimeline();
    }

    resetToDefault() {
        this.documents = [...INITIAL_DOCUMENTS];
        this.notifications = [...INITIAL_NOTIFICATIONS];
        this.saveDocsToStorage();
        this.saveNotifsToStorage();
        this.generateActivitiesTimeline();
        renderNotifications();
    }

    clearAll() {
        this.documents = [];
        this.notifications = [];
        this.saveDocsToStorage();
        this.saveNotifsToStorage();
        this.generateActivitiesTimeline();
        renderNotifications();
    }

    generateActivitiesTimeline() {
        this.activities = [];
        this.documents.forEach(doc => {
            this.activities.push({
                type: 'upload',
                title: `Uploaded document "${doc.name}"`,
                subtitle: `Extracted ${doc.entities.length} entities • Category: ${doc.category}`,
                date: doc.date,
                timestamp: doc.timestamp
            });
        });

        this.activities.push({
            type: 'graph',
            title: 'Knowledge Graph Topology Initialized',
            subtitle: 'Linked document nodes and neural memory entities',
            date: '2026-09-15 14:00',
            timestamp: 1789461000000
        });

        this.activities.sort((a, b) => b.timestamp - a.timestamp);
    }

    getGraphTopology() {
        const nodesMap = new Map();
        const links = [];

        this.documents.forEach(doc => {
            const docNodeId = doc.id;
            if (!nodesMap.has(docNodeId)) {
                nodesMap.set(docNodeId, {
                    id: docNodeId,
                    label: doc.name,
                    type: 'document',
                    category: doc.category,
                    date: doc.date,
                    color: '#3B82F6',
                    radius: 16,
                    desc: doc.summary
                });
            }

            doc.entities.forEach(entName => {
                let entType = 'entity';
                let color = '#8B5CF6';

                if (entName.includes('$') || entName.includes('%') || entName.match(/\d+/)) {
                    entType = 'metric';
                    color = '#10B981';
                } else if (entName.includes('CFO') || entName.includes('Kubernetes') || entName.includes('Kafka')) {
                    entType = 'org';
                    color = '#F59E0B';
                }

                const entNodeId = `entity_${entName.replace(/\s+/g, '_')}`;
                if (!nodesMap.has(entNodeId)) {
                    nodesMap.set(entNodeId, {
                        id: entNodeId,
                        label: entName,
                        type: entType,
                        color: color,
                        radius: 11,
                        desc: `Extracted from "${doc.name}"`
                    });
                }

                links.push({
                    source: docNodeId,
                    target: entNodeId
                });
            });
        });

        return {
            nodes: Array.from(nodesMap.values()),
            links: links
        };
    }
}

const App = new EchoAppState();

// --- INITIALIZATION ---
document.addEventListener('DOMContentLoaded', () => {
    if (window.lucide) lucide.createIcons();

    setupNavigationRouting();
    setupDropzoneUpload();
    setupSearchEngine();
    setupResultsTable();
    setupNotificationsHeader();
    setupProfileHeader();
    setupSettings();

    renderNotifications();
    renderActiveTab('home');
});

// --- NAVIGATION & ROUTING ---
function setupNavigationRouting() {
    document.querySelectorAll('.nav-item, .profile-dropdown-item').forEach(item => {
        item.addEventListener('click', (e) => {
            const tabName = item.getAttribute('data-tab');
            if (tabName) {
                e.preventDefault();
                renderActiveTab(tabName);
                document.getElementById('profile-dropdown')?.classList.add('hidden');
            }
        });
    });
}

function renderActiveTab(tabName) {
    App.activeTab = tabName;

    document.querySelectorAll('.nav-item').forEach(link => {
        if (link.getAttribute('data-tab') === tabName) {
            link.classList.add('active');
        } else {
            link.classList.remove('active');
        }
    });

    document.querySelectorAll('.view-panel').forEach(p => p.classList.add('hidden'));

    const target = document.getElementById(`view-${tabName}`);
    if (target) target.classList.remove('hidden');

    const titleEl = document.getElementById('page-title');
    const subTitleEl = document.getElementById('page-subtitle');

    const titleMap = {
        home: 'Home',
        search: 'Search',
        results: 'Results',
        graph: 'Knowledge Graph',
        profile: 'My Profile',
        settings: 'Settings'
    };

    if (titleEl) titleEl.textContent = titleMap[tabName] || 'Home';
    if (subTitleEl) subTitleEl.textContent = 'Institutional Memory & Decision Intelligence Engine';

    if (tabName === 'search') renderSearchResults();
    if (tabName === 'results') renderResultsTable();
    if (tabName === 'graph') renderKnowledgeGraph();
    if (tabName === 'profile') renderProfileScreen();

    updateNavBadge();
}

function updateNavBadge() {
    const badge = document.getElementById('nav-count-badge');
    if (badge) badge.textContent = App.documents.length;
}

// --- INTERACTIVE NOTIFICATION CENTER ---
function setupNotificationsHeader() {
    const btn = document.getElementById('notification-btn');
    const panel = document.getElementById('notification-panel');
    const btnMarkAll = document.getElementById('btn-mark-all-read');
    const btnClear = document.getElementById('btn-clear-notifs');

    if (btn && panel) {
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            panel.classList.toggle('hidden');
            document.getElementById('profile-dropdown')?.classList.add('hidden');
        });

        document.addEventListener('click', () => panel.classList.add('hidden'));
        panel.addEventListener('click', (e) => e.stopPropagation());
    }

    if (btnMarkAll) btnMarkAll.addEventListener('click', () => App.markAllNotificationsRead());
    if (btnClear) btnClear.addEventListener('click', () => App.clearNotifications());
}

async function renderNotifications() {
    const list = document.getElementById('notif-items-list');
    const badgeCount = document.getElementById('notif-badge-count');
    const headerBadge = document.getElementById('notif-header-badge');

    if (!list) return;

    const notifs = await window.apiService.getNotifications();
    const unreadCount = notifs.filter(n => !n.read).length;

    if (badgeCount) {
        if (unreadCount > 0) {
            badgeCount.textContent = unreadCount;
            badgeCount.classList.remove('hidden');
        } else {
            badgeCount.classList.add('hidden');
        }
    }

    if (headerBadge) {
        headerBadge.textContent = `${unreadCount} Unread`;
    }

    if (notifs.length === 0) {
        list.innerHTML = `<div class="p-6 text-center text-slate-400 text-xs font-semibold">No notifications.</div>`;
        return;
    }

    list.innerHTML = notifs.map(notif => `
        <div class="p-3 rounded-2xl ${notif.read ? 'bg-slate-50/60' : 'bg-indigo-50/70 border border-indigo-100'} flex items-start gap-3 transition-all">
            <div class="w-7 h-7 rounded-xl ${notif.type === 'success' ? 'bg-emerald-100 text-emerald-600' : 'bg-indigo-100 text-indigo-600'} flex items-center justify-center shrink-0 mt-0.5">
                <i data-lucide="${notif.type === 'success' ? 'check-circle-2' : 'info'}" class="w-4 h-4"></i>
            </div>
            <div class="flex-1 min-w-0">
                <div class="flex items-center justify-between gap-1">
                    <h5 class="font-extrabold text-xs text-[#0F172A] truncate">${notif.title}</h5>
                    <span class="text-[10px] text-slate-400 font-semibold shrink-0">${notif.time}</span>
                </div>
                <p class="text-xs text-slate-600 font-medium leading-relaxed mt-0.5">${notif.message}</p>
            </div>
        </div>
    `).join('');

    if (window.lucide) lucide.createIcons();
}

// --- PROFILE BAR & DROPDOWN ---
function setupProfileHeader() {
    const trigger = document.getElementById('profile-menu-trigger');
    const dropdown = document.getElementById('profile-dropdown');
    const btnSignOut = document.getElementById('btn-sign-out');

    if (trigger && dropdown) {
        trigger.addEventListener('click', (e) => {
            e.stopPropagation();
            dropdown.classList.toggle('hidden');
            document.getElementById('notification-panel')?.classList.add('hidden');
        });

        document.addEventListener('click', () => dropdown.classList.add('hidden'));
        dropdown.addEventListener('click', (e) => e.stopPropagation());
    }

    if (btnSignOut) {
        btnSignOut.addEventListener('click', () => {
            dropdown.classList.add('hidden');
            showToast('Signed out of ECHO Intelligence Engine session.', 'info');
        });
    }
}

async function renderProfileScreen() {
    const uploadsEl = document.getElementById('profile-stat-uploads');
    const entitiesEl = document.getElementById('profile-stat-entities');
    const nodesEl = document.getElementById('profile-stat-nodes');
    const feed = document.getElementById('profile-timeline-feed');

    const profileData = await window.apiService.getUserProfile();
    const docs = await window.apiService.getDocuments();
    const topology = await window.apiService.getGraphTopology();

    const totalUploads = docs.length;
    const totalEntities = docs.reduce((sum, d) => sum + d.entities.length, 0);

    if (uploadsEl) uploadsEl.textContent = totalUploads;
    if (entitiesEl) entitiesEl.textContent = totalEntities;
    if (nodesEl) nodesEl.textContent = topology.nodes.length;

    if (!feed) return;

    if (App.activities.length === 0) {
        feed.innerHTML = `<div class="p-6 text-center text-slate-400 text-xs">No recent activity logged.</div>`;
        return;
    }

    feed.innerHTML = App.activities.map(act => `
        <div class="timeline-item flex items-start gap-4">
            <div class="w-9 h-9 rounded-2xl ${act.type === 'upload' ? 'bg-indigo-50 text-indigo-600 border border-indigo-200/60' : 'bg-purple-50 text-purple-600 border border-purple-200/60'} flex items-center justify-center shrink-0 z-10">
                <i data-lucide="${act.type === 'upload' ? 'file-up' : 'git-commit'}" class="w-4 h-4"></i>
            </div>
            <div class="flex-1 bg-slate-50 p-4 rounded-2xl border border-slate-100 space-y-1">
                <div class="flex items-center justify-between">
                    <h5 class="font-extrabold text-xs text-[#0F172A]">${act.title}</h5>
                    <span class="text-[10px] font-bold text-slate-400">${act.date}</span>
                </div>
                <p class="text-xs text-slate-500 font-medium">${act.subtitle}</p>
            </div>
        </div>
    `).join('');

    if (window.lucide) lucide.createIcons();
}

// --- FILE UPLOADER & POLLING PIPELINE ---
function setupDropzoneUpload() {
    const dropzone = document.getElementById('upload-dropzone');
    const fileInput = document.getElementById('file-input');
    const triggerBtn = document.getElementById('trigger-file-select');

    if (!dropzone || !fileInput) return;

    if (triggerBtn) {
        triggerBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            fileInput.click();
        });
    }

    dropzone.addEventListener('click', () => fileInput.click());

    ['dragenter', 'dragover'].forEach(name => {
        dropzone.addEventListener(name, (e) => {
            e.preventDefault();
            e.stopPropagation();
            dropzone.classList.add('drag-active');
        });
    });

    ['dragleave', 'drop'].forEach(name => {
        dropzone.addEventListener(name, (e) => {
            e.preventDefault();
            e.stopPropagation();
            dropzone.classList.remove('drag-active');
        });
    });

    dropzone.addEventListener('drop', (e) => {
        if (e.dataTransfer && e.dataTransfer.files.length > 0) {
            handleRealFileProcessing(e.dataTransfer.files[0]);
        }
    });

    fileInput.addEventListener('change', () => {
        if (fileInput.files && fileInput.files.length > 0) {
            handleRealFileProcessing(fileInput.files[0]);
            fileInput.value = '';
        }
    });
}

async function handleRealFileProcessing(file) {
    const modal = document.getElementById('upload-modal');
    const modalTitle = document.getElementById('upload-modal-title');
    const modalFileName = document.getElementById('upload-modal-file-name');
    const progressBar = document.getElementById('upload-progress-bar');
    const stageText = document.getElementById('upload-stage-text');
    const percentText = document.getElementById('upload-percent-text');
    const completedActions = document.getElementById('upload-completed-actions');

    modal.classList.remove('hidden');
    modalTitle.textContent = 'Processing Document';
    modalFileName.textContent = file.name;
    progressBar.style.width = '10%';
    percentText.textContent = '10%';
    stageText.textContent = 'Initiating API File Upload...';
    completedActions.classList.add('hidden');

    const uploadRes = await window.apiService.uploadDocument(file);
    const docId = uploadRes.documentId;

    let currentStep = 1;
    const pollInterval = setInterval(async () => {
        const statusRes = await window.apiService.getDocumentStatus(docId, currentStep);

        progressBar.style.width = `${statusRes.progress}%`;
        percentText.textContent = `${statusRes.progress}%`;
        stageText.textContent = statusRes.stage;

        if (statusRes.isComplete) {
            clearInterval(pollInterval);
            modalTitle.textContent = 'Document Successfully Processed!';

            const docs = await window.apiService.getDocuments();
            App.documents = docs;
            App.saveDocsToStorage();
            App.generateActivitiesTimeline();
            App.addNotification({
                id: `notif_${Date.now()}`,
                title: "Document Processed",
                message: `Document '${file.name}' processed successfully into Knowledge Graph.`,
                time: "Just now",
                read: false,
                type: "success"
            });
            updateNavBadge();

            completedActions.classList.remove('hidden');
            showToast(`Document "${file.name}" successfully indexed!`, 'success');
        } else {
            currentStep++;
        }
    }, 850);
}

function createProcessedDocument(file) {
    const ext = file.name.split('.').pop().toLowerCase();
    const now = new Date();
    const formattedDate = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')} ${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}`;
    const sizeMB = (file.size / (1024 * 1024)).toFixed(1);
    const sizeStr = file.size > 0 ? `${sizeMB} MB` : '1.5 MB';

    return {
        id: `doc_${Date.now()}`,
        name: file.name,
        date: formattedDate,
        timestamp: Date.now(),
        size: sizeStr,
        type: ext,
        category: 'Operations',
        summary: `Extracted text and structural information from document "${file.name}". Integrated into institutional memory database.`,
        entities: ['Document Processing', 'Vector Index', 'Knowledge Entity'],
        status: 'Indexed & Processed'
    };
}

// Modal Action Listeners
document.addEventListener('click', (e) => {
    if (e.target.id === 'modal-btn-view-results') {
        document.getElementById('upload-modal').classList.add('hidden');
        renderActiveTab('results');
    } else if (e.target.id === 'modal-btn-view-graph') {
        document.getElementById('upload-modal').classList.add('hidden');
        renderActiveTab('graph');
    }
});

// --- SEARCH VIEW ---
function setupSearchEngine() {
    const input = document.getElementById('search-input');
    const btn = document.getElementById('search-submit-btn');

    if (input) input.addEventListener('input', () => renderSearchResults());
    if (btn) btn.addEventListener('click', () => renderSearchResults());
}

async function renderSearchResults() {
    const query = document.getElementById('search-input')?.value.trim().toLowerCase() || '';
    const list = document.getElementById('search-results-list');
    if (!list) return;

    const filtered = await window.apiService.searchDocuments(query);

    if (filtered.length === 0) {
        list.innerHTML = `<div class="bg-white rounded-3xl p-8 border border-slate-200 text-center text-slate-500 text-xs font-semibold">No records found.</div>`;
        return;
    }

    list.innerHTML = filtered.map(doc => `
        <div class="bg-white rounded-3xl p-5 border border-slate-200/80 shadow-sm space-y-2">
            <div class="flex items-center justify-between">
                <h4 class="font-extrabold text-sm text-[#0F172A]">${doc.name}</h4>
                <span class="text-xs font-bold text-emerald-600 bg-emerald-50 px-2.5 py-0.5 rounded-full">98% Match</span>
            </div>
            <p class="text-xs text-slate-600 font-medium">${doc.summary}</p>
            <div class="flex items-center gap-3 text-[11px] text-slate-400 font-semibold pt-1">
                <span>Uploaded: ${doc.date}</span>
                <span>•</span>
                <span>Size: ${doc.size}</span>
            </div>
        </div>
    `).join('');
}

// --- RESULTS VIEW ---
function setupResultsTable() {}

async function renderResultsTable() {
    const tbody = document.getElementById('results-table-body');
    if (!tbody) return;

    const docs = await window.apiService.getDocuments();

    if (docs.length === 0) {
        tbody.innerHTML = `<tr><td colspan="6" class="py-6 text-center text-slate-400 font-semibold">No documents in repository.</td></tr>`;
        return;
    }

    tbody.innerHTML = docs.map(doc => `
        <tr class="hover:bg-slate-50/80 transition-all border-b border-slate-100">
            <td class="py-3.5 px-4 font-bold text-[#0F172A]">${doc.name}</td>
            <td class="py-3.5 px-4 text-slate-500">${doc.date}</td>
            <td class="py-3.5 px-4 text-slate-600 max-w-xs truncate">${doc.summary}</td>
            <td class="py-3.5 px-4">
                <div class="flex flex-wrap gap-1">
                    ${doc.entities.map(e => `<span class="px-2 py-0.5 rounded-full text-[10px] font-semibold bg-indigo-50 text-indigo-700">${e}</span>`).join('')}
                </div>
            </td>
            <td class="py-3.5 px-4">
                <span class="px-2.5 py-1 rounded-full text-[10px] font-bold bg-emerald-50 text-emerald-600">${doc.status}</span>
            </td>
            <td class="py-3.5 px-4 text-right">
                <button onclick="deleteRecord('${doc.id}')" class="text-slate-400 hover:text-red-600 p-1">
                    <i data-lucide="trash-2" class="w-4 h-4"></i>
                </button>
            </td>
        </tr>
    `).join('');

    if (window.lucide) lucide.createIcons();
}

window.deleteRecord = async function(docId) {
    if (confirm('Delete this document?')) {
        await window.apiService.deleteDocument(docId);
        renderResultsTable();
        updateNavBadge();
        showToast('Document record deleted.', 'warning');
    }
};

// --- KNOWLEDGE GRAPH VIEW (D3.js) ---
async function renderKnowledgeGraph() {
    const svg = d3.select('#knowledge-graph-svg');
    svg.selectAll('*').remove();

    const container = document.getElementById('knowledge-graph-svg');
    const width = container.clientWidth || 800;
    const height = container.clientHeight || 500;

    const topology = await window.apiService.getGraphTopology();
    if (topology.nodes.length === 0) return;

    const g = svg.append('g');

    const zoom = d3.zoom()
        .scaleExtent([0.3, 3])
        .on('zoom', (e) => g.attr('transform', e.transform));

    svg.call(zoom);

    document.getElementById('graph-zoom-in').onclick = () => svg.transition().duration(300).call(zoom.scaleBy, 1.3);
    document.getElementById('graph-zoom-out').onclick = () => svg.transition().duration(300).call(zoom.scaleBy, 0.7);
    document.getElementById('graph-reset-view').onclick = () => svg.transition().duration(300).call(zoom.transform, d3.zoomIdentity);

    const simulation = d3.forceSimulation(topology.nodes)
        .force('link', d3.forceLink(topology.links).id(d => d.id).distance(85))
        .force('charge', d3.forceManyBody().strength(-200))
        .force('center', d3.forceCenter(width / 2, height / 2))
        .force('collide', d3.forceCollide(22));

    const link = g.append('g')
        .selectAll('line')
        .data(topology.links)
        .enter().append('line')
        .attr('class', 'link-line');

    const node = g.append('g')
        .selectAll('g')
        .data(topology.nodes)
        .enter().append('g')
        .call(d3.drag()
            .on('start', (e, d) => { if (!e.active) simulation.alphaTarget(0.3).restart(); d.fx = d.x; d.fy = d.y; })
            .on('drag', (e, d) => { d.fx = e.x; d.fy = e.y; })
            .on('end', (e, d) => { if (!e.active) simulation.alphaTarget(0); d.fx = null; d.fy = null; })
        );

    node.append('circle')
        .attr('class', 'node-circle')
        .attr('r', d => d.radius)
        .attr('fill', d => d.color);

    node.append('text')
        .attr('class', 'node-label')
        .attr('dx', 14)
        .attr('dy', 4)
        .text(d => d.label);

    simulation.on('tick', () => {
        link.attr('x1', d => d.source.x).attr('y1', d => d.source.y).attr('x2', d => d.target.x).attr('y2', d => d.target.y);
        node.attr('transform', d => `translate(${d.x},${d.y})`);
    });
}

// --- SETTINGS VIEW ---
function setupSettings() {
    const importBtn = document.getElementById('btn-import-sample');
    const clearBtn = document.getElementById('btn-clear-history');

    if (importBtn) {
        importBtn.addEventListener('click', () => {
            App.resetToDefault();
            updateNavBadge();
            showToast('Dataset reset to sample records.', 'info');
        });
    }

    if (clearBtn) {
        clearBtn.addEventListener('click', () => {
            if (confirm('Clear all local document records?')) {
                App.clearAll();
                updateNavBadge();
                showToast('Local history cleared.', 'warning');
            }
        });
    }
}

// --- TOAST NOTIFICATIONS ---
function showToast(msg, type = 'info') {
    const container = document.getElementById('toast-container');
    if (!container) return;

    const toast = document.createElement('div');
    toast.className = `toast-slide-in pointer-events-auto flex items-center gap-3 px-4 py-3 rounded-2xl shadow-xl text-xs font-bold text-white ${
        type === 'success' ? 'bg-emerald-600' : type === 'warning' ? 'bg-amber-600' : 'bg-indigo-600'
    }`;

    toast.innerHTML = `<span>${msg}</span>`;
    container.appendChild(toast);

    setTimeout(() => {
        toast.style.opacity = '0';
        toast.style.transition = 'all 0.3s ease';
        setTimeout(() => toast.remove(), 300);
    }, 3000);
}
