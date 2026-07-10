// gdrive.js — Native Google Drive Upload page controller

'use strict';

// ── State ────────────────────────────────────────────────────────────────────
let _authUrl = null;
let _browserStack = [];      // [{id, name}] breadcrumb stack
let _browserNextToken = null;
let _recentUploads = [];
let _activeUploadPoll = null;

// ── Init ─────────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
    // Show redirect URI hint in setup instructions
    const uriEl = document.getElementById('redirect-uri-display');
    if (uriEl) {
        uriEl.textContent = `${window.location.protocol}//${window.location.host}/api/gdrive/auth/callback`;
    }

    // Handle ?connected=1 redirect from OAuth callback
    const params = new URLSearchParams(window.location.search);
    if (params.get('connected') === '1') {
        history.replaceState({}, '', '/static/gdrive.html');
        showToast('✅ Google account connected!', 'success');
    }

    loadAuthStatus();
});

// ── Auth ─────────────────────────────────────────────────────────────────────
async function loadAuthStatus() {
    try {
        const res = await fetch('/api/gdrive/auth/status');
        if (res.status === 404) {
            showAuthError('Native Google Drive routes are not available on this server (HTTP 404). Check startup logs for "Native GDrive router disabled" and ensure google-api-python-client/google-auth-httplib2 are installed in the active environment.');
            return;
        }
        if (!res.ok) {
            let detail = '';
            try {
                const payload = await res.json();
                detail = payload && payload.detail ? `: ${payload.detail}` : '';
            } catch (_ignored) {
                detail = '';
            }
            throw new Error(`HTTP ${res.status}${detail}`);
        }
        const data = await res.json();

        document.getElementById('auth-not-configured').style.display = 'none';
        document.getElementById('auth-connected').style.display = 'none';
        document.getElementById('auth-disconnected').style.display = 'none';
        document.getElementById('work-area').style.display = 'none';

        if (!data.client_configured) {
            document.getElementById('auth-not-configured').style.display = '';
            _authUrl = null;
        } else if (data.connected) {
            document.getElementById('auth-email').textContent = data.account_email || '';
            document.getElementById('auth-connected').style.display = '';
            document.getElementById('work-area').style.display = '';
            const uploadDetails = document.getElementById('upload-details');
            if (uploadDetails) uploadDetails.open = true;
            _browserContext = 'sync';
            updateBrowserCtxBadge();
            loadBrowser('root', 'My Drive', null);
            _authUrl = null;
        } else {
            _authUrl = data.auth_url || null;
            document.getElementById('auth-disconnected').style.display = '';
        }
    } catch (e) {
        showAuthError(`Failed to load auth status: ${e.message}`);
    }
}

function gdriveConnect() {
    if (_authUrl) {
        window.location.href = _authUrl;
    } else {
        window.location.href = '/api/gdrive/auth/start';
    }
}

async function gdriveDisconnect() {
    if (!confirm('Disconnect your Google account from JetStream? You will need to reconnect to upload files.')) return;
    try {
        const res = await fetch('/api/gdrive/auth/disconnect', { method: 'POST' });
        const data = await res.json();
        showToast(data.message || 'Disconnected.', 'info');
        document.getElementById('work-area').style.display = 'none';
        loadAuthStatus();
    } catch (e) {
        showAuthError(`Disconnect failed: ${e.message}`);
    }
}

function showAuthError(msg) {
    const el = document.getElementById('auth-error');
    el.textContent = msg;
    el.style.display = '';
}

// ── Upload ────────────────────────────────────────────────────────────────────
async function gdriveUpload() {
    const localPath = document.getElementById('upload-local-path').value.trim();
    const folderId = document.getElementById('dest-folder-id').value || 'root';
    const overwrite = document.getElementById('upload-overwrite').checked;

    if (!localPath) {
        showUploadResult(false, null, 'Please enter a local file path.');
        return;
    }

    showUploadResult(null, null, null, true); // loading state

    try {
        const res = await fetch('/api/gdrive/upload', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ local_path: localPath, folder_id: folderId, overwrite }),
        });
        const data = await res.json();
        if (!res.ok) {
            showUploadResult(false, null, data.detail || 'Upload failed.');
            return;
        }
        if (!data.upload_id) {
            // Backward compatibility if server responds synchronously.
            showUploadResult(true, data);
            addToHistory(data, localPath);
            return;
        }
        startUploadPolling(data.upload_id, localPath);
    } catch (e) {
        showUploadResult(false, null, `Network error: ${e.message}`);
    }
}

function startUploadPolling(uploadId, localPath) {
    if (_activeUploadPoll) {
        clearInterval(_activeUploadPoll);
        _activeUploadPoll = null;
    }

    const started = Date.now();
    const tick = async () => {
        try {
            const res = await fetch(`/api/gdrive/upload/status/${encodeURIComponent(uploadId)}`);
            const data = await res.json();
            if (!res.ok) {
                showUploadResult(false, null, data.detail || 'Upload status check failed.');
                if (_activeUploadPoll) clearInterval(_activeUploadPoll);
                _activeUploadPoll = null;
                return;
            }

            const elapsedSec = Math.max(0, Math.floor((Date.now() - started) / 1000));
            if (data.status === 'completed') {
                showUploadResult(true, data);
                addToHistory(data, localPath);
                if (_activeUploadPoll) clearInterval(_activeUploadPoll);
                _activeUploadPoll = null;
                return;
            }
            if (data.status === 'failed') {
                showUploadResult(false, null, data.error || 'Upload failed.');
                if (_activeUploadPoll) clearInterval(_activeUploadPoll);
                _activeUploadPoll = null;
                return;
            }

            showUploadProgress(data.status || 'uploading', data.progress_pct || 0, elapsedSec);
        } catch (e) {
            showUploadResult(false, null, `Status polling failed: ${e.message}`);
            if (_activeUploadPoll) clearInterval(_activeUploadPoll);
            _activeUploadPoll = null;
        }
    };

    tick();
    _activeUploadPoll = setInterval(tick, 1500);
}

function showUploadProgress(status, progressPct, elapsedSec) {
    const el = document.getElementById('upload-result');
    el.style.display = '';
    el.style.background = '#f8fafc';
    el.style.border = '1px solid #e2e8f0';
    const safePct = Math.max(0, Math.min(100, Number(progressPct) || 0));
    const mm = String(Math.floor(elapsedSec / 60)).padStart(2, '0');
    const ss = String(elapsedSec % 60).padStart(2, '0');
    const label = status === 'queued' ? 'Queued' : 'Uploading';

    el.innerHTML = `
        <div style="display:flex;justify-content:space-between;align-items:center;gap:10px;">
            <span style="color:#334155;font-weight:600;">⏳ ${label}…</span>
            <span style="color:#64748b;font-size:0.85em;">${mm}:${ss}</span>
        </div>
        <div style="margin-top:8px;height:10px;background:#e2e8f0;border-radius:999px;overflow:hidden;">
            <div style="height:100%;width:${safePct}%;background:#2563eb;transition:width .3s ease;"></div>
        </div>
        <div style="margin-top:6px;color:#475569;font-size:0.85em;">${safePct}% complete</div>
    `;
}

function showUploadResult(success, data, errorMsg, loading) {
    const el = document.getElementById('upload-result');
    el.style.display = '';
    if (loading) {
        el.style.background = '#f8fafc';
        el.style.border = '1px solid #e2e8f0';
        el.innerHTML = '<span style="color:#64748b;">⏳ Uploading…</span>';
        return;
    }
    if (success) {
        el.style.background = '#f0fdf4';
        el.style.border = '1px solid #86efac';
        el.innerHTML = `
            <div style="font-weight:600;color:#15803d;">✅ Upload complete</div>
            <div style="margin-top:6px;color:#166534;">
                <strong>${escapeHtml(data.file_name)}</strong>
                ${data.web_view_link
                    ? `<a href="${data.web_view_link}" target="_blank" style="margin-left:10px;color:#2563eb;font-size:0.9em;">Open in Drive ↗</a>`
                    : ''}
            </div>
        `;
    } else {
        el.style.background = '#fef2f2';
        el.style.border = '1px solid #fca5a5';
        el.innerHTML = `<div style="color:#991b1b;">❌ ${escapeHtml(errorMsg || 'Unknown error')}</div>`;
    }
}

function addToHistory(data, localPath) {
    _recentUploads.unshift({ ...data, localPath, ts: new Date().toLocaleTimeString() });
    if (_recentUploads.length > 10) _recentUploads.pop();
    renderHistory();
}

function renderHistory() {
    const el = document.getElementById('upload-history');
    if (!_recentUploads.length) { el.innerHTML = ''; return; }
    el.innerHTML = `
        <div style="font-size:0.82em;font-weight:600;color:#94a3b8;margin-bottom:6px;margin-top:10px;">RECENT UPLOADS</div>
        <div style="border:1px solid #e2e8f0;border-radius:6px;overflow:hidden;">
        ${_recentUploads.map(u => `
            <div style="padding:8px 12px;border-bottom:1px solid #f1f5f9;display:flex;align-items:center;gap:10px;font-size:0.85em;">
                <span style="color:#64748b;">${u.ts}</span>
                <span style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="${escapeHtml(u.localPath)}">${escapeHtml(u.file_name)}</span>
                ${u.web_view_link
                    ? `<a href="${u.web_view_link}" target="_blank" style="color:#2563eb;white-space:nowrap;">↗ View</a>`
                    : ''}
            </div>
        `).join('')}
        </div>
    `;
}

// ── Browser ───────────────────────────────────────────────────────────────────
let _browserContext = 'sync'; // 'sync' or 'upload'

function updateBrowserCtxBadge() {
    const badge = document.getElementById('browser-ctx-badge');
    if (!badge) return;
    if (_browserContext === 'sync') {
        badge.className = 'ctx-badge ctx-sync';
        badge.textContent = '\u2192 Sync dest';
    } else {
        badge.className = 'ctx-badge ctx-upload';
        badge.textContent = '\u2192 Upload dest';
    }
}

function setBrowserContext(ctx) {
    _browserContext = ctx;
    updateBrowserCtxBadge();
    const panel = document.getElementById('browser-panel');
    if (panel) panel.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    showToast(ctx === 'upload' ? '📂 Click ‘️ Select in browser to set upload folder' : '📂 Browser sets sync destination', 'info');
}

function goRoot() {
    _browserStack = [];
    _browserNextToken = null;
    loadBrowser('root', 'My Drive', null);
}

function refreshBrowser() {
    if (_browserStack.length) {
        const cur = _browserStack.pop();
        loadBrowser(cur.id, cur.name, null);
    } else {
        loadBrowser('root', 'My Drive', null);
    }
}

function openBrowser(folderId, folderName, context) {
    // Legacy: kept for any external callers; browser is always visible now.
    folderId = folderId || 'root';
    folderName = folderName || 'My Drive';
    _browserContext = context || 'sync';
    updateBrowserCtxBadge();
    loadBrowser(folderId, folderName, null);
}

function closeBrowser() {
    // Browser stays visible; just reset context to sync.
    _browserContext = 'sync';
    updateBrowserCtxBadge();
}

function browserUp() {
    if (_browserStack.length <= 1) return;
    _browserStack.pop();
    const parent = _browserStack[_browserStack.length - 1];
    _browserStack.pop(); // will be re-pushed by loadBrowser
    loadBrowser(parent.id, parent.name, null);
}

function browserNextPage() {
    if (!_browserStack.length || !_browserNextToken) return;
    const cur = _browserStack[_browserStack.length - 1];
    loadBrowser(cur.id, cur.name, _browserNextToken, true);
}

async function loadBrowser(folderId, folderName, pageToken, append) {
    if (!append) {
        document.getElementById('browser-tbody').innerHTML =
            '<tr><td colspan="4" style="padding:24px;text-align:center;color:#94a3b8;">Loading…</td></tr>';
    }

    try {
        let url = `/api/gdrive/browse?folder_id=${encodeURIComponent(folderId)}`;
        if (pageToken) url += `&page_token=${encodeURIComponent(pageToken)}`;
        const res = await fetch(url);
        if (!res.ok) {
            const err = await res.json();
            throw new Error(err.detail || `HTTP ${res.status}`);
        }
        const data = await res.json();

        // Update breadcrumb stack
        if (!append) {
            _browserStack.push({ id: folderId, name: data.folder_name || folderName });
        }
        _browserNextToken = data.next_page_token || null;

        renderBreadcrumb();
        renderBrowserItems(data.items, append);

        document.getElementById('browser-up-btn').style.display = _browserStack.length > 1 ? '' : 'none';
        document.getElementById('browser-pager').style.display = _browserNextToken ? '' : 'none';
    } catch (e) {
        document.getElementById('browser-tbody').innerHTML =
            `<tr><td colspan="4" style="padding:24px;text-align:center;color:#ef4444;">Error: ${escapeHtml(e.message)}</td></tr>`;
    }
}

function renderBreadcrumb() {
    const el = document.getElementById('browser-breadcrumb');
    el.innerHTML = _browserStack.map((entry, i) => {
        if (i === _browserStack.length - 1) {
            return `<strong>${escapeHtml(entry.name)}</strong>`;
        }
        return `<a href="#" onclick="browserJump(${i});return false;" style="color:#2563eb;">${escapeHtml(entry.name)}</a>`;
    }).join(' › ');
}

function browserJump(idx) {
    const target = _browserStack[idx];
    _browserStack = _browserStack.slice(0, idx);
    loadBrowser(target.id, target.name, null);
}

function renderBrowserItems(items, append) {
    const tbody = document.getElementById('browser-tbody');
    if (!append) tbody.innerHTML = '';
    if (!items.length && !append) {
        tbody.innerHTML = '<tr><td colspan="4" style="padding:24px;text-align:center;color:#94a3b8;">Empty folder</td></tr>';
        return;
    }
    items.forEach(item => {
        const tr = document.createElement('tr');
        tr.style.borderBottom = '1px solid #f1f5f9';
        const icon = item.is_folder ? '📁' : '📄';
        const modified = item.modified_time ? new Date(item.modified_time).toLocaleDateString() : '—';
        const size = item.size_bytes != null ? formatBytes(item.size_bytes) : '—';

        // Name cell — use DOM for the clickable folder link to avoid escaping issues
        const nameCell = document.createElement('td');
        nameCell.style.padding = '8px 12px';
        if (item.is_folder) {
            const a = document.createElement('a');
            a.href = '#';
            a.style.cssText = 'color:#2563eb;text-decoration:none;';
            a.textContent = `${icon} ${item.name}`;
            a.addEventListener('click', e => { e.preventDefault(); enterFolder(item.id, item.name); });
            nameCell.appendChild(a);
        } else {
            nameCell.textContent = `${icon} ${item.name}`;
        }

        // Action cell — Select button or View link, also using DOM
        const actionCell = document.createElement('td');
        actionCell.style.padding = '8px 12px';
        if (item.is_folder) {
            const btn = document.createElement('button');
            btn.className = 'btn btn-secondary';
            btn.style.cssText = 'font-size:0.8em;padding:4px 10px;';
            btn.textContent = '📌 Select';
            btn.addEventListener('click', () => selectFolder(item.id, item.name));
            actionCell.appendChild(btn);
        } else if (item.web_view_link) {
            const a = document.createElement('a');
            a.href = item.web_view_link;
            a.target = '_blank';
            a.style.cssText = 'color:#2563eb;font-size:0.85em;';
            a.textContent = '↗ View';
            actionCell.appendChild(a);
        } else {
            actionCell.textContent = '—';
        }

        const modCell = document.createElement('td');
        modCell.style.cssText = 'padding:8px 12px;color:#64748b;';
        modCell.textContent = modified;

        const sizeCell = document.createElement('td');
        sizeCell.style.cssText = 'padding:8px 12px;color:#64748b;';
        sizeCell.textContent = size;

        tr.appendChild(nameCell);
        tr.appendChild(modCell);
        tr.appendChild(sizeCell);
        tr.appendChild(actionCell);
        tbody.appendChild(tr);
    });
}

function enterFolder(id, name) {
    _browserNextToken = null;
    loadBrowser(id, name, null);
}

function selectFolder(id, name) {
    if (_browserContext === 'sync') {
        document.getElementById('sync-dest-id').value = id;
        document.getElementById('sync-dest-label').textContent = name;
        document.getElementById('sync-dest-label').style.color = '#1e293b';
    } else {
        document.getElementById('dest-folder-id').value = id;
        document.getElementById('dest-folder-label').textContent = name;
        document.getElementById('dest-folder-label').style.color = '#1e293b';
        // Auto-reset context back to sync after upload dest is picked
        _browserContext = 'sync';
        updateBrowserCtxBadge();
    }
    showToast(`📁 Destination set to "${name}"`, 'success');
}

// ── Sync ──────────────────────────────────────────────────────────────────────
async function gdriveSync() {
    const localFolder = document.getElementById('sync-local-folder').value.trim();
    const driveFolderId = document.getElementById('sync-dest-id').value || 'root';
    const recursive = document.getElementById('sync-recursive').checked;
    const overwrite = document.getElementById('sync-overwrite').checked;

    if (!localFolder) {
        _showSyncResult(null, 'Please enter a local folder path.');
        return;
    }

    _showSyncResult('loading');

    try {
        const res = await fetch('/api/gdrive/sync', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                local_folder: localFolder,
                drive_folder_id: driveFolderId,
                recursive,
                overwrite,
                concurrency: Math.min(16, Math.max(1, parseInt(document.getElementById('sync-concurrency')?.value) || 4)),
                chunk_size_mb: Math.min(64, Math.max(1, parseInt(document.getElementById('sync-chunk-mb')?.value) || 8)),
            }),
        });
        const data = await res.json();
        if (!res.ok) {
            _showSyncResult('error', data.detail || 'Sync failed.');
            return;
        }
        _showSyncResult('done', null, data);
    } catch (e) {
        _showSyncResult('error', `Network error: ${e.message}`);
    }
}

function _showSyncResult(state, errorMsg, data) {
    const resultEl = document.getElementById('sync-result');
    const listEl = document.getElementById('sync-file-list');
    resultEl.style.display = '';
    listEl.innerHTML = '';

    if (state === 'loading') {
        resultEl.style.background = '#f8fafc';
        resultEl.style.border = '1px solid #e2e8f0';
        resultEl.innerHTML = '<span style="color:#64748b;">⏳ Syncing… this may take a while for large folders.</span>';
        return;
    }
    if (state === 'error') {
        resultEl.style.background = '#fef2f2';
        resultEl.style.border = '1px solid #fca5a5';
        resultEl.innerHTML = `<div style="color:#991b1b;">❌ ${escapeHtml(errorMsg)}</div>`;
        return;
    }
    // done
    const allOk = data.failed === 0;
    resultEl.style.background = allOk ? '#f0fdf4' : '#fefce8';
    resultEl.style.border = `1px solid ${allOk ? '#86efac' : '#fde047'}`;
    resultEl.innerHTML = `
        <div style="font-weight:600;color:${allOk ? '#15803d' : '#854d0e'};">
            ${allOk ? '✅' : '⚠️'} Sync complete — ${data.succeeded} of ${data.total} files uploaded
            ${data.failed ? `<span style="color:#b45309;"> (${data.failed} failed)</span>` : ''}
        </div>
    `;

    if (data.files && data.files.length) {
        listEl.innerHTML = `
            <div style="font-size:0.82em;font-weight:600;color:#94a3b8;margin:10px 0 6px;">FILES</div>
            <div style="border:1px solid #e2e8f0;border-radius:6px;overflow:hidden;">
            ${data.files.map(f => `
                <div style="padding:7px 12px;border-bottom:1px solid #f1f5f9;display:flex;align-items:center;gap:10px;font-size:0.83em;">
                    <span>${f.success ? '✅' : '❌'}</span>
                    <span style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="${escapeHtml(f.local_path)}">${escapeHtml(f.file_name)}</span>
                    ${f.web_view_link
                        ? `<a href="${f.web_view_link}" target="_blank" style="color:#2563eb;white-space:nowrap;">↗</a>`
                        : f.error ? `<span style="color:#dc2626;" title="${escapeHtml(f.error)}">error</span>` : ''}
                </div>
            `).join('')}
            </div>
        `;
    }
}

// ── Utilities ─────────────────────────────────────────────────────────────────
function formatBytes(bytes) {
    if (bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return `${parseFloat((bytes / Math.pow(k, i)).toFixed(1))} ${sizes[i]}`;
}

function escapeHtml(str) {
    return String(str ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
}

function escapeAttr(str) {
    return String(str ?? '').replace(/'/g, "\\'").replace(/"/g, '&quot;');
}

function showToast(msg, type) {
    // Use shared.js toast if available, otherwise fallback
    if (typeof window.showNotification === 'function') {
        window.showNotification(msg, type);
    } else {
        console.info(msg);
    }
}
