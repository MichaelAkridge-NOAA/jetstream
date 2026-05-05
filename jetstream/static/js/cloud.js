/**
 * JetStream - Cloud Transfer Page
 * Cloud-to-cloud transfer with gcloud storage rsync
 */

let cloudTransferJobs = {};
let hiddenTransferIds = new Set();

document.addEventListener('DOMContentLoaded', function() {
    loadCloudTransfers();

    // Poll for job updates
    setInterval(loadCloudTransfers, 3000);
});

// ===== GCS PATH HELPER =====

function normalizeGcsPath(path) {
    // Remove any trailing slashes
    path = path.replace(/\/+$/, '');

    // If already starts with gs://, return as-is
    if (path.startsWith('gs://')) {
        return path;
    }

    // Otherwise, add gs:// prefix
    return 'gs://' + path;
}

// ===== PATH PREVIEW =====

function updateCloudPathPreview() {
    const src = document.getElementById('source-bucket').value.trim();
    const dst = document.getElementById('dest-bucket').value.trim();

    const srcDiv = document.getElementById('source-path-preview');
    const dstDiv = document.getElementById('dest-path-preview');

    if (src) {
        const norm = src.startsWith('gs://') ? src.replace(/\/+$/, '') : 'gs://' + src.replace(/\/+$/, '');
        document.getElementById('source-path-preview-text').textContent = norm + '/';
        srcDiv.style.display = 'block';
    } else {
        srcDiv.style.display = 'none';
    }

    if (dst) {
        const norm = dst.startsWith('gs://') ? dst.replace(/\/+$/, '') : 'gs://' + dst.replace(/\/+$/, '');
        document.getElementById('dest-path-preview-text').textContent = norm + '/';
        dstDiv.style.display = 'block';
    } else {
        dstDiv.style.display = 'none';
    }
}

// ===== ADVANCED OPTIONS =====

function toggleAdvancedOptions() {
    const advancedOptions = document.getElementById('advanced-options');
    const toggleIcon = document.getElementById('advanced-toggle');

    if (advancedOptions.style.display === 'none') {
        advancedOptions.style.display = 'block';
        toggleIcon.textContent = '\u25b2';
    } else {
        advancedOptions.style.display = 'none';
        toggleIcon.textContent = '\u25bc';
    }
}

// ===== FORM SUBMIT =====

document.getElementById('cloud-transfer-form').addEventListener('submit', async function(e) {
    e.preventDefault();

    const sourceBucket = document.getElementById('source-bucket').value.trim();
    const destBucket = document.getElementById('dest-bucket').value.trim();
    const recursive = document.getElementById('recursive').checked;
    const dryRun = document.getElementById('dry-run').checked;
    const excludePatterns = document.getElementById('exclude-patterns').value
        .split('\n')
        .map(s => s.trim())
        .filter(s => s.length > 0);

    if (!sourceBucket || !destBucket) {
        showToast('Please enter both source and destination paths', 'error');
        return;
    }

    const submitBtn = this.querySelector('button[type="submit"]');
    submitBtn.disabled = true;
    submitBtn.textContent = '⏳ Starting Transfer...';

    try {
        const response = await fetch('/api/cloud/transfer', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                source_path: sourceBucket,
                dest_path: destBucket,
                recursive: recursive,
                dry_run: dryRun,
                exclude_patterns: excludePatterns
            })
        });

        const data = await response.json();

        if (response.ok) {
            showToast(dryRun ? 'Dry run started! Check results below.' : 'Transfer started successfully!', 'success');
            loadCloudTransfers();
        } else {
            showToast(data.detail || 'Failed to start transfer', 'error');
        }
    } catch (error) {
        console.error('Error starting transfer:', error);
        showToast('Error starting transfer: ' + error.message, 'error');
    } finally {
        submitBtn.disabled = false;
        submitBtn.textContent = '🚀 Start Cloud Transfer';
    }
});

// ===== LOAD CLOUD TRANSFERS =====

async function loadCloudTransfers() {
    try {
        const response = await fetch('/api/cloud/transfers');
        if (!response.ok) {
            const container = document.getElementById('cloud-jobs-list');
            container.innerHTML = '<p style="text-align:center;color:#dc2626;padding:30px 0;">Failed to load transfers (API error ' + response.status + ')</p>';
            return;
        }

        const jobs = await response.json();
        cloudTransferJobs = {};
        jobs.forEach(job => {
            cloudTransferJobs[job.job_id] = job;
        });

        renderCloudJobs(jobs);
    } catch (error) {
        console.error('Error loading transfers:', error);
        const container = document.getElementById('cloud-jobs-list');
        container.innerHTML = '<p style="text-align:center;color:#dc2626;padding:30px 0;">Could not connect to server.</p>';
    }
}

function renderCloudJobs(jobs) {
    const container = document.getElementById('cloud-jobs-list');

    // Update stats
    updateTransferStats(jobs);

    // Filter out hidden jobs
    const visibleJobs = jobs.filter(job => !hiddenTransferIds.has(job.job_id));

    if (!visibleJobs || visibleJobs.length === 0) {
        container.innerHTML = '<p style="text-align: center; color: #999; padding: 50px 0;">No cloud transfers yet. Use the form to start a transfer.</p>';
        return;
    }

    // Sort by created_at descending (newest first)
    visibleJobs.sort((a, b) => new Date(b.created_at) - new Date(a.created_at));

    // Update last updated timestamp
    const lastUpdated = document.getElementById('transfers-last-updated');
    if (lastUpdated) {
        lastUpdated.textContent = `(updated ${new Date().toLocaleTimeString()})`;
    }

    container.innerHTML = visibleJobs.map(job => {
        const statusClass = getStatusClass(job.status);
        const statusIcon = getStatusIcon(job.status);
        const isDryRun = job.dry_run ? ' (Dry Run)' : '';

        // Shorten paths for display
        const sourcePath = shortenPath(job.source_path);
        const destPath = shortenPath(job.dest_path);

        const isClickable = job.status === 'completed' || job.status === 'failed';

        return `
            <div class="job-item ${statusClass}" ${isClickable ? `onclick="viewTransferOutput('${job.job_id}')" style="cursor: pointer;"` : ''}>
                <div class="job-info">
                    <div class="job-name">
                        ${statusIcon} ${sourcePath} → ${destPath}${isDryRun}
                    </div>
                    <div class="job-meta" style="font-size: 0.85em; color: #64748b;">
                        Started: ${formatDate(job.created_at)}
                        ${job.completed_at ? ' | Completed: ' + formatDate(job.completed_at) : ''}
                    </div>
                    ${job.error ? `<div style="color: #dc2626; font-size: 0.85em; margin-top: 4px;">Error: ${escapeHtml(job.error)}</div>` : ''}
                </div>
                <div class="job-actions">
                    <span class="status-badge ${statusClass}">${job.status}</span>
                </div>
            </div>
        `;
    }).join('');
}

function shortenPath(path) {
    if (!path) return 'Unknown';
    // Remove gs:// prefix for cleaner display
    path = path.replace(/^gs:\/\//, '');
    // If path is too long, truncate middle
    if (path.length > 40) {
        return path.substring(0, 20) + '...' + path.substring(path.length - 17);
    }
    return path;
}

function updateTransferStats(jobs) {
    const total = jobs.length;
    const active = jobs.filter(j => j.status === 'running').length;
    const completed = jobs.filter(j => j.status === 'completed').length;
    const failed = jobs.filter(j => j.status === 'failed').length;

    document.getElementById('total-transfers').textContent = total;
    document.getElementById('active-transfers').textContent = active;
    document.getElementById('completed-transfers').textContent = completed;
    document.getElementById('failed-transfers').textContent = failed;
}

function getStatusClass(status) {
    switch (status) {
        case 'running': return 'status-running';
        case 'completed': return 'status-completed';
        case 'failed': return 'status-failed';
        default: return 'status-pending';
    }
}

function getStatusIcon(status) {
    switch (status) {
        case 'running': return '⏳';
        case 'completed': return '✅';
        case 'failed': return '❌';
        default: return '⏸️';
    }
}

// ===== VIEW TRANSFER OUTPUT =====

async function viewTransferOutput(jobId) {
    ensureModalExists();
    try {
        const response = await fetch(`/api/cloud/transfer/${jobId}`);
        if (!response.ok) throw new Error('Failed to fetch transfer details');

        const job = await response.json();

        const modalBody = document.getElementById('modalBody');
        let html = '';
        
        html += `<div class="detail-section"><h3>Status</h3><span class="status-badge ${getStatusClass(job.status)}">${job.status.toUpperCase()}</span>${job.dry_run ? ' <span class="job-badge badge-dry-run">🧪 DRY-RUN</span>' : ''}</div>`;
        
        html += `<div class="detail-section"><h3>Command</h3><div class="detail-value">${escapeHtml(job.command || 'N/A')}</div></div>`;

        html += '<div class="detail-section"><h3>Transfer Information</h3><div class="detail-grid">';
        html += `<div class="detail-item"><span class="detail-label">Job ID</span><span class="detail-text">${job.job_id}</span></div>`;
        html += `<div class="detail-item"><span class="detail-label">Created</span><span class="detail-text">${formatDate(job.created_at)}</span></div>`;
        html += `<div class="detail-item"><span class="detail-label">Completed</span><span class="detail-text">${formatDate(job.completed_at)}</span></div>`;
        html += '</div></div>';

        html += '<div class="detail-section"><h3>Source & Destination</h3><div class="detail-grid">';
        html += `<div class="detail-item"><span class="detail-label">Source Path</span><span class="detail-text" style="word-break: break-word; overflow-wrap: anywhere;">${escapeHtml(job.source_path)}</span></div>`;
        html += `<div class="detail-item"><span class="detail-label">Destination Path</span><span class="detail-text" style="word-break: break-word; overflow-wrap: anywhere;">${escapeHtml(job.dest_path)}</span></div>`;
        html += '</div></div>';

        if (job.error) {
            html += `<div class="detail-section"><h3>Error Message</h3><div class="detail-value" style="color: #991b1b; background: #fee2e2;">${escapeHtml(job.error)}</div></div>`;
        }

        if (job.output) {
            html += '<div class="detail-section"><h3>Command Output</h3>';
            html += `<div class="detail-value" style="max-height: 300px; overflow-y: auto; white-space: pre-wrap; word-wrap: break-word; overflow-wrap: anywhere;">${escapeHtml(job.output)}</div></div>`;
        }

        html += '<div class="modal-actions">';
        html += '<button class="btn btn-secondary" onclick="closeJobModal()">Close</button>';
        html += '</div>';

        modalBody.innerHTML = html;
        document.getElementById('jobModal').style.display = 'block';
    } catch (error) {
        console.error('Error fetching transfer details:', error);
        showToast('Error loading transfer details', 'error');
    }
}

// ===== CLEAR COMPLETED TRANSFERS =====

function clearCompletedTransfers() {
    // Hide completed and failed jobs from the view
    Object.values(cloudTransferJobs).forEach(job => {
        if (job.status === 'completed' || job.status === 'failed') {
            hiddenTransferIds.add(job.job_id);
        }
    });
    
    // Re-render the job list
    loadCloudTransfers();
    showToast('Completed transfers hidden from view', 'success');
}
