/**
 * JetStream - Analytics Page
 * Charts, performance metrics, cloud bucket analyzer
 */

let charts = {};

document.addEventListener('DOMContentLoaded', function() {
    loadAnalytics();
});

// ===== TAB SWITCHING =====

function switchAnalyticsTab(tab) {
    document.querySelectorAll('.analytics-tab').forEach(t => {
        t.style.borderBottom = '3px solid transparent';
        t.style.color = '#64748b';
    });
    document.getElementById(tab + '-tab').style.borderBottom = '3px solid #3182ce';
    document.getElementById(tab + '-tab').style.color = '#3182ce';

    document.querySelectorAll('.analytics-section').forEach(s => s.style.display = 'none');
    document.getElementById(tab + '-section').style.display = 'block';
}

// ===== LOAD ALL ANALYTICS =====

async function loadAnalytics() {
    await Promise.all([
        loadUploadTrends(),
        loadSuccessRate(),
        loadPerformanceMetrics(),
        loadTopSources(),
        loadJobTypeBreakdown()
    ]);
}

// ===== UPLOAD TRENDS CHART =====

async function loadUploadTrends() {
    try {
        const response = await fetch('/api/analytics/upload-trends?days=30');
        const data = await response.json();

        const ctx = document.getElementById('trendsChart');
        if (!ctx) return;
        if (charts.trends) charts.trends.destroy();

        charts.trends = new Chart(ctx, {
            type: 'line',
            data: {
                labels: data.trends.map(t => t.date),
                datasets: [
                    {
                        label: 'Total Jobs',
                        data: data.trends.map(t => t.total_jobs),
                        borderColor: '#3182ce',
                        backgroundColor: 'rgba(49, 130, 206, 0.1)',
                        yAxisID: 'y'
                    },
                    {
                        label: 'Data (GB)',
                        data: data.trends.map(t => t.total_gb),
                        borderColor: '#10b981',
                        backgroundColor: 'rgba(16, 185, 129, 0.1)',
                        yAxisID: 'y1'
                    }
                ]
            },
            options: {
                responsive: true,
                interaction: { mode: 'index', intersect: false },
                scales: {
                    y: { type: 'linear', display: true, position: 'left', title: { display: true, text: 'Jobs' } },
                    y1: { type: 'linear', display: true, position: 'right', title: { display: true, text: 'GB' }, grid: { drawOnChartArea: false } }
                }
            }
        });
    } catch (error) {
        console.error('Error loading upload trends:', error);
    }
}

// ===== SUCCESS RATE CHART =====

async function loadSuccessRate() {
    try {
        const response = await fetch('/api/analytics/success-rate');
        const data = await response.json();

        const ctx = document.getElementById('statusChart');
        if (!ctx) return;
        if (charts.status) charts.status.destroy();

        charts.status = new Chart(ctx, {
            type: 'doughnut',
            data: {
                labels: data.by_status.map(s => s.status.toUpperCase()),
                datasets: [{
                    data: data.by_status.map(s => s.count),
                    backgroundColor: ['#10b981', '#ef4444', '#f59e0b', '#3b82f6', '#8b5cf6', '#6b7280']
                }]
            },
            options: {
                responsive: true,
                plugins: { legend: { position: 'bottom' } }
            }
        });

        const completed = data.by_status.find(s => s.status === 'completed');
        const successRate = completed ? completed.percentage : 0;
        document.getElementById('analytics-success-rate').textContent = successRate.toFixed(1) + '%';
    } catch (error) {
        console.error('Error loading success rate:', error);
    }
}

// ===== PERFORMANCE METRICS =====

async function loadPerformanceMetrics() {
    try {
        const response = await fetch('/api/analytics/performance-metrics');
        const data = await response.json();

        document.getElementById('analytics-avg-speed').textContent = data.avg_speed_mbps.toFixed(2) + ' Mbps';
        document.getElementById('analytics-total-data').textContent = data.total_data_transferred_gb.toFixed(2) + ' GB';
        document.getElementById('analytics-completed').textContent = data.completed_jobs;
    } catch (error) {
        console.error('Error loading performance metrics:', error);
    }
}

// ===== TOP SOURCES CHART =====

async function loadTopSources() {
    try {
        const response = await fetch('/api/analytics/top-sources?limit=5');
        const data = await response.json();

        const ctx = document.getElementById('sourcesChart');
        if (!ctx) return;
        if (charts.sources) charts.sources.destroy();

        charts.sources = new Chart(ctx, {
            type: 'bar',
            data: {
                labels: data.sources.map(s => s.path.split(/[\\/]/).pop() || s.path),
                datasets: [{
                    label: 'Job Count',
                    data: data.sources.map(s => s.job_count),
                    backgroundColor: '#3182ce'
                }]
            },
            options: {
                responsive: true,
                plugins: { legend: { display: false } },
                scales: { y: { beginAtZero: true, title: { display: true, text: 'Jobs' } } }
            }
        });
    } catch (error) {
        console.error('Error loading top sources:', error);
    }
}

// ===== JOB TYPE BREAKDOWN CHART =====

async function loadJobTypeBreakdown() {
    try {
        const response = await fetch('/api/analytics/job-type-breakdown');
        const data = await response.json();

        const ctx = document.getElementById('jobTypesChart');
        if (!ctx) return;
        if (charts.jobTypes) charts.jobTypes.destroy();

        charts.jobTypes = new Chart(ctx, {
            type: 'bar',
            data: {
                labels: ['Dry-Run', 'Split', 'Recursive', 'Scheduled'],
                datasets: [{
                    label: 'Job Count',
                    data: [data.dry_run_jobs, data.split_jobs, data.recursive_jobs, data.scheduled_jobs],
                    backgroundColor: ['#f59e0b', '#ec4899', '#10b981', '#8b5cf6']
                }]
            },
            options: {
                responsive: true,
                plugins: { legend: { display: false } },
                scales: { y: { beginAtZero: true, title: { display: true, text: 'Jobs' } } }
            }
        });
    } catch (error) {
        console.error('Error loading job type breakdown:', error);
    }
}

// ===== CLOUD BUCKET ANALYZER =====

async function analyzeCloudBucket() {
    const bucketName = document.getElementById('cloud-bucket-name').value;
    const prefix = document.getElementById('cloud-prefix').value;

    if (!bucketName) {
        showToast('Please enter a bucket name', 'warning');
        return;
    }

    const btn = document.getElementById('analyze-cloud-btn');
    setButtonLoading(btn, true);

    document.getElementById('cloud-analysis-results').style.display = 'block';
    document.getElementById('cloud-analysis-content').innerHTML = '<div class="spinner-overlay"><div class="spinner"></div><span>Analyzing bucket...</span></div>';

    try {
        const response = await fetch('/api/cloud/analyze-bucket', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                bucket_name: bucketName,
                prefix: prefix || '',
                max_depth: 3
            })
        });

        const data = await response.json();

        if (response.ok) {
            let html = '<div class="summary-card"><h3 style="margin-top: 0; margin-bottom: 15px;">\ud83d\udcca Analysis Summary</h3>';
            html += '<div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 15px;">';
            html += '<div class="summary-item"><div class="summary-label">Bucket</div><div class="summary-value">' + (data.bucket_name || data.bucket) + '</div></div>';
            html += '<div class="summary-item"><div class="summary-label">Prefix</div><div class="summary-value">' + (data.prefix || '(root)') + '</div></div>';
            html += '<div class="summary-item"><div class="summary-label">Folders Analyzed</div><div class="summary-value">' + (data.total_folders_analyzed || data.folder_count || 0) + '</div></div>';
            html += '<div class="summary-item"><div class="summary-label">Blobs Scanned</div><div class="summary-value">' + (data.total_blobs_scanned || data.total_files || 0) + '</div></div>';
            html += '</div></div>';

            if (data.folders && data.folders.length > 0) {
                html += '<div style="overflow-x: auto; margin-top: 20px;"><table class="cloud-results-table"><thead><tr>';
                html += '<th style="text-align: left;">Folder Path</th><th style="text-align: right;">Files</th><th style="text-align: right;">Size (GB)</th>';
                html += '<th style="text-align: left;">Created</th><th style="text-align: left;">Updated</th></tr></thead><tbody>';
                data.folders.forEach(function(folder, i) {
                    html += '<tr class="' + (i % 2 === 0 ? 'even' : 'odd') + '">';
                    html += '<td style="font-family: monospace; font-size: 0.9em;">' + folder.path + '</td>';
                    html += '<td style="text-align: right;">' + folder.file_count + '</td>';
                    html += '<td style="text-align: right;">' + folder.total_size_gb + '</td>';
                    html += '<td style="font-size: 0.85em;">' + (folder.earliest_created ? new Date(folder.earliest_created).toLocaleDateString() : '-') + '</td>';
                    html += '<td style="font-size: 0.85em;">' + (folder.latest_updated ? new Date(folder.latest_updated).toLocaleDateString() : '-') + '</td>';
                    html += '</tr>';
                });
                html += '</tbody></table></div>';
            }

            document.getElementById('cloud-analysis-content').innerHTML = html;
        } else {
            document.getElementById('cloud-analysis-content').innerHTML = '<p style="color: red;">Error: ' + (data.detail || 'Analysis failed') + '</p>';
        }
    } catch (error) {
        document.getElementById('cloud-analysis-content').innerHTML = '<p style="color: red;">Error: ' + error.message + '</p>';
    } finally {
        setButtonLoading(btn, false, '🔍 Analyze Bucket');
    }
}

// ===== QUICK SUMMARY =====

async function getQuickSummary() {
    const bucketName = document.getElementById('cloud-bucket-name').value;
    if (!bucketName) {
        showToast('Please enter a bucket name', 'warning');
        return;
    }

    document.getElementById('cloud-analysis-results').style.display = 'block';
    document.getElementById('cloud-analysis-content').innerHTML = '<div class="spinner-overlay"><div class="spinner"></div><span>Loading summary...</span></div>';

    try {
        const response = await fetch('/api/cloud/bucket-summary/' + bucketName);
        const data = await response.json();

        if (response.ok) {
            let html = '<div class="summary-card"><h3 style="margin-top: 0; margin-bottom: 15px;">\ud83d\udcca Bucket Summary</h3>';
            html += '<div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 15px;">';
            html += '<div class="summary-item"><div class="summary-label">Bucket Name</div><div class="summary-value">' + data.bucket_name + '</div></div>';
            html += '<div class="summary-item"><div class="summary-label">Location</div><div class="summary-value">' + (data.location || 'N/A') + '</div></div>';
            html += '<div class="summary-item"><div class="summary-label">Storage Class</div><div class="summary-value">' + (data.storage_class || 'N/A') + '</div></div>';
            html += '<div class="summary-item"><div class="summary-label">Sample Objects</div><div class="summary-value">' + (data.sample_object_count || 0) + '</div></div>';
            html += '<div class="summary-item"><div class="summary-label">Sample Size</div><div class="summary-value">' + (data.sample_total_size_gb || 0) + ' GB</div></div>';
            html += '</div>';
            if (data.note) {
                html += '<div style="margin-top: 15px; padding: 10px; background: rgba(59, 130, 246, 0.1); border-left: 3px solid #3b82f6; border-radius: 4px;"><small>' + data.note + '</small></div>';
            }
            html += '</div>';
            document.getElementById('cloud-analysis-content').innerHTML = html;
        } else {
            document.getElementById('cloud-analysis-content').innerHTML = '<p style="color: red;">Error: ' + (data.detail || 'Failed to get summary') + '</p>';
        }
    } catch (error) {
        document.getElementById('cloud-analysis-content').innerHTML = '<p style="color: red;">Error: ' + error.message + '</p>';
    }
}
