/**
 * JetStream - Home Page
 * Dashboard stats loading
 */

document.addEventListener('DOMContentLoaded', function() {
    loadStats();
    setInterval(loadStats, getRefreshInterval());
});

function loadStats() {
    fetch('/api/stats/')
        .then(response => response.json())
        .then(data => {
            document.getElementById('total-jobs').textContent = data.total_jobs || 0;
            document.getElementById('active-jobs').textContent = data.active_jobs || 0;
            document.getElementById('data-uploaded').textContent = (data.total_uploaded_gb || 0).toFixed(2) + ' GB';
            document.getElementById('queue-length').textContent = data.queue_length || 0;
            updateLastRefreshed('home-last-updated');
        })
        .catch(error => console.error('Error loading stats:', error));
}
