/**
 * JetStream - Jobs Dashboard Page
 * All jobs listing with filtering
 */

let allJobsCache = [];

document.addEventListener('DOMContentLoaded', function() {
    loadAllJobs();
    loadStats();
    setInterval(loadAllJobs, getRefreshInterval());
    setInterval(loadStats, getRefreshInterval());
});

// ===== LOAD STATS =====

function loadStats() {
    fetch('/api/stats/')
        .then(response => response.json())
        .then(data => {
            document.getElementById('all-total-jobs').textContent = data.total_jobs || 0;
            document.getElementById('running-jobs').textContent = data.active_jobs || 0;
            
            // Get completed and failed from jobs_by_status
            const statusCounts = data.jobs_by_status || {};
            document.getElementById('completed-jobs').textContent = statusCounts.completed || 0;
            document.getElementById('failed-jobs').textContent = statusCounts.failed || 0;
        })
        .catch(error => console.error('Error loading stats:', error));
}

// ===== LOAD ALL JOBS =====

function loadAllJobs() {
    const limit = document.getElementById('filter-limit').value;
    const statusParam = document.getElementById('filter-status').value;
    let url = '/api/uploads/?limit=' + limit + '&include_cleared=true';
    if (statusParam) url += '&status=' + statusParam;

    // Show spinner only on first load
    if (allJobsCache.length === 0) {
        showSpinner('all-jobs-list', 'Loading jobs...');
    }

    fetch(url)
        .then(response => response.json())
        .then(data => {
            // API returns flat array, not {jobs: [...]}
            allJobsCache = Array.isArray(data) ? data : [];
            filterJobs();
            updateLastRefreshed('jobs-last-updated');
        })
        .catch(error => console.error('Error loading jobs:', error));
}

// ===== FILTERING =====

function filterJobs() {
    const statusFilter = document.getElementById('filter-status').value.toLowerCase();
    const searchFilter = document.getElementById('filter-search').value.toLowerCase();
    const dryRunFilter = document.getElementById('filter-dry-run') ? document.getElementById('filter-dry-run').value : '';
    const splitFilter = document.getElementById('filter-split') ? document.getElementById('filter-split').value : '';

    let filtered = allJobsCache;

    if (statusFilter) {
        filtered = filtered.filter(job => job.status.toLowerCase() === statusFilter);
    }

    if (searchFilter) {
        filtered = filtered.filter(job =>
            job.job_id.toLowerCase().includes(searchFilter) ||
            (job.source_path && job.source_path.toLowerCase().includes(searchFilter)) ||
            (job.destination_bucket && job.destination_bucket.toLowerCase().includes(searchFilter))
        );
    }

    if (dryRunFilter) {
        const isDryRun = dryRunFilter === 'true';
        filtered = filtered.filter(job => job.dry_run === isDryRun);
    }

    if (splitFilter) {
        const isSplit = splitFilter === 'true';
        filtered = filtered.filter(job => job.split_by_folder === isSplit);
    }

    renderJobs(filtered);
}

// ===== RENDERING =====

function renderJobs(jobs) {
    const jobsList = document.getElementById('all-jobs-list');

    if (!jobs || jobs.length === 0) {
        jobsList.innerHTML = '<p style="text-align: center; color: #999; padding: 50px 0;">No jobs found</p>';
        return;
    }

    jobsList.innerHTML = jobs.map(job => renderJobCard(job)).join('');
}

// ===== CLEAR FILTERS =====

function clearFilters() {
    document.getElementById('filter-status').value = '';
    document.getElementById('filter-search').value = '';
    document.getElementById('filter-limit').value = '100';
    if (document.getElementById('filter-dry-run')) document.getElementById('filter-dry-run').value = '';
    if (document.getElementById('filter-split')) document.getElementById('filter-split').value = '';
    loadAllJobs();
}
