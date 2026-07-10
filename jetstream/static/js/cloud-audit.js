/**
 * JetStream - Cloud Audit Page
 */

let selectedRunId = null;
let findingsSkip = 0;
let findingsTotal = 0;
let findingsLimit = 100;
let patternChart = null;
let prefixChart = null;
let selectedRunStatus = null;

function parsePatternsFromTextarea() {
    const raw = document.getElementById('audit-patterns').value || '';
    return raw
        .split('\n')
        .map(line => line.trim())
        .filter(line => line.length > 0);
}

function getStatusBadgeClass(status) {
    const normalized = (status || '').toLowerCase();
    if (normalized === 'queued') return 'status-queued';
    if (normalized === 'running') return 'status-running';
    if (normalized === 'completed') return 'status-completed';
    if (normalized === 'failed') return 'status-failed';
    if (normalized === 'cancelled') return 'status-cancelled';
    if (normalized === 'cancel_requested') return 'status-scheduled';
    return 'status-pending';
}

function renderRuns(runs) {
    const container = document.getElementById('audit-runs-list');
    if (!runs || runs.length === 0) {
        container.innerHTML = '<p style="text-align: center; color: #999; padding: 24px 0;">No runs yet.</p>';
        return;
    }

    container.innerHTML = runs.map(run => {
        const selectedStyle = run.run_id === selectedRunId ? 'border-color: #3b82f6; background: #eff6ff;' : '';
        const rowTitle = run.run_id === selectedRunId ? 'Selected run' : 'Click to load run';
        return `
            <div class="job-item" style="cursor:pointer; ${selectedStyle}" title="${rowTitle}" onclick="selectRun('${run.run_id}')">
                <div class="job-header">
                    <span class="job-id">${escapeHtml(run.run_id.slice(0, 8))}...</span>
                    <span class="status-badge ${getStatusBadgeClass(run.status)}">${escapeHtml(run.status || 'unknown')}</span>
                </div>
                <div style="font-size: 0.9em; color: #475569; line-height: 1.5;">
                    <div><strong>Bucket:</strong> ${escapeHtml(run.bucket_name || '')}</div>
                    <div><strong>Prefix:</strong> ${escapeHtml(run.prefix || '(root)')}</div>
                    <div><strong>Scanned:</strong> ${(run.scanned_objects || 0).toLocaleString()} objects</div>
                    <div><strong>Junk:</strong> ${(run.junk_objects || 0).toLocaleString()} objects</div>
                </div>
            </div>
        `;
    }).join('');
}

async function loadAuditRuns() {
    try {
        const response = await fetch('/api/cloud-audit/runs?limit=30');
        const data = await response.json();
        if (!response.ok) {
            throw new Error(data.detail || 'Failed to load runs');
        }

        const runs = data.runs || [];
        renderRuns(runs);
        updateLastRefreshed('audit-runs-last-updated');

        if (!selectedRunId && runs.length > 0) {
            await selectRun(runs[0].run_id);
        }
    } catch (error) {
        document.getElementById('audit-runs-list').innerHTML = `<p style="color:#dc2626;padding:14px 0;">${escapeHtml(error.message)}</p>`;
    }
}

function updateSummaryCards(run) {
    document.getElementById('audit-run-status').textContent = (run.status || '-').toUpperCase();
    document.getElementById('audit-run-id').textContent = run.run_id ? `Run ${run.run_id.slice(0, 8)}...` : 'No run selected';
    document.getElementById('audit-scanned-objects').textContent = (run.scanned_objects || 0).toLocaleString();
    document.getElementById('audit-junk-objects').textContent = (run.junk_objects || 0).toLocaleString();
    document.getElementById('audit-quarantined-objects').textContent = (run.quarantined_objects || 0).toLocaleString();
}

function renderSummaryCharts(summaryData) {
    const byPattern = summaryData.by_pattern || [];
    const topPrefixes = summaryData.top_prefixes || [];

    const patternCtx = document.getElementById('patternChart').getContext('2d');
    const prefixCtx = document.getElementById('prefixChart').getContext('2d');

    if (patternChart) {
        patternChart.destroy();
    }
    if (prefixChart) {
        prefixChart.destroy();
    }

    patternChart = new Chart(patternCtx, {
        type: 'doughnut',
        data: {
            labels: byPattern.map(item => item.pattern),
            datasets: [{
                data: byPattern.map(item => item.count || 0),
                backgroundColor: ['#2563eb', '#0ea5e9', '#14b8a6', '#22c55e', '#f59e0b', '#ef4444', '#8b5cf6'],
            }],
        },
        options: {
            responsive: true,
            plugins: {
                legend: {
                    position: 'bottom',
                },
            },
        },
    });

    prefixChart = new Chart(prefixCtx, {
        type: 'bar',
        data: {
            labels: topPrefixes.map(item => item.prefix),
            datasets: [{
                label: 'Bytes',
                data: topPrefixes.map(item => item.bytes || 0),
                backgroundColor: '#3182ce',
            }],
        },
        options: {
            responsive: true,
            scales: {
                y: {
                    ticks: {
                        callback: value => formatBytes(value),
                    },
                },
            },
            plugins: {
                legend: {
                    display: false,
                },
            },
        },
    });
}

async function loadRunSummary(runId) {
    const response = await fetch(`/api/cloud-audit/runs/${runId}/summary`);
    const data = await response.json();
    if (!response.ok) {
        throw new Error(data.detail || 'Failed to load run summary');
    }

    selectedRunStatus = ((data.run || {}).status || '').toLowerCase();
    updateSummaryCards(data.run || {});
    renderSummaryCharts(data);
}

function renderFindingsTable(findings) {
    const tbody = document.getElementById('findings-table-body');
    if (!findings || findings.length === 0) {
        tbody.innerHTML = '<tr><td colspan="5" style="padding: 14px; color: #64748b;">No findings for this filter.</td></tr>';
        return;
    }

    tbody.innerHTML = findings.map(f => `
        <tr style="border-bottom: 1px solid #e2e8f0;">
            <td style="padding: 10px; max-width: 460px; word-break: break-word;">${escapeHtml(f.object_name || '')}</td>
            <td style="padding: 10px; font-family: monospace;">${escapeHtml(f.matched_pattern || '')}</td>
            <td style="padding: 10px; text-align: right;">${formatBytes(f.size_bytes || 0)}</td>
            <td style="padding: 10px;"><span class="status-badge ${getStatusBadgeClass(f.action_status)}">${escapeHtml(f.action_status || 'pending')}</span></td>
            <td style="padding: 10px;">${formatDate(f.updated_at)}</td>
        </tr>
    `).join('');
}

async function loadFindings(runId) {
    const status = document.getElementById('findings-status-filter').value;
    findingsLimit = parseInt(document.getElementById('findings-limit').value, 10) || 100;

    const params = new URLSearchParams({
        skip: String(findingsSkip),
        limit: String(findingsLimit),
    });
    if (status) {
        params.set('action_status', status);
    }

    const response = await fetch(`/api/cloud-audit/runs/${runId}/findings?${params.toString()}`);
    const data = await response.json();
    if (!response.ok) {
        throw new Error(data.detail || 'Failed to load findings');
    }

    findingsTotal = data.total || 0;
    renderFindingsTable(data.findings || []);

    const start = findingsTotal === 0 ? 0 : findingsSkip + 1;
    const end = Math.min(findingsSkip + findingsLimit, findingsTotal);
    document.getElementById('findings-page-meta').textContent = `Showing ${start}-${end} of ${findingsTotal}`;
}

async function selectRun(runId) {
    selectedRunId = runId;
    findingsSkip = 0;
    selectedRunStatus = null;
    await Promise.all([loadRunSummary(runId), loadFindings(runId)]);
    await loadAuditRuns();
}

async function clearFailedRuns() {
    try {
        const response = await fetch('/api/cloud-audit/runs/clear-failed', {
            method: 'DELETE',
        });
        const data = await response.json();
        if (!response.ok) {
            throw new Error(data.detail || 'Failed to clear failed runs');
        }

        showToast(data.message || 'Failed runs cleared', 'success');
        if (selectedRunStatus === 'failed') {
            selectedRunId = null;
            selectedRunStatus = null;
            document.getElementById('findings-table-body').innerHTML = '<tr><td colspan="5" style="padding: 14px; color: #64748b;">Select a run to load findings.</td></tr>';
            document.getElementById('findings-page-meta').textContent = 'No data';
        }
        await loadAuditRuns();
    } catch (error) {
        showToast(error.message, 'error');
    }
}

async function reloadFindingsFromFilter() {
    if (!selectedRunId) {
        return;
    }
    findingsSkip = 0;
    await loadFindings(selectedRunId);
}

function downloadManifest(format) {
    if (!selectedRunId) {
        showToast('Select a run first.', 'warning');
        return;
    }

    const status = document.getElementById('findings-status-filter').value;
    const params = new URLSearchParams({ format: format || 'csv' });
    if (status) {
        params.set('action_status', status);
    }

    window.location.href = `/api/cloud-audit/runs/${selectedRunId}/manifest?${params.toString()}`;
}

async function nextFindingsPage() {
    if (!selectedRunId) {
        return;
    }
    if (findingsSkip + findingsLimit >= findingsTotal) {
        return;
    }
    findingsSkip += findingsLimit;
    await loadFindings(selectedRunId);
}

async function prevFindingsPage() {
    if (!selectedRunId) {
        return;
    }
    findingsSkip = Math.max(0, findingsSkip - findingsLimit);
    await loadFindings(selectedRunId);
}

async function cancelSelectedRun() {
    if (!selectedRunId) {
        showToast('Select a run first.', 'warning');
        return;
    }

    try {
        const response = await fetch(`/api/cloud-audit/runs/${selectedRunId}/cancel`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: '{}',
        });
        const data = await response.json();
        if (!response.ok) {
            throw new Error(data.detail || 'Failed to cancel run');
        }
        showToast(data.message || 'Cancellation requested', 'success');
        await loadAuditRuns();
        await loadRunSummary(selectedRunId);
    } catch (error) {
        showToast(error.message, 'error');
    }
}

async function runQuarantine() {
    if (!selectedRunId) {
        showToast('Select a run first.', 'warning');
        return;
    }

    const payload = {
        confirm_text: (document.getElementById('quarantine-confirm-text').value || '').trim(),
        quarantine_bucket: (document.getElementById('quarantine-bucket').value || '').trim() || null,
        quarantine_prefix: (document.getElementById('quarantine-prefix').value || '').trim() || 'quarantine',
        dry_run: document.getElementById('quarantine-dry-run').checked,
        limit: parseInt(document.getElementById('quarantine-limit').value, 10) || 500,
    };

    try {
        const response = await fetch(`/api/cloud-audit/runs/${selectedRunId}/quarantine`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });
        const data = await response.json();
        if (!response.ok) {
            throw new Error(data.detail || 'Quarantine failed');
        }

        showToast(
            payload.dry_run
                ? `Dry-run quarantine reviewed ${data.processed || 0} findings`
                : `Quarantined ${data.quarantined || 0} objects`,
            'success'
        );

        await Promise.all([loadRunSummary(selectedRunId), loadFindings(selectedRunId), loadAuditRuns()]);
    } catch (error) {
        showToast(error.message, 'error');
    }
}

async function handleStartScanSubmit(event) {
    event.preventDefault();

    const submitBtn = document.getElementById('start-audit-btn');
    setButtonLoading(submitBtn, true);

    const payload = {
        bucket_name: (document.getElementById('audit-bucket').value || '').trim(),
        prefix: (document.getElementById('audit-prefix').value || '').trim(),
        max_objects: parseInt(document.getElementById('audit-max-objects').value, 10) || 0,
        junk_regex_patterns: parsePatternsFromTextarea(),
        dry_run: document.getElementById('audit-dry-run').checked,
    };

    try {
        const response = await fetch('/api/cloud-audit/scan/start', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });
        const data = await response.json();
        if (!response.ok) {
            throw new Error(data.detail || 'Failed to start audit scan');
        }

        selectedRunId = data.run_id;
        findingsSkip = 0;
        showToast(`Started scan ${data.run_id.slice(0, 8)}...`, 'success');

        await Promise.all([loadAuditRuns(), loadRunSummary(selectedRunId), loadFindings(selectedRunId)]);
    } catch (error) {
        showToast(error.message, 'error');
    } finally {
        setButtonLoading(submitBtn, false, '🔎 Start Background Scan');
    }
}

async function pollSelectedRun() {
    if (!selectedRunId) {
        return;
    }

    try {
        const response = await fetch(`/api/cloud-audit/runs/${selectedRunId}`);
        const run = await response.json();
        if (!response.ok) {
            return;
        }

        updateSummaryCards(run);

        const status = (run.status || '').toLowerCase();
        const previousStatus = selectedRunStatus;
        selectedRunStatus = status;

        if (status === 'running' || status === 'queued' || status === 'cancel_requested') {
            return;
        }

        // For completed/failed/cancelled, refresh heavy sections only once per status change.
        if (status !== previousStatus) {
            await Promise.all([loadRunSummary(selectedRunId), loadFindings(selectedRunId), loadAuditRuns()]);
        }
    } catch (_error) {
        // Ignore polling errors to keep UI responsive.
    }
}

document.addEventListener('DOMContentLoaded', async function() {
    const form = document.getElementById('audit-scan-form');
    form.addEventListener('submit', handleStartScanSubmit);

    await loadAuditRuns();

    const refreshInterval = getRefreshInterval();
    setInterval(loadAuditRuns, refreshInterval);
    setInterval(pollSelectedRun, 3000);
});
