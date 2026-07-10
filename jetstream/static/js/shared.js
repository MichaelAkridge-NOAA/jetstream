/**
 * JetStream - Shared Utilities
 * Common functions used across all pages
 */

// ===== THEME MANAGEMENT =====

function applyTheme(theme) {
    if (theme === 'dark') {
        document.body.classList.add('dark-mode');
    } else if (theme === 'light') {
        document.body.classList.remove('dark-mode');
    } else if (theme === 'auto') {
        if (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches) {
            document.body.classList.add('dark-mode');
        } else {
            document.body.classList.remove('dark-mode');
        }
    }
}

function loadThemeOnStartup() {
    const stored = localStorage.getItem('uiPreferences');
    if (stored) {
        try {
            const prefs = JSON.parse(stored);
            if (prefs.theme) applyTheme(prefs.theme);
        } catch (e) { /* ignore */ }
    }
}

// Apply theme on every page load
document.addEventListener('DOMContentLoaded', loadThemeOnStartup);

// ===== SHARED NAVIGATION =====

var DEFAULT_UI_PREFERENCES = {
    theme: 'light',
    refresh_interval: 5,
    notifications: true,
    confirm_delete: true,
    beta_pages: {
        drive_upload: false,
        cloud_audit: false
    }
};

function getUIPreferences() {
    var prefs = {};
    try {
        prefs = JSON.parse(localStorage.getItem('uiPreferences') || '{}');
    } catch (e) {
        prefs = {};
    }

    var beta = prefs.beta_pages || {};
    return {
        theme: prefs.theme || DEFAULT_UI_PREFERENCES.theme,
        refresh_interval: prefs.refresh_interval || DEFAULT_UI_PREFERENCES.refresh_interval,
        notifications: prefs.notifications !== false,
        confirm_delete: prefs.confirm_delete !== false,
        beta_pages: {
            drive_upload: beta.drive_upload === true,
            cloud_audit: beta.cloud_audit === true
        }
    };
}

function _getCurrentPath() {
    return window.location.pathname.toLowerCase();
}

function _isActiveTab(currentPath, tabPath) {
    if (tabPath === '/') {
        return currentPath === '/';
    }
    return currentPath === tabPath;
}

function renderSharedNav() {
    var nav = document.querySelector('.nav-tabs');
    if (!nav) return;

    var prefs = getUIPreferences();
    var tabs = [
        { icon: '🏠', label: 'Home', href: '/' },
        { icon: '📤', label: 'Uploads', href: '/static/uploads.html' },
        { icon: '🗂️', label: 'Drive Upload', href: '/static/gdrive.html', visible: prefs.beta_pages.drive_upload },
        { icon: '☁️', label: 'Cloud Sync', href: '/static/cloud.html' },
        { icon: '🧹', label: 'Cloud Audit', href: '/static/cloud-audit.html', visible: prefs.beta_pages.cloud_audit },
        { icon: '📋', label: 'Jobs', href: '/static/jobs.html' },
        { icon: '📊', label: 'Analytics', href: '/static/analytics.html' },
        { icon: '⚙️', label: 'Settings', href: '/static/settings.html' }
    ];

    var currentPath = _getCurrentPath();
    nav.innerHTML = tabs
        .filter(function(tab) {
            return tab.visible !== false;
        })
        .map(function(tab) {
            var activeClass = _isActiveTab(currentPath, tab.href) ? ' active' : '';
            return '<button class="nav-tab' + activeClass + '" onclick="window.location.href=\'' + tab.href + '\'">' +
                tab.icon + ' ' + tab.label +
                '</button>';
        })
        .join('');
}

function applySharedPageVisibility() {
    var prefs = getUIPreferences();
    var driveQuickActions = document.querySelectorAll('[data-feature="drive-upload"]');
    var auditQuickActions = document.querySelectorAll('[data-feature="cloud-audit"]');

    driveQuickActions.forEach(function(el) {
        el.style.display = prefs.beta_pages.drive_upload ? '' : 'none';
    });

    auditQuickActions.forEach(function(el) {
        el.style.display = prefs.beta_pages.cloud_audit ? '' : 'none';
    });
}

function applyNavigationPreferences() {
    renderSharedNav();
    applySharedPageVisibility();
}

document.addEventListener('DOMContentLoaded', applyNavigationPreferences);

// ===== VERSION BADGE =====

async function loadVersionBadge() {
    try {
        const response = await fetch('/api/version');
        const data = await response.json();
        const version = data.version || '';
        if (!version) return;

        // Inject into every page's header subtitle
        const subtitle = document.querySelector('.header-content p');
        if (subtitle) {
            subtitle.innerHTML =
                'Cloud Data Management System' +
                ' <span style="' +
                    'display:inline-block;' +
                    'margin-left:8px;' +
                    'padding:1px 7px;' +
                    'font-size:0.72em;' +
                    'font-weight:600;' +
                    'letter-spacing:0.04em;' +
                    'border-radius:999px;' +
                    'background:rgba(255,255,255,0.18);' +
                    'border:1px solid rgba(255,255,255,0.35);' +
                    'color:inherit;' +
                    'vertical-align:middle;' +
                '">v' + version + '</span>';
        }
    } catch (e) { /* silently ignore — version badge is cosmetic */ }
}

document.addEventListener('DOMContentLoaded', loadVersionBadge);

// ===== REFRESH INTERVAL =====

/**
 * Returns the user-configured refresh interval in milliseconds.
 * Falls back to 5000ms (5 seconds) if not set.
 */
function getRefreshInterval() {
    try {
        const prefs = JSON.parse(localStorage.getItem('uiPreferences') || '{}');
        const seconds = parseInt(prefs.refresh_interval, 10);
        if (seconds && seconds >= 1 && seconds <= 60) {
            return seconds * 1000;
        }
    } catch (e) { /* ignore */ }
    return 5000;
}

// ===== SHARED FORMATTING =====

// ===== TOAST NOTIFICATIONS =====

function _ensureToastContainer() {
    var container = document.getElementById('toast-container');
    if (!container) {
        container = document.createElement('div');
        container.id = 'toast-container';
        container.className = 'toast-container';
        document.body.appendChild(container);
    }
    return container;
}

var _toastIcons = { success: '✓', error: '✗', info: 'ℹ', warning: '⚠' };

/**
 * Show a toast notification.
 * @param {string} message - The message text
 * @param {'success'|'error'|'info'|'warning'} type - Toast type
 * @param {number} duration - Auto-dismiss in ms (default 3500)
 */
function showToast(message, type, duration) {
    type = type || 'info';
    duration = duration || 3500;
    var container = _ensureToastContainer();

    var toast = document.createElement('div');
    toast.className = 'toast toast-' + type;
    toast.innerHTML = '<span class="toast-icon">' + (_toastIcons[type] || '') + '</span>' +
        '<span class="toast-message">' + message + '</span>' +
        '<button class="toast-close" onclick="this.parentElement.remove()">&times;</button>';
    container.appendChild(toast);

    setTimeout(function() {
        toast.classList.add('toast-hiding');
        setTimeout(function() { toast.remove(); }, 350);
    }, duration);
}

// ===== LOADING SPINNERS =====

/**
 * Show a loading spinner inside a container element.
 * @param {string} containerId - DOM id of the container
 * @param {string} [message] - Optional loading message
 */
function showSpinner(containerId, message) {
    var el = document.getElementById(containerId);
    if (!el) return;
    el.innerHTML = '<div class="spinner-overlay"><div class="spinner"></div>' +
        (message ? '<span>' + message + '</span>' : '') + '</div>';
}

/**
 * Remove spinner from a container (caller replaces content after).
 */
function hideSpinner(containerId) {
    var el = document.getElementById(containerId);
    if (!el) return;
    var overlay = el.querySelector('.spinner-overlay');
    if (overlay) overlay.remove();
}

// ===== BUTTON LOADING STATE =====

/**
 * Toggle a button's loading state.
 * @param {HTMLElement} btn - The button element
 * @param {boolean} loading - true to show loading, false to restore
 * @param {string} [originalText] - Text to restore (only needed when loading=false)
 */
function setButtonLoading(btn, loading, originalText) {
    if (!btn) return;
    if (loading) {
        btn._originalText = btn.innerHTML;
        btn.classList.add('btn-loading');
        btn.disabled = true;
        btn.innerHTML = '<span class="btn-spinner"></span> Processing...';
    } else {
        btn.classList.remove('btn-loading');
        btn.disabled = false;
        btn.innerHTML = originalText || btn._originalText || btn.innerHTML;
    }
}

// ===== COPY TO CLIPBOARD =====

function copyToClipboard(text) {
    navigator.clipboard.writeText(text).then(function() {
        showToast('Copied to clipboard!', 'success', 2000);
    }).catch(function() {
        // Fallback for older browsers
        var ta = document.createElement('textarea');
        ta.value = text;
        ta.style.position = 'fixed';
        ta.style.opacity = '0';
        document.body.appendChild(ta);
        ta.select();
        document.execCommand('copy');
        document.body.removeChild(ta);
        showToast('Copied to clipboard!', 'success', 2000);
    });
}

// ===== LAST UPDATED TIMESTAMP =====

function updateLastRefreshed(elementId) {
    var el = document.getElementById(elementId);
    if (!el) return;
    var now = new Date();
    el.textContent = 'Updated ' + now.toLocaleTimeString();
    el.className = 'last-updated';
}

// ===== FORMATTING =====

function formatBytes(bytes) {
    if (!bytes || bytes === 0) return '0 B';
    const gb = bytes / (1024 ** 3);
    if (gb >= 1) return gb.toFixed(2) + ' GB';
    const mb = bytes / (1024 ** 2);
    if (mb >= 1) return mb.toFixed(2) + ' MB';
    return (bytes / 1024).toFixed(2) + ' KB';
}

function formatDuration(secondsOrStarted, completedAt) {
    // Handle both formats: formatDuration(seconds) or formatDuration(startedAt, completedAt)
    var seconds;
    if (completedAt !== undefined) {
        // Old format with two dates
        if (!secondsOrStarted || !completedAt) return 'N/A';
        seconds = Math.round((new Date(completedAt) - new Date(secondsOrStarted)) / 1000);
    } else {
        // New format with seconds directly
        if (!secondsOrStarted) return 'N/A';
        seconds = Math.round(secondsOrStarted);
    }
    if (seconds < 60) return seconds + 's';
    if (seconds < 3600) return Math.floor(seconds / 60) + 'm ' + (seconds % 60) + 's';
    return Math.floor(seconds / 3600) + 'h ' + Math.floor((seconds % 3600) / 60) + 'm';
}

function formatDate(dateStr) {
    if (!dateStr) return 'N/A';
    return new Date(dateStr).toLocaleString();
}

function escapeHtml(text) {
    if (!text) return '';
    var div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// ===== SHARED JOB RENDERING =====

function renderJobCard(job, options) {
    options = options || {};
    var showDelete = options.showDelete !== false;
    var showProgress = options.showProgress !== false;
    var clickable = options.clickable !== false;
    var isCloudSync = job.job_type === 'cloud_sync' || job.transfer_direction === 'cloud_to_cloud';

    var jobTitle = job.friendly_name || (job.job_id.substring(0, 8) + '...');
    return '<div class="job-item" ' + (clickable ? 'onclick="showJobDetails(\'' + job.job_id + '\')"' : '') + ' style="' + (clickable ? 'cursor: pointer;' : '') + '">' +
        '<div class="job-header">' +
            '<span class="job-id" title="' + job.job_id + '">' + escapeHtml(jobTitle) + '</span>' +
            '<div class="job-actions">' +
                '<span class="status-badge status-' + job.status + '">' + job.status.toUpperCase() + '</span>' +
                (showDelete ? '<button class="btn-delete" onclick="event.stopPropagation(); deleteJob(\'' + job.job_id + '\')" title="Delete Job">\u2715</button>' : '') +
            '</div>' +
        '</div>' +
        '<div class="job-badges">' +
            '<span class="job-badge badge-rsync">\ud83d\udce6 RSYNC</span>' +
            (job.dry_run ? '<span class="job-badge badge-dry-run">\ud83d\udc41\ufe0f DRY-RUN</span>' : '') +
            (job.no_clobber ? '<span class="job-badge badge-rsync">\ud83d\udee1\ufe0f NO-CLOBBER</span>' : '') +
            (job.scheduled_for ? '<span class="job-badge badge-scheduled">\u23f0 SCHEDULED</span>' : '') +
            (isCloudSync ? '<span class="job-badge badge-local">\u2601\ufe0f CLOUD\u2192CLOUD</span>' : '<span class="job-badge badge-local">\ud83d\udcbb LOCAL\u2192CLOUD</span>') +
            (isCloudSync ? '<span class="job-badge badge-rsync">\u2601\ufe0f CLOUD SYNC</span>' : '') +
            (job.split_by_folder ? '<span class="job-badge badge-split">\ud83d\udcc1 SPLIT</span>' : '') +
            (job.recursive ? '<span class="job-badge badge-rsync">\ud83d\udd04 RECURSIVE</span>' : '') +
            (job.auto_retry && job.retry_count > 0 ? '<span class="job-badge badge-scheduled">\ud83d\udd04 RETRY ' + job.retry_count + '</span>' : '') +
        '</div>' +
        (job.scheduled_for && job.status === 'scheduled' ? '<div style="color: #6b21a8; font-size: 0.85em; margin: 8px 0;">\u23f0 Scheduled for: ' + formatDate(job.scheduled_for) + '</div>' : '') +
        (showProgress ? '<div class="progress-bar"><div class="progress-fill" style="width: ' + (job.progress_percent || 0) + '%">' + (job.progress_percent || 0) + '%</div></div>' : '') +
        '<div class="job-details">' +
            '<div><strong>Source:</strong> ' + escapeHtml((job.source_path || '').split(/[\\\/]/).pop()) + '</div>' +
            '<div><strong>Files:</strong> ' + (job.files_uploaded || 0) + ' / ' + (job.total_files || 0) + '</div>' +
            '<div><strong>Bucket:</strong> ' + escapeHtml(job.destination_bucket || 'N/A') + '</div>' +
            '<div><strong>Size:</strong> ' + formatBytes(job.total_size_bytes) + '</div>' +
            '<div><strong>Created:</strong> ' + new Date(job.created_at).toLocaleDateString() + '</div>' +
            '<div><strong>Duration:</strong> ' + formatDuration(job.duration_seconds || (job.started_at ? undefined : null) || job.started_at, job.duration_seconds ? undefined : job.completed_at) + '</div>' +
        '</div>' +
    '</div>';
}

// ===== SHARED JOB ACTIONS =====

async function deleteJob(jobId) {
    if (!confirm('Are you sure you want to delete this job?')) return;
    try {
        var response = await fetch('/api/uploads/' + jobId, { method: 'DELETE' });
        if (response.ok) {
            if (typeof loadJobs === 'function') loadJobs();
            if (typeof loadAllJobs === 'function') loadAllJobs();
            if (typeof loadStats === 'function') loadStats();
        } else {
            var data = await response.json();
            showToast('Error deleting job: ' + (data.detail || 'Unknown error'), 'error');
        }
    } catch (error) {
        showToast('Error: ' + error.message, 'error');
    }
}

async function retryJob(jobId, removeDryRun) {
    var message = removeDryRun
        ? 'This will run the ACTUAL upload (not a dry-run). Are you sure?'
        : 'Are you sure you want to retry this job?';
    if (!confirm(message)) return;
    try {
        var url = removeDryRun
            ? '/api/uploads/' + jobId + '/retry?remove_dry_run=true'
            : '/api/uploads/' + jobId + '/retry';
        var response = await fetch(url, { method: 'POST' });
        if (response.ok) {
            closeJobModal();
            if (typeof loadJobs === 'function') loadJobs();
            if (typeof loadAllJobs === 'function') loadAllJobs();
            if (typeof loadStats === 'function') loadStats();
            showToast(removeDryRun ? 'Job queued for actual upload' : 'Job queued for retry', 'success');
        } else {
            var data = await response.json();
            showToast('Error retrying job: ' + (data.detail || 'Unknown error'), 'error');
        }
    } catch (error) {
        showToast('Error: ' + error.message, 'error');
    }
}

async function cancelJob(jobId) {
    if (!confirm('Cancel this job?')) return;
    try {
        var response = await fetch('/api/uploads/' + jobId + '/cancel', { method: 'POST' });
        if (response.ok) {
            closeJobModal();
            if (typeof loadJobs === 'function') loadJobs();
            if (typeof loadAllJobs === 'function') loadAllJobs();
            if (typeof loadStats === 'function') loadStats();
            showToast('Job cancelled', 'success');
        } else {
            var data = await response.json();
            showToast('Error: ' + (data.detail || 'Unknown error'), 'error');
        }
    } catch (error) {
        showToast('Error: ' + error.message, 'error');
    }
}

// ===== JOB DETAIL MODAL =====

function ensureModalExists() {
    if (!document.getElementById('jobModal')) {
        var modal = document.createElement('div');
        modal.id = 'jobModal';
        modal.className = 'modal';
        modal.onclick = function(e) { if (e.target.id === 'jobModal') closeJobModal(); };
        modal.innerHTML = '<div class="modal-content"><div class="modal-header"><h2>Job Details</h2><button class="modal-close" onclick="closeJobModal()">\u00d7</button></div><div id="modalBody"></div></div>';
        document.body.appendChild(modal);
    }
}

async function showJobDetails(jobId) {
    ensureModalExists();
    try {
        var response = await fetch('/api/uploads/' + jobId);
        if (!response.ok) throw new Error('Job not found');
        var job = await response.json();

        var isCloudSync = job.job_type === 'cloud_sync' || job.transfer_direction === 'cloud_to_cloud';
        var canRetry = !isCloudSync && ['completed', 'failed', 'cancelled'].indexOf(job.status) !== -1;
        var canCancel = !isCloudSync && ['pending', 'queued', 'running', 'scheduled'].indexOf(job.status) !== -1;
        var isDryRun = job.dry_run;
        var uploadTool = job.upload_tool || 'gcloud';

        // Build command preview based on upload tool (including filters)
        var command = '';
        if (isCloudSync && job.filters && job.filters.display_command) {
            command = job.filters.display_command;
        } else if (uploadTool === 'gsutil') {
            command = 'gsutil -m rsync';
            if (job.dry_run) command += ' -n';
            if (job.recursive) command += ' -r';
        } else {
            command = 'gcloud storage rsync';
            if (job.dry_run) command += ' --dry-run';
            if (job.recursive) command += ' --recursive';
            command += ' --checksums-only';
            if (job.no_clobber) command += ' --no-clobber';
        }
        
        // Add exclude patterns to command preview
        if (job.filters) {
            var excludePatterns = [];
            if (job.filters.exclude_patterns && job.filters.exclude_patterns.length > 0) {
                excludePatterns = excludePatterns.concat(job.filters.exclude_patterns);
            }
            if (job.filters.exclude_folders && job.filters.exclude_folders.length > 0) {
                job.filters.exclude_folders.forEach(function(folder) {
                    excludePatterns.push('.*/' + folder + '/.*');
                });
            }
            if (excludePatterns.length > 0) {
                var combinedPattern = excludePatterns.map(function(p) { return '(' + p + ')'; }).join('|');
                if (uploadTool === 'gsutil') {
                    command += ' -x "' + combinedPattern + '"';
                } else {
                    command += ' --exclude="' + combinedPattern + '"';
                }
            }
        }
        if (!isCloudSync || !(job.filters && job.filters.display_command)) {
            command += ' "' + job.source_path + '" "gs://' + job.destination_bucket + '/' + (job.destination_path || '') + '"';
        }

        var modalBody = document.getElementById('modalBody');
        var html = '';
        html += '<div class="detail-section"><h3>Status</h3><span class="status-badge status-' + job.status + '">' + job.status.toUpperCase() + '</span></div>';
        html += '<div class="detail-section"><h3>Command</h3><div class="detail-value" style="word-break: break-all; font-family: monospace; font-size: 0.85em;">' + escapeHtml(command) + '</div></div>';

        html += '<div class="detail-section"><h3>Job Information</h3><div class="detail-grid">';
        if (job.friendly_name) {
            html += '<div class="detail-item"><span class="detail-label">Job Name</span><span class="detail-text">' + escapeHtml(job.friendly_name) + '</span></div>';
        }
        html += '<div class="detail-item"><span class="detail-label">Job Type</span><span class="detail-text">' + (isCloudSync ? 'Cloud Sync' : 'Upload') + '</span></div>';
        html += '<div class="detail-item"><span class="detail-label">Job ID</span><span class="detail-text">' + job.job_id + '</span></div>';
        html += '<div class="detail-item"><span class="detail-label">Created</span><span class="detail-text">' + formatDate(job.created_at) + '</span></div>';
        html += '<div class="detail-item"><span class="detail-label">Started</span><span class="detail-text">' + formatDate(job.started_at) + '</span></div>';
        html += '<div class="detail-item"><span class="detail-label">Completed</span><span class="detail-text">' + formatDate(job.completed_at) + '</span></div>';
        if (job.duration_seconds) {
            html += '<div class="detail-item"><span class="detail-label">Duration</span><span class="detail-text">' + formatDuration(job.duration_seconds) + '</span></div>';
        }
        if (job.transfer_speed) {
            html += '<div class="detail-item"><span class="detail-label">Avg Speed</span><span class="detail-text">' + formatBytes(job.transfer_speed) + '/s</span></div>';
        }
        html += '</div></div>';

        html += '<div class="detail-section"><h3>Source & Destination</h3><div class="detail-grid">';
        html += '<div class="detail-item"><span class="detail-label">Source Path</span><span class="detail-text">' + job.source_path + '</span></div>';
        html += '<div class="detail-item"><span class="detail-label">Destination Bucket</span><span class="detail-text">' + job.destination_bucket + '</span></div>';
        html += '<div class="detail-item"><span class="detail-label">Destination Path</span><span class="detail-text">' + (job.destination_path || '(root)') + '</span></div>';
        html += '<div class="detail-item"><span class="detail-label">Threads</span><span class="detail-text">' + job.threads + '</span></div>';
        html += '</div></div>';

        html += '<div class="detail-section"><h3>Progress</h3>';
        html += '<div class="progress-bar" style="margin-bottom: 15px;"><div class="progress-fill" style="width: ' + job.progress_percent + '%">' + job.progress_percent + '%</div></div>';
        html += '<div class="detail-grid">';
        html += '<div class="detail-item"><span class="detail-label">Files Uploaded</span><span class="detail-text">' + job.files_uploaded + ' / ' + job.total_files + '</span></div>';
        html += '<div class="detail-item"><span class="detail-label">Data</span><span class="detail-text">' + formatBytes(job.bytes_uploaded) + ' / ' + formatBytes(job.total_size_bytes) + '</span></div>';
        html += '<div class="detail-item"><span class="detail-label">Dry Run</span><span class="detail-text">' + (job.dry_run ? 'Yes' : 'No') + '</span></div>';
        html += '<div class="detail-item"><span class="detail-label">Recursive</span><span class="detail-text">' + (job.recursive ? 'Yes' : 'No') + '</span></div>';
        html += '<div class="detail-item"><span class="detail-label">Upload Tool</span><span class="detail-text">' + uploadTool + '</span></div>';
        html += '</div></div>';

        // Show filters if configured
        if (job.filters && (
            (job.filters.exclude_patterns && job.filters.exclude_patterns.length > 0) ||
            (job.filters.exclude_folders && job.filters.exclude_folders.length > 0)
        )) {
            html += '<div class="detail-section"><h3>Filters</h3><div class="detail-grid">';
            if (job.filters.exclude_folders && job.filters.exclude_folders.length > 0) {
                html += '<div class="detail-item"><span class="detail-label">Exclude Folders</span><span class="detail-text" style="font-family: monospace;">' + escapeHtml(job.filters.exclude_folders.join(', ')) + '</span></div>';
            }
            if (job.filters.exclude_patterns && job.filters.exclude_patterns.length > 0) {
                html += '<div class="detail-item"><span class="detail-label">Exclude Patterns</span><span class="detail-text" style="font-family: monospace;">' + escapeHtml(job.filters.exclude_patterns.join(', ')) + '</span></div>';
            }
            html += '</div></div>';
        }

        if (job.error_message) {
            html += '<div class="detail-section"><h3>Error Message</h3><div class="detail-value" style="color: #991b1b; background: #fee2e2;">' + escapeHtml(job.error_message) + '</div></div>';
        }

        if (job.upload_output) {
            html += '<div class="detail-section"><h3>Command Output <button class="btn btn-secondary" onclick="downloadJobOutput(\'' + job.job_id + '\', \'' + job.source_path.replace(/\\/g, '\\\\') + '\')" style="float: right; font-size: 12px; padding: 4px 8px;">\ud83d\udcbe Download Output</button></h3>';
            html += '<div class="detail-value" style="max-height: 300px; overflow-y: auto; white-space: pre-wrap; font-family: monospace; font-size: 0.85em;">' + escapeHtml(job.upload_output) + '</div></div>';
        }

        html += '<div class="modal-actions">';
        if (canCancel) {
            html += '<button class="btn btn-secondary" onclick="cancelJob(\'' + job.job_id + '\')" style="color: #dc2626; border-color: #fecaca; background: #fee2e2;">\u26d4 Cancel Job</button>';
        }
        if (canRetry && isDryRun) {
            html += '<button class="btn-retry" onclick="retryJob(\'' + job.job_id + '\', true)">\ud83d\ude80 Run Actual Upload (Remove Dry-Run)</button>';
        }
        if (canRetry) {
            html += '<button class="btn-retry" onclick="retryJob(\'' + job.job_id + '\', false)">\ud83d\udd04 ' + (isDryRun ? 'Re-run Dry-Run' : 'Retry Upload') + '</button>';
        }
        html += '<button class="btn btn-secondary" onclick="closeJobModal()">Close</button>';
        html += '</div>';

        modalBody.innerHTML = html;
        document.getElementById('jobModal').style.display = 'block';
    } catch (error) {
        showToast('Error loading job details: ' + error.message, 'error');
    }
}

function closeJobModal() {
    var modal = document.getElementById('jobModal');
    if (modal) modal.style.display = 'none';
}

async function downloadJobOutput(jobId, sourcePath) {
    try {
        var response = await fetch('/api/uploads/' + jobId);
        var job = await response.json();
        if (!response.ok || !job.upload_output) {
            showToast('No output available for this job', 'warning');
            return;
        }
        var timestamp = new Date(job.created_at).toISOString().replace(/:/g, '-').split('.')[0];
        var pathName = sourcePath.split(/[/\\]/).pop() || 'job';
        var filename = pathName + '_' + jobId.substring(0, 8) + '_' + timestamp + '.txt';
        var blob = new Blob([job.upload_output], { type: 'text/plain' });
        var url = window.URL.createObjectURL(blob);
        var a = document.createElement('a');
        a.href = url;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        window.URL.revokeObjectURL(url);
        document.body.removeChild(a);
    } catch (error) {
        showToast('Error downloading output: ' + error.message, 'error');
    }
}
