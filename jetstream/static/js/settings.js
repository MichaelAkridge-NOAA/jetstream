/**
 * JetStream - Settings Page
 * Authentication, configuration, file filters, UI preferences
 */

document.addEventListener('DOMContentLoaded', function() {
    loadSettings();
});

// ===== TAB SWITCHING =====

function switchSettingsTab(tab) {
    document.querySelectorAll('.settings-subtab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.settings-tab-content').forEach(s => s.classList.remove('active'));

    document.getElementById(tab + '-subtab').classList.add('active');
    document.getElementById(tab + '-tab').classList.add('active');
}

// ===== LOAD SETTINGS =====

async function loadSettings() {
    try {
        const response = await fetch('/api/settings/');
        const data = await response.json();

        // Update auth status
        const authContent = document.getElementById('auth-status-content');
        const authStatus = document.getElementById('auth-status');

        if (data.gcs_authenticated) {
            authStatus.style.background = '#d1fae5';
            authStatus.style.border = '1px solid #10b981';
            authContent.innerHTML = '<div style="color: #065f46;">' +
                '\u2713 <strong>Authenticated</strong><br>' +
                '<small>Method: ' + (data.auth_method || 'N/A') + '</small>' +
                (data.gcloud_account ? '<br><small>Account: ' + data.gcloud_account + '</small>' : '') +
                '</div>';
        } else {
            authStatus.style.background = '#fee2e2';
            authStatus.style.border = '1px solid #ef4444';
            authContent.innerHTML = '<div style="color: #991b1b;">' +
                '\u2717 <strong>Not Authenticated</strong><br>' +
                '<small>Please run <code style="background: #1e293b; color: #e2e8f0; padding: 2px 6px; border-radius: 3px;">gcloud auth application-default login</code></small>' +
                '</div>';
        }

        // Load from localStorage
        loadFilterConfigFromStorage();
        loadUIPreferencesFromStorage();

    } catch (error) {
        console.error('Error loading settings:', error);
        document.getElementById('auth-status-content').innerHTML = '<div style="color: #991b1b;">Error loading settings: ' + error.message + '</div>';
    }
}

// ===== FILE FILTERS =====

function saveFilterConfig() {
    const filterConfig = {
        exclude_folders: document.getElementById('setting-exclude-folders').value.split(',').map(s => s.trim()).filter(s => s),
        include_patterns: document.getElementById('setting-include-patterns').value.split('\n').map(s => s.trim()).filter(s => s),
        exclude_patterns: document.getElementById('setting-exclude-patterns').value.split('\n').map(s => s.trim()).filter(s => s)
    };
    localStorage.setItem('filterConfig', JSON.stringify(filterConfig));
    showToast('Filter configuration saved!', 'success');
}

function resetFiltersToDefault() {
    if (!confirm('Reset all filters to default values?')) return;
    setDefaultFilters();
    saveFilterConfig();
}

function setDefaultFilters() {
    document.getElementById('setting-exclude-folders').value =
        '_archive, _YEAR, ISLAND, SITE-ID, SITE_PHOTOS, Corrected, corrected, uncorrected, MISC, DARK, Products, Thumbs.db, .DS_Store, __pycache__';
    document.getElementById('setting-include-patterns').value =
        '^.*\\.(jpg|jpeg|png|tiff|tif|raw|cr2|nef|arw|dng)$\n^.*\\.(mp4|mov|avi|mkv)$\n^.*\\.(txt|csv|json|xml|log)$';
    document.getElementById('setting-exclude-patterns').value =
        '.*\\.tmp$\n.*\\.bak$\n.*~$\n.*\\.pyc$';
}

function loadFilterConfigFromStorage() {
    const stored = localStorage.getItem('filterConfig');
    if (stored) {
        try {
            const config = JSON.parse(stored);
            document.getElementById('setting-exclude-folders').value = config.exclude_folders.join(', ');
            document.getElementById('setting-include-patterns').value = config.include_patterns.join('\n');
            document.getElementById('setting-exclude-patterns').value = config.exclude_patterns.join('\n');
        } catch (e) { /* ignore */ }
    } else {
        setDefaultFilters();
    }
}

// ===== UI PREFERENCES =====

function saveUIPreferences() {
    const uiPrefs = {
        theme: document.getElementById('setting-theme').value,
        refresh_interval: parseInt(document.getElementById('setting-refresh-interval').value),
        notifications: document.getElementById('setting-notifications').checked,
        confirm_delete: document.getElementById('setting-confirm-delete').checked
    };
    localStorage.setItem('uiPreferences', JSON.stringify(uiPrefs));

    // Apply theme immediately
    applyTheme(uiPrefs.theme);

    showToast('UI preferences saved! Refresh interval will take effect on next page load.', 'success');
}

function loadUIPreferencesFromStorage() {
    const stored = localStorage.getItem('uiPreferences');
    if (stored) {
        try {
            const prefs = JSON.parse(stored);
            document.getElementById('setting-theme').value = prefs.theme || 'light';
            document.getElementById('setting-refresh-interval').value = prefs.refresh_interval || 5;
            document.getElementById('setting-notifications').checked = prefs.notifications !== false;
            document.getElementById('setting-confirm-delete').checked = prefs.confirm_delete !== false;
        } catch (e) { /* ignore */ }
    }
}
