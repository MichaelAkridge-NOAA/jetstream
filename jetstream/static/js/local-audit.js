/**
 * JetStream - Local Audit Page
 */

let selectedRunId = null;
let selectedFolder = null;
let detailsSkip = 0;
let detailsLimit = 100;
let detailsTotal = 0;
let selectedRunStatus = null;
let currentSummary = null;
let currentFolders = [];

function getStatusBadgeClass(status) {
    const normalized = (status || '').toLowerCase();
    if (normalized === 'queued') return 'status-queued';
    if (normalized === 'running') return 'status-running';
    if (normalized === 'completed') return 'status-completed';
    if (normalized === 'failed') return 'status-failed';
    if (normalized === 'cancelled') return 'status-cancelled';
    return 'status-pending';
}

function getFileCategory(extension) {
    const docs = new Set(['.doc', '.docx', '.pdf', '.txt', '.rtf', '.odt', '.xls', '.xlsx', '.csv', '.ppt', '.pptx', '.md']);
    const media = new Set(['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tif', '.tiff', '.webp', '.mp4', '.mov', '.avi', '.mkv', '.mp3', '.wav']);
    const data = new Set(['.json', '.xml', '.parquet', '.feather', '.avro', '.sqlite', '.db', '.zip', '.gz', '.tar', '.7z', '.ndjson']);
    const temp = new Set(['.tmp', '.temp', '.bak', '.old', '.log', '.dmp', '.cache']);
    const ext = (extension || '').toLowerCase();
    if (docs.has(ext)) return 'docs';
    if (media.has(ext)) return 'media';
    if (data.has(ext)) return 'data';
    if (temp.has(ext)) return 'temp';
    return 'other';
}

function buildTypeRowsFromMap(fileTypes, totalFiles) {
    const safeTotal = Math.max(Number(totalFiles || 0), 1);
    return Object.entries(fileTypes || {})
        .map(([extension, count]) => ({
            extension,
            count: Number(count || 0),
            percent_of_total: Number((((Number(count || 0)) / safeTotal) * 100).toFixed(2)),
            category: getFileCategory(extension),
        }))
        .sort((a, b) => b.count - a.count)
        .slice(0, 50);
}

function renderRuns(runs) {
    const container = document.getElementById('local-audit-runs-list');
    if (!runs || runs.length === 0) {
        container.innerHTML = '<p style="text-align: center; color: #999; padding: 24px 0;">No runs yet.</p>';
        return;
    }

    container.innerHTML = runs.map(run => {
        const selectedStyle = run.run_id === selectedRunId ? 'border-color: #3b82f6; background: #eff6ff;' : '';
        return `
            <div class="job-item" style="cursor:pointer; ${selectedStyle}" onclick="selectRun('${run.run_id}')">
                <div class="job-header">
                    <span class="job-id">${escapeHtml((run.run_id || '').slice(0, 8))}...</span>
                    <span class="status-badge ${getStatusBadgeClass(run.status)}">${escapeHtml(run.status || 'unknown')}</span>
                </div>
                <div style="font-size: 0.9em; color: #475569; line-height: 1.5;">
                    <div><strong>Path:</strong> ${escapeHtml(run.target_path || '')}</div>
                    <div><strong>Files:</strong> ${(run.total_files || 0).toLocaleString()}</div>
                    <div><strong>Size:</strong> ${formatBytes(run.total_size_bytes || 0)}</div>
                    <div><strong>Mode:</strong> ${escapeHtml(run.scan_mode || 'detailed')}</div>
                </div>
            </div>
        `;
    }).join('');
}

function updateSummaryCards(run) {
    document.getElementById('local-audit-run-status').textContent = (run.status || '-').toUpperCase();
    document.getElementById('local-audit-run-id').textContent = run.run_id ? `Run ${run.run_id.slice(0, 8)}...` : 'No run selected';
    document.getElementById('local-audit-total-files').textContent = (run.total_files || 0).toLocaleString();
    document.getElementById('local-audit-total-size').textContent = formatBytes(run.total_size_bytes || 0);
    document.getElementById('local-audit-skipped').textContent = (run.skip_permission_count || 0).toLocaleString();
}

function renderRecommendations(recommendations) {
    const container = document.getElementById('local-audit-recommendations');
    if (!recommendations || recommendations.length === 0) {
        container.innerHTML = '<p style="color:#64748b;">No recommendations for this run.</p>';
        return;
    }

    container.innerHTML = recommendations.map(item => {
        const priority = (item.priority || 'low').toLowerCase();
        const bg = priority === 'high' ? '#fee2e2' : priority === 'medium' ? '#ffedd5' : '#eff6ff';
        const border = priority === 'high' ? '#ef4444' : priority === 'medium' ? '#f97316' : '#3b82f6';
        return `
            <div style="padding: 10px 12px; border-radius: 8px; margin-bottom: 10px; background: ${bg}; border-left: 4px solid ${border};">
                <div style="font-weight: 600; color: #1e293b;">${escapeHtml(item.title || item.kind || 'Recommendation')}</div>
                <div style="font-size: 0.9em; color: #334155; margin-top: 4px;">${escapeHtml(item.reason || '')}</div>
            </div>
        `;
    }).join('');
}

function renderFileTypes(fileTypes) {
    const container = document.getElementById('local-audit-file-types');
    if (!fileTypes || fileTypes.length === 0) {
        container.innerHTML = '<p style="color:#64748b;">No file type data for this run.</p>';
        return;
    }

    container.innerHTML = `
        <table style="width: 100%; border-collapse: collapse; font-size: 0.9em;">
            <thead>
                <tr style="background: #f8fafc; border-bottom: 1px solid #e2e8f0;">
                    <th style="text-align: left; padding: 10px;">Extension</th>
                    <th style="text-align: left; padding: 10px;">Category</th>
                    <th style="text-align: right; padding: 10px;">Count</th>
                    <th style="text-align: right; padding: 10px;">% of Total</th>
                </tr>
            </thead>
            <tbody>
                ${fileTypes.map(item => `
                    <tr style="border-bottom: 1px solid #e2e8f0;">
                        <td style="padding: 10px; font-family: monospace;">${escapeHtml(item.extension || '')}</td>
                        <td style="padding: 10px;">${escapeHtml(item.category || 'other')}</td>
                        <td style="padding: 10px; text-align: right;">${(item.count || 0).toLocaleString()}</td>
                        <td style="padding: 10px; text-align: right;">${Number(item.percent_of_total || 0).toFixed(2)}%</td>
                    </tr>
                `).join('')}
            </tbody>
        </table>
    `;
}

function renderBreakdownForSelection() {
    const context = document.getElementById('local-audit-breakdown-context');
    if (!currentSummary) {
        context.textContent = 'Overall run breakdown.';
        renderFileTypes([]);
        return;
    }

    if (!selectedFolder) {
        context.textContent = 'Overall run breakdown.';
        renderFileTypes(currentSummary.top_file_types || []);
        return;
    }

    const folder = (currentFolders || []).find(row => (row.name || '(root)') === selectedFolder);
    if (!folder) {
        context.textContent = 'Overall run breakdown.';
        renderFileTypes(currentSummary.top_file_types || []);
        return;
    }

    context.textContent = `Folder breakdown: ${selectedFolder}`;
    renderFileTypes(buildTypeRowsFromMap(folder.file_types || {}, folder.total_files || 0));
}

function renderFolders(folders) {
    const container = document.getElementById('local-audit-folders-list');
    if (!folders || folders.length === 0) {
        container.innerHTML = '<p style="color:#64748b;">No folders found for this run.</p>';
        return;
    }

    container.innerHTML = folders.map(folder => {
        const name = folder.name || '(root)';
        const selectedStyle = name === selectedFolder ? 'border-color: #3b82f6; background: #eff6ff;' : '';
        const encodedName = encodeURIComponent(name);
        return `
            <div class="job-item" style="cursor:pointer; ${selectedStyle}" onclick="selectFolder('${encodedName}')">
                <div class="job-header">
                    <span class="job-id">${escapeHtml(name)}</span>
                    <span class="status-badge status-completed">${escapeHtml(folder.scan_mode || 'detailed')}</span>
                </div>
                <div style="font-size: 0.9em; color: #475569; line-height: 1.5;">
                    <div><strong>Files:</strong> ${(folder.total_files || 0).toLocaleString()}</div>
                    <div><strong>Size:</strong> ${formatBytes(folder.total_size_bytes || 0)}</div>
                </div>
            </div>
        `;
    }).join('');
}

function renderDetails(findings) {
    const tbody = document.getElementById('local-audit-details-body');
    if (!findings || findings.length === 0) {
        tbody.innerHTML = '<tr><td colspan="5" style="padding: 14px; color: #64748b;">No file details for this selection.</td></tr>';
        return;
    }

    tbody.innerHTML = findings.map(item => `
        <tr style="border-bottom: 1px solid #e2e8f0;">
            <td style="padding: 10px; max-width: 480px; word-break: break-word;">${escapeHtml(item.relative_path || '')}</td>
            <td style="padding: 10px; font-family: monospace;">${escapeHtml(item.extension || '')} <span style="color:#64748b;">(${escapeHtml(item.file_category || 'other')})</span></td>
            <td style="padding: 10px; text-align: right;">${formatBytes(item.size_bytes || 0)}</td>
            <td style="padding: 10px; text-align: right;">${(item.age_days || 0).toLocaleString()}</td>
            <td style="padding: 10px;">${formatDate(item.modified_at)}</td>
        </tr>
    `).join('');
}

async function loadLocalAuditRuns() {
    try {
        const response = await fetch('/api/local-audit/runs?limit=30');
        const data = await response.json();
        if (!response.ok) {
            throw new Error(data.detail || 'Failed to load local audit runs');
        }

        const runs = data.runs || [];
        renderRuns(runs);
        updateLastRefreshed('local-audit-runs-last-updated');

        if (!selectedRunId && runs.length > 0) {
            await selectRun(runs[0].run_id);
        }
    } catch (error) {
        document.getElementById('local-audit-runs-list').innerHTML = `<p style="color:#dc2626;padding:14px 0;">${escapeHtml(error.message)}</p>`;
    }
}

async function loadRunSummary(runId) {
    const response = await fetch(`/api/local-audit/runs/${runId}/summary`);
    const data = await response.json();
    if (!response.ok) {
        throw new Error(data.detail || 'Failed to load local audit summary');
    }

    selectedRunStatus = ((data.run || {}).status || '').toLowerCase();
    currentSummary = data;
    updateSummaryCards(data.run || {});
    renderRecommendations(data.recommendations || []);
    renderBreakdownForSelection();
}

async function loadFolders(runId) {
    const response = await fetch(`/api/local-audit/runs/${runId}/folders`);
    const data = await response.json();
    if (!response.ok) {
        throw new Error(data.detail || 'Failed to load folder breakdown');
    }

    const folders = data.folders || [];
    currentFolders = folders;
    renderFolders(folders);

    renderBreakdownForSelection();
}

async function loadDetails(runId) {
    detailsLimit = parseInt(document.getElementById('local-audit-detail-limit').value, 10) || 100;
    const sortBy = document.getElementById('local-audit-detail-sort').value || 'size_bytes';
    const sortOrder = document.getElementById('local-audit-detail-order').value || 'desc';

    const params = new URLSearchParams({
        skip: String(detailsSkip),
        limit: String(detailsLimit),
        sort_by: sortBy,
        sort_order: sortOrder,
    });
    if (selectedFolder) {
        params.set('folder', selectedFolder);
    }

    const response = await fetch(`/api/local-audit/runs/${runId}/details?${params.toString()}`);
    const data = await response.json();
    if (!response.ok) {
        throw new Error(data.detail || 'Failed to load file details');
    }

    detailsTotal = data.total || 0;
    renderDetails(data.findings || []);

    const start = detailsTotal === 0 ? 0 : detailsSkip + 1;
    const end = Math.min(detailsSkip + detailsLimit, detailsTotal);
    document.getElementById('local-audit-detail-meta').textContent = `Showing ${start}-${end} of ${detailsTotal}`;
    document.getElementById('local-audit-selected-folder').textContent = selectedFolder || 'Overall (all folders)';
}

async function selectRun(runId) {
    selectedRunId = runId;
    selectedFolder = null;
    detailsSkip = 0;

    await Promise.all([loadRunSummary(runId), loadFolders(runId)]);
    await loadDetails(runId);
    await loadLocalAuditRuns();
}

async function selectFolder(folderNameEncoded) {
    selectedFolder = decodeURIComponent(folderNameEncoded || '');
    detailsSkip = 0;
    renderBreakdownForSelection();
    await loadDetails(selectedRunId);
    await loadFolders(selectedRunId);
}

async function showOverallSummary() {
    if (!selectedRunId) {
        showToast('Select a run first.', 'warning');
        return;
    }

    selectedFolder = null;
    detailsSkip = 0;
    renderBreakdownForSelection();
    await loadDetails(selectedRunId);
    renderFolders(currentFolders || []);
}

async function reloadDetails() {
    if (!selectedRunId) {
        return;
    }
    detailsSkip = 0;
    await loadDetails(selectedRunId);
}

async function nextDetailsPage() {
    if (!selectedRunId) {
        return;
    }
    if (detailsSkip + detailsLimit >= detailsTotal) {
        return;
    }
    detailsSkip += detailsLimit;
    await loadDetails(selectedRunId);
}

async function prevDetailsPage() {
    if (!selectedRunId) {
        return;
    }
    detailsSkip = Math.max(0, detailsSkip - detailsLimit);
    await loadDetails(selectedRunId);
}

async function handleStartScanSubmit(event) {
    event.preventDefault();

    const button = document.getElementById('start-local-audit-btn');
    setButtonLoading(button, true);

    const payload = {
        path: (document.getElementById('local-audit-path').value || '').trim(),
        recursive: document.getElementById('local-audit-recursive').checked,
    };

    try {
        const response = await fetch('/api/local-audit/scan/start', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });
        const data = await response.json();
        if (!response.ok) {
            throw new Error(data.detail || 'Failed to start local audit scan');
        }

        selectedRunId = data.run_id;
        selectedFolder = null;
        detailsSkip = 0;

        showToast(`Started local audit ${data.run_id.slice(0, 8)}...`, 'success');
        await loadLocalAuditRuns();
        await Promise.all([loadRunSummary(selectedRunId), loadFolders(selectedRunId)]);
        await loadDetails(selectedRunId);
    } catch (error) {
        showToast(error.message, 'error');
    } finally {
        setButtonLoading(button, false, 'Start Local Audit');
    }
}

async function clearRunsByScope(scope, successMessage) {
    try {
        const response = await fetch(`/api/local-audit/runs/clear?scope=${encodeURIComponent(scope)}`, {
            method: 'DELETE',
        });
        const data = await response.json();
        if (!response.ok) {
            throw new Error(data.detail || 'Failed to clear runs');
        }

        showToast(data.message || successMessage || 'Runs cleared', 'success');
        if (selectedRunId) {
            const stillExists = (await fetch(`/api/local-audit/runs/${selectedRunId}`)).ok;
            if (!stillExists) {
                selectedRunId = null;
                selectedFolder = null;
                currentSummary = null;
                currentFolders = [];
                renderBreakdownForSelection();
            }
        }
        await loadLocalAuditRuns();
    } catch (error) {
        showToast(error.message, 'error');
    }
}

async function clearFinishedRuns() {
    await clearRunsByScope('finished', 'Finished runs cleared');
}

async function clearFailedRuns() {
    await clearRunsByScope('failed', 'Failed runs cleared');
}

async function rerunSelectedAudit() {
    if (!selectedRunId) {
        showToast('Select a run first.', 'warning');
        return;
    }

    try {
        const response = await fetch(`/api/local-audit/runs/${selectedRunId}/rerun`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({}),
        });
        const data = await response.json();
        if (!response.ok) {
            throw new Error(data.detail || 'Failed to rerun audit');
        }

        selectedRunId = data.run_id;
        selectedFolder = null;
        detailsSkip = 0;
        showToast(`Re-run started ${data.run_id.slice(0, 8)}...`, 'success');
        await loadLocalAuditRuns();
    } catch (error) {
        showToast(error.message, 'error');
    }
}

async function pollSelectedRun() {
    if (!selectedRunId) {
        return;
    }

    try {
        const response = await fetch(`/api/local-audit/runs/${selectedRunId}`);
        const run = await response.json();
        if (!response.ok) {
            return;
        }

        updateSummaryCards(run);

        const status = (run.status || '').toLowerCase();
        const previousStatus = selectedRunStatus;
        selectedRunStatus = status;

        if (status === 'running' || status === 'queued') {
            return;
        }

        if (status !== previousStatus) {
            await Promise.all([
                loadRunSummary(selectedRunId),
                loadFolders(selectedRunId),
                loadDetails(selectedRunId),
                loadLocalAuditRuns(),
            ]);
        }
    } catch (_error) {
        // Ignore polling errors to keep UI responsive.
    }
}

document.addEventListener('DOMContentLoaded', async function() {
    document.getElementById('local-audit-scan-form').addEventListener('submit', handleStartScanSubmit);

    await loadLocalAuditRuns();

    setInterval(loadLocalAuditRuns, getRefreshInterval());
    setInterval(pollSelectedRun, 3000);
});
