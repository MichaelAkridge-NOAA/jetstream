// Dataset Creator - scan a GCS prefix, group media into a catalog, save/export it.

let lastCatalog = null;
let scannedUris = [];
let busyTimer = null;
let busyStartedAt = null;
let livePreviewTimer = null;
let previewShape = 'grouped';

const API = '/api/dataset-creator';

// ── Busy state with elapsed timer ───────────────────────────────────────────

const BUSY_CONFIG = {
    scan: { banner: 'scanBusy', elapsed: 'scanBusyElapsed', button: 'btnScan', summary: 'scanSummary', label: 'Scanning' },
    build: { banner: 'buildBusy', elapsed: 'buildBusyElapsed', button: 'btnBuild', summary: 'catalogSummary', label: 'Building' }
};

function setBusy(opName, busy) {
    const cfg = BUSY_CONFIG[opName];
    const banner = document.getElementById(cfg.banner);
    const button = document.getElementById(cfg.button);
    const summary = document.getElementById(cfg.summary);
    const buttons = document.querySelectorAll('#datasetForm .dc-actions button');

    clearInterval(busyTimer);
    busyTimer = null;

    if (busy) {
        busyStartedAt = Date.now();
        banner.hidden = false;
        button._originalText = button.innerHTML;
        button.classList.add('btn-loading');
        buttons.forEach(function (b) { b.disabled = true; });

        const tick = function () {
            const elapsed = Math.max(0, Math.floor((Date.now() - busyStartedAt) / 1000));
            document.getElementById(cfg.elapsed).textContent = elapsed + 's';
            summary.textContent = cfg.label + '... ' + elapsed + 's';
            button.innerHTML = '<span class="btn-spinner"></span>' + cfg.label + '... ' + elapsed + 's';
        };
        tick();
        busyTimer = setInterval(tick, 1000);
    } else {
        busyStartedAt = null;
        banner.hidden = true;
        button.classList.remove('btn-loading');
        if (button._originalText) button.innerHTML = button._originalText;
        buttons.forEach(function (b) { b.disabled = false; });
    }
}

function setAlert(className, message) {
    const el = document.getElementById('previewAlert');
    el.className = 'dc-alert ' + className;
    el.textContent = message;
}

// ── Payload building ────────────────────────────────────────────────────────

function parseExtensions() {
    const raw = document.getElementById('extensions').value.trim();
    if (!raw) return null;
    return raw.split(',').map(function (s) { return s.trim(); }).filter(Boolean);
}

function parseJsonOrDefault(elId, fallback) {
    const raw = document.getElementById(elId).value.trim();
    if (!raw) return fallback;
    try {
        return JSON.parse(raw);
    } catch (err) {
        throw new Error('Invalid JSON in ' + elId);
    }
}

function basePayload() {
    const maxPathDepthRaw = document.getElementById('max_path_depth').value.trim();
    const maxPathDepth = maxPathDepthRaw ? Number(maxPathDepthRaw) : null;
    if (maxPathDepth !== null && (!Number.isInteger(maxPathDepth) || maxPathDepth < 0)) {
        throw new Error('Max path depth must be a whole number greater than or equal to 0');
    }

    return {
        gcs_prefix: document.getElementById('gcs_prefix').value.trim(),
        include_images: document.getElementById('include_images').checked,
        include_videos: document.getElementById('include_videos').checked,
        extensions: parseExtensions(),
        filename_filter: document.getElementById('filename_filter').value.trim() || null,
        folder_filter: document.getElementById('folder_filter').value.trim() || null,
        ignore_folder_names: document.getElementById('ignore_folder_names').value
            .split(',').map(function (s) { return s.trim(); }).filter(Boolean),
        max_path_depth: maxPathDepth,
        max_results: Number(document.getElementById('max_results').value) || 0
    };
}

function selectedManualSites() {
    return Array.from(document.querySelectorAll('.manual-site-checkbox:checked'))
        .map(function (cb) { return cb.value; });
}

function buildPayload() {
    return Object.assign({}, basePayload(), {
        catalog_format: document.getElementById('catalog_format').value,
        group_by_mode: document.getElementById('group_by_mode').value,
        filename_delimiter: document.getElementById('filename_delimiter').value || '_',
        filename_token_count: Number(document.getElementById('filename_token_count').value || 3),
        folder_segment_index: Number(document.getElementById('folder_segment_index').value || 0),
        regex_pattern: document.getElementById('regex_pattern').value.trim() || null,
        regex_group_index: Number(document.getElementById('regex_group_index').value || 1),
        manual_overrides: parseJsonOrDefault('manual_overrides', {}),
        selected_groups: [],
        site_instance_mode: document.getElementById('site_instance_mode').value,
        site_instance_threshold: Number(document.getElementById('site_instance_threshold').value || 25),
        site_instance_pattern: document.getElementById('site_instance_pattern').value.trim() || null,
        site_instance_folder_segment_index: Number(document.getElementById('site_instance_folder_segment_index').value || 0),
        manual_site_groups: selectedManualSites()
    });
}

// ── Conditional field blocks ────────────────────────────────────────────────

function show(id, visible) {
    document.getElementById(id).style.display = visible ? '' : 'none';
}

function toggleGroupingFields() {
    const mode = document.getElementById('group_by_mode').value;
    show('grouping_filename_block', mode === 'filename_token');
    show('grouping_folder_block', mode === 'folder_segment');
    show('grouping_regex_block', mode === 'regex');
    show('grouping_manual_block', mode === 'manual');
    updateLivePreview();
}

function toggleSiteFields() {
    const mode = document.getElementById('site_instance_mode').value;
    show('site_threshold_block', mode === 'threshold');
    show('site_folder_block', mode === 'folder_boundary');
    show('site_pattern_block', mode === 'filename_pattern');

    document.getElementById('manualSiteHint').textContent = mode === 'manual'
        ? 'Manual mode enabled: check groups below then click Build Catalog.'
        : 'Choose Manual site mode to enable per-group selection.';

    document.querySelectorAll('.manual-site-checkbox').forEach(function (cb) {
        cb.disabled = mode !== 'manual';
    });
    updateLivePreview();
}

// ── Client-side grouping engine (mirrors services_dataset.py) ───────────────

function uriPath(uri) {
    if (uri.indexOf('gs://') !== 0) return uri;
    const rest = uri.slice(5);
    const slash = rest.indexOf('/');
    return slash === -1 ? '' : rest.slice(slash + 1);
}

function baseName(path) {
    const parts = path.split('/');
    return parts[parts.length - 1] || '';
}

function stripExt(name) {
    const i = name.lastIndexOf('.');
    return i > 0 ? name.slice(0, i) : name;
}

function globToRegExp(glob) {
    const escaped = glob.replace(/[.+^${}()|[\]\\]/g, '\\$&')
        .replace(/\*/g, '.*')
        .replace(/\?/g, '.');
    return new RegExp('^' + escaped + '$', 'i');
}

function deriveGroupKey(uri, opts) {
    const path = uriPath(uri);
    const fname = baseName(path);
    const stem = stripExt(fname);
    const mode = opts.group_by_mode;

    if (mode === 'none') return 'all';

    if (mode === 'filename_token') {
        const parts = stem.split(opts.filename_delimiter).filter(Boolean);
        if (!parts.length) return 'ungrouped';
        return parts.slice(0, opts.filename_token_count).join(opts.filename_delimiter);
    }

    if (mode === 'folder_segment') {
        const dir = path.indexOf('/') !== -1 ? path.slice(0, path.lastIndexOf('/')) : '';
        const segments = dir.split('/').filter(Boolean);
        if (!segments.length) return 'root';
        return segments[Math.min(opts.folder_segment_index, segments.length - 1)];
    }

    if (mode === 'regex' && opts.regex_pattern) {
        try {
            const m = new RegExp(opts.regex_pattern).exec(fname);
            if (!m) return 'unmatched';
            return m[opts.regex_group_index] !== undefined ? String(m[opts.regex_group_index]) : m[0];
        } catch (e) {
            return 'regex-error';
        }
    }

    if (mode === 'manual' && opts.manual_overrides && Object.keys(opts.manual_overrides).length) {
        const lf = fname.toLowerCase();
        const lu = uri.toLowerCase();
        const keys = Object.keys(opts.manual_overrides);
        for (let i = 0; i < keys.length; i++) {
            const patterns = opts.manual_overrides[keys[i]] || [];
            for (let j = 0; j < patterns.length; j++) {
                const p = String(patterns[j]).trim();
                if (!p) continue;
                const pl = p.toLowerCase();
                if (/[*?[]/.test(pl)) {
                    const rx = globToRegExp(pl);
                    if (rx.test(lf) || rx.test(lu)) return keys[i];
                } else if (lf.indexOf(pl) !== -1 || lu.indexOf(pl) !== -1) {
                    return keys[i];
                }
            }
        }
        return 'unmapped';
    }

    return 'all';
}

function deriveSiteInstances(grouped, opts, manualSelected) {
    const mode = opts.site_instance_mode;
    const out = new Set();
    if (mode === 'none') return out;

    if (mode === 'manual') {
        (manualSelected || []).forEach(function (k) { if (grouped[k]) out.add(k); });
        return out;
    }

    const keys = Object.keys(grouped);

    if (mode === 'threshold') {
        keys.forEach(function (k) {
            if (grouped[k].length >= opts.site_instance_threshold) out.add(k);
        });
        return out;
    }

    if (mode === 'folder_boundary') {
        keys.forEach(function (k) {
            const values = grouped[k];
            if (!values.length) return;
            const dir = uriPath(values[0]);
            const parent = dir.indexOf('/') !== -1 ? dir.slice(0, dir.lastIndexOf('/')) : '';
            const segments = parent.split('/').filter(Boolean);
            if (!segments.length) return;
            const idx = Math.min(opts.site_instance_folder_segment_index, segments.length - 1);
            if (segments[idx] === k) out.add(k);
        });
        return out;
    }

    if (mode === 'filename_pattern' && opts.site_instance_pattern) {
        let rx;
        try {
            rx = new RegExp(opts.site_instance_pattern);
        } catch (e) {
            return out;
        }
        keys.forEach(function (k) {
            if (grouped[k].some(function (u) { return rx.test(baseName(uriPath(u))); })) out.add(k);
        });
        return out;
    }

    return out;
}

function currentGroupingOpts() {
    let manualOverrides = {};
    try {
        manualOverrides = parseJsonOrDefault('manual_overrides', {});
    } catch (e) {
        manualOverrides = {};
    }
    return {
        group_by_mode: document.getElementById('group_by_mode').value,
        filename_delimiter: document.getElementById('filename_delimiter').value || '_',
        filename_token_count: Number(document.getElementById('filename_token_count').value || 3),
        folder_segment_index: Number(document.getElementById('folder_segment_index').value || 0),
        regex_pattern: document.getElementById('regex_pattern').value.trim() || null,
        regex_group_index: Number(document.getElementById('regex_group_index').value || 1),
        manual_overrides: manualOverrides,
        site_instance_mode: document.getElementById('site_instance_mode').value,
        site_instance_threshold: Number(document.getElementById('site_instance_threshold').value || 25),
        site_instance_pattern: document.getElementById('site_instance_pattern').value.trim() || null,
        site_instance_folder_segment_index: Number(document.getElementById('site_instance_folder_segment_index').value || 0)
    };
}

function computeGroupedFromScan() {
    const opts = currentGroupingOpts();
    const grouped = {};
    scannedUris.forEach(function (uri) {
        const key = deriveGroupKey(uri, opts);
        (grouped[key] = grouped[key] || []).push(uri);
    });
    const sites = deriveSiteInstances(grouped, opts, selectedManualSites());
    return { grouped: grouped, sites: sites };
}

// ── Mirrored grouping controls (sidebar <-> live preview panel) ─────────────

// [sidebar id, live-preview id]
const MIRRORED_CONTROLS = [
    ['group_by_mode', 'pv_group_by_mode'],
    ['filename_delimiter', 'pv_filename_delimiter'],
    ['filename_token_count', 'pv_filename_token_count'],
    ['folder_segment_index', 'pv_folder_segment_index'],
    ['regex_pattern', 'pv_regex_pattern'],
    ['regex_group_index', 'pv_regex_group_index']
];

function setIfChanged(el, value) {
    if (el.value !== value) el.value = value;
}

function syncMirrorFromSidebar() {
    MIRRORED_CONTROLS.forEach(function (pair) {
        setIfChanged(document.getElementById(pair[1]), document.getElementById(pair[0]).value);
    });
    const mode = document.getElementById('pv_group_by_mode').value;
    document.querySelectorAll('.dc-preview-grouping [data-pvmode]').forEach(function (el) {
        el.style.display = el.dataset.pvmode === mode ? '' : 'none';
    });
}

function describeGrouping() {
    const o = currentGroupingOpts();
    switch (o.group_by_mode) {
        case 'filename_token':
            return 'Grouping by the first ' + o.filename_token_count + ' token' +
                (o.filename_token_count === 1 ? '' : 's') + ' of each filename, split on "' +
                o.filename_delimiter + '". Raise the token count for narrower groups.';
        case 'folder_segment':
            return 'Grouping by folder segment #' + o.folder_segment_index +
                ' of each file\'s path (0 = first folder below the bucket).';
        case 'regex':
            return 'Grouping by capture group ' + o.regex_group_index +
                ' of the pattern matched against each filename. Non-matching files go to "unmatched".';
        case 'manual':
            return 'Grouping by your JSON pattern map. Files matching no pattern go to "unmapped".';
        default:
            return 'No grouping: every file lands in a single group named "all".';
    }
}

function renderGroupingExplainer() {
    const el = document.getElementById('groupingExplainer');
    el.innerHTML = '';

    const desc = document.createElement('div');
    desc.textContent = describeGrouping();
    el.appendChild(desc);

    if (scannedUris.length) {
        const sample = scannedUris[0];
        const example = document.createElement('div');
        example.className = 'dc-explainer-example';
        example.textContent = baseName(uriPath(sample)) + '  \u2192  ' +
            deriveGroupKey(sample, currentGroupingOpts());
        el.appendChild(example);
    }
}

// ── Live preview ────────────────────────────────────────────────────────────

function updateLivePreview() {
    clearTimeout(livePreviewTimer);
    livePreviewTimer = setTimeout(renderLivePreview, 150);
}

function renderLivePreview() {
    const pre = document.getElementById('livePreviewJson');
    const chips = document.getElementById('liveChips');
    const summary = document.getElementById('livePreviewSummary');

    syncMirrorFromSidebar();
    renderGroupingExplainer();

    if (!scannedUris.length) {
        summary.textContent = 'Scan first to enable live preview';
        chips.innerHTML = '';
        pre.textContent = 'Scan a prefix, then adjust grouping options to see a live sample here.';
        return;
    }

    const result = computeGroupedFromScan();
    const grouped = result.grouped;
    const sites = result.sites;
    const groupKeys = Object.keys(grouped).sort();
    const sampleSize = Math.max(1, Number(document.getElementById('liveSampleSize').value || 3));

    summary.textContent = groupKeys.length + ' group(s), ' + sites.size +
        ' site instance(s), ' + scannedUris.length + ' item(s)';

    chips.innerHTML = '';
    groupKeys.slice(0, 40).forEach(function (k) {
        const chip = document.createElement('span');
        chip.className = 'group-chip' + (sites.has(k) ? ' is-site' : '');
        chip.textContent = k + ' (' + grouped[k].length + ')';
        chips.appendChild(chip);
    });
    if (groupKeys.length > 40) {
        const more = document.createElement('span');
        more.className = 'group-chip is-more';
        more.textContent = '+' + (groupKeys.length - 40) + ' more';
        chips.appendChild(more);
    }

    let preview;
    if (previewShape === 'flat') {
        const flat = scannedUris.slice().sort();
        const shown = flat.slice(0, sampleSize * Math.max(1, groupKeys.length));
        preview = { instances: shown };
        if (flat.length > shown.length) preview['...'] = (flat.length - shown.length) + ' more items';
    } else {
        const sampleGroups = {};
        groupKeys.slice(0, 25).forEach(function (k) {
            const items = grouped[k].slice().sort();
            const shown = items.slice(0, sampleSize);
            if (items.length > sampleSize) shown.push('... ' + (items.length - sampleSize) + ' more');
            sampleGroups[k] = shown;
        });
        preview = { instances: sampleGroups };
        if (groupKeys.length > 25) preview['...'] = (groupKeys.length - 25) + ' more groups';
    }
    pre.textContent = JSON.stringify(preview, null, 2);
}

function copyLivePreview() {
    copyToClipboard(document.getElementById('livePreviewJson').textContent);
}

// ── Catalog rendering ───────────────────────────────────────────────────────

function renderGroupTable(groups) {
    const tbody = document.getElementById('groupBody');
    const manualMode = document.getElementById('site_instance_mode').value === 'manual';
    tbody.innerHTML = '';

    groups.forEach(function (g, i) {
        const tr = document.createElement('tr');
        tr.className = i % 2 === 0 ? 'even' : 'odd';

        const tdCheck = document.createElement('td');
        const cb = document.createElement('input');
        cb.type = 'checkbox';
        cb.className = 'manual-site-checkbox';
        cb.value = g.group_key;
        cb.checked = !!g.is_site_instance;
        cb.disabled = !manualMode;
        tdCheck.appendChild(cb);

        const tdKey = document.createElement('td');
        tdKey.className = 'mono-cell';
        tdKey.textContent = g.group_key;

        const tdCount = document.createElement('td');
        tdCount.textContent = g.count;

        const tdSite = document.createElement('td');
        const badge = document.createElement('span');
        badge.className = 'group-chip' + (g.is_site_instance ? ' is-site' : '');
        badge.textContent = g.is_site_instance ? 'yes' : 'no';
        tdSite.appendChild(badge);

        tr.appendChild(tdCheck);
        tr.appendChild(tdKey);
        tr.appendChild(tdCount);
        tr.appendChild(tdSite);
        tbody.appendChild(tr);
    });
}

function renderCatalogSummary(catalog, summaryText) {
    const groups = catalog.groups || [];
    const siteCount = groups.filter(function (g) { return g.is_site_instance; }).length;
    document.getElementById('flatCount').textContent = (catalog.flat_instances || []).length;
    document.getElementById('groupCount').textContent = groups.length + ' / ' + siteCount;
    document.getElementById('catalogSummary').textContent = summaryText;
    renderGroupTable(groups);
}

// ── API actions ─────────────────────────────────────────────────────────────

async function postJson(url, body) {
    const response = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
    });
    const data = await response.json().catch(function () { return {}; });
    if (!response.ok) {
        throw new Error(typeof data.detail === 'string' ? data.detail : 'Request failed');
    }
    return data;
}

async function scanDataset() {
    setBusy('scan', true);
    try {
        const data = await postJson(API + '/scan', basePayload());

        const tbody = document.getElementById('previewBody');
        tbody.innerHTML = '';
        (data.items || []).slice(0, 200).forEach(function (uri, idx) {
            const tr = document.createElement('tr');
            tr.className = idx % 2 === 0 ? 'even' : 'odd';
            const tdIdx = document.createElement('td');
            tdIdx.textContent = idx + 1;
            const tdUri = document.createElement('td');
            tdUri.className = 'mono-cell';
            tdUri.textContent = uri;
            tr.appendChild(tdIdx);
            tr.appendChild(tdUri);
            tbody.appendChild(tr);
        });

        scannedUris = data.items || [];
        const extSummary = (data.extensions_used || []).join(', ') || 'none';
        document.getElementById('scanSummary').textContent =
            data.total_returned + '/' + data.total_matched + ' shown' + (data.truncated ? ' (truncated)' : '');
        setAlert(data.truncated ? 'warning' : 'success',
            'Matched ' + data.total_matched + ' files. Extensions: ' + extSummary +
            (data.truncated ? ' — results were truncated at the server scan limit.' : ''));
        renderLivePreview();
    } catch (err) {
        document.getElementById('scanSummary').textContent = 'Scan failed';
        setAlert('danger', err.message);
        showToast(err.message, 'error');
    } finally {
        setBusy('scan', false);
    }
}

async function buildCatalog() {
    setBusy('build', true);
    try {
        const data = await postJson(API + '/catalog', buildPayload());
        lastCatalog = data;
        renderCatalogSummary(data, 'Built ' + (data.groups || []).length + ' groups');
        toggleSiteFields();
        showToast('Catalog built', 'success');
    } catch (err) {
        document.getElementById('catalogSummary').textContent = 'Build failed';
        showToast(err.message, 'error');
    } finally {
        setBusy('build', false);
    }
}

function catalogWithSelectedFormat() {
    return Object.assign({}, lastCatalog, {
        catalog_format: document.getElementById('catalog_format').value
    });
}

async function saveCurrentCatalog() {
    if (!lastCatalog) {
        showToast('Build a catalog first.', 'warning');
        return;
    }
    const defaultName = 'catalog-' + new Date().toISOString().slice(0, 19).replace(/[:T]/g, '-');
    const name = prompt('Catalog name', defaultName);
    if (name === null) return;

    try {
        await postJson(API + '/catalogs', { name: name || null, catalog: catalogWithSelectedFormat() });
        showToast('Catalog saved', 'success');
        await refreshSavedCatalogs();
    } catch (err) {
        showToast(err.message, 'error');
    }
}

async function refreshSavedCatalogs() {
    const body = document.getElementById('savedCatalogBody');
    try {
        const response = await fetch(API + '/catalogs?limit=100');
        const rows = await response.json();
        if (!response.ok) throw new Error(rows.detail || 'Failed to load saved catalogs');

        if (!rows.length) {
            body.innerHTML = '<tr><td colspan="5" class="muted-note">No saved catalogs yet.</td></tr>';
            return;
        }

        body.innerHTML = rows.map(function (r, i) {
            const id = escapeHtml(r.id);
            return '<tr class="' + (i % 2 === 0 ? 'even' : 'odd') + '">' +
                '<td>' + escapeHtml(r.name) + '</td>' +
                '<td>' + r.total_items + '</td>' +
                '<td>' + r.total_groups + '</td>' +
                '<td class="muted-note">' + escapeHtml(formatDate(r.created_at)) + '</td>' +
                '<td><div class="dc-row-actions">' +
                '<button class="btn btn-secondary btn-sm" data-action="load" data-id="' + id + '">Load</button>' +
                '<button class="btn btn-secondary btn-sm" data-action="view" data-id="' + id + '">View</button>' +
                '<button class="btn btn-secondary btn-sm" data-action="export-flat" data-id="' + id + '">Export Flat</button>' +
                '<button class="btn btn-secondary btn-sm" data-action="export-grouped" data-id="' + id + '">Export Grouped</button>' +
                '<button class="btn btn-delete btn-sm" data-action="delete" data-id="' + id + '">Delete</button>' +
                '</div></td></tr>';
        }).join('');
    } catch (err) {
        body.innerHTML = '<tr><td colspan="5" style="color:#dc2626">' + escapeHtml(err.message) + '</td></tr>';
    }
}

async function loadSavedCatalog(catalogId) {
    try {
        const response = await fetch(API + '/catalogs/' + encodeURIComponent(catalogId));
        const data = await response.json();
        if (!response.ok) throw new Error(data.detail || 'Load failed');

        lastCatalog = data.catalog;
        renderCatalogSummary(lastCatalog, 'Loaded saved catalog: ' + data.name);
        toggleSiteFields();
        showToast('Loaded "' + data.name + '"', 'success');
    } catch (err) {
        showToast(err.message, 'error');
    }
}

async function viewSavedCatalog(catalogId) {
    try {
        const data = await postJson(API + '/catalogs/' + encodeURIComponent(catalogId) + '/viewer-session', {});
        window.open(data.viewer_url, '_blank');
    } catch (err) {
        showToast(err.message, 'error');
    }
}

function exportSavedCatalog(catalogId, format) {
    window.open(API + '/catalogs/' + encodeURIComponent(catalogId) +
        '/export?catalog_format=' + encodeURIComponent(format || 'both'), '_blank');
}

async function deleteSavedCatalog(catalogId) {
    if (!confirm('Delete this saved catalog?')) return;
    try {
        const response = await fetch(API + '/catalogs/' + encodeURIComponent(catalogId), { method: 'DELETE' });
        if (!response.ok) {
            const data = await response.json().catch(function () { return {}; });
            throw new Error(data.detail || 'Delete failed');
        }
        showToast('Catalog deleted', 'success');
        await refreshSavedCatalogs();
    } catch (err) {
        showToast(err.message, 'error');
    }
}

async function openInViewer() {
    if (!lastCatalog) {
        showToast('Build a catalog first.', 'warning');
        return;
    }
    try {
        const data = await postJson(API + '/viewer-session', catalogWithSelectedFormat());
        window.open(data.viewer_url, '_blank');
    } catch (err) {
        showToast(err.message, 'error');
    }
}

async function exportCatalog() {
    if (!lastCatalog) {
        showToast('Build a catalog first.', 'warning');
        return;
    }
    try {
        const response = await fetch(API + '/export', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(catalogWithSelectedFormat())
        });
        if (!response.ok) {
            const data = await response.json().catch(function () { return {}; });
            throw new Error(data.detail || 'Export failed');
        }

        const disposition = response.headers.get('Content-Disposition') || '';
        const match = disposition.match(/filename="([^"]+)"/);
        const blob = await response.blob();
        const url = URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = url;
        link.download = match ? match[1] : 'dataset_catalog.json';
        document.body.appendChild(link);
        link.click();
        link.remove();
        URL.revokeObjectURL(url);
    } catch (err) {
        showToast(err.message, 'error');
    }
}

// ── Wiring ──────────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', async function () {
    document.getElementById('btnScan').addEventListener('click', scanDataset);
    document.getElementById('btnBuild').addEventListener('click', buildCatalog);
    document.getElementById('btnSave').addEventListener('click', saveCurrentCatalog);
    document.getElementById('btnViewer').addEventListener('click', openInViewer);
    document.getElementById('btnExport').addEventListener('click', exportCatalog);
    document.getElementById('btnCopyPreview').addEventListener('click', copyLivePreview);
    document.getElementById('btnRefreshSaved').addEventListener('click', refreshSavedCatalogs);

    document.getElementById('toggleOptional').addEventListener('click', function () {
        const panel = document.getElementById('optionalOptions');
        const open = panel.style.display === 'none';
        panel.style.display = open ? '' : 'none';
        this.innerHTML = 'Optional settings ' + (open ? '&#9652;' : '&#9662;');
    });

    document.getElementById('shapeToggle').addEventListener('click', function (e) {
        const btn = e.target.closest('button[data-shape]');
        if (!btn) return;
        previewShape = btn.dataset.shape;
        this.querySelectorAll('button').forEach(function (b) {
            b.classList.toggle('active', b === btn);
        });
        renderLivePreview();
    });

    document.getElementById('liveSampleSize').addEventListener('input', updateLivePreview);
    document.getElementById('group_by_mode').addEventListener('change', toggleGroupingFields);
    document.getElementById('site_instance_mode').addEventListener('change', toggleSiteFields);

    // Live-preview copies write back to the sidebar, which drives everything else.
    MIRRORED_CONTROLS.forEach(function (pair) {
        const mirror = document.getElementById(pair[1]);
        ['input', 'change'].forEach(function (evt) {
            mirror.addEventListener(evt, function () {
                setIfChanged(document.getElementById(pair[0]), mirror.value);
                toggleGroupingFields();
            });
        });
    });

    ['filename_delimiter', 'filename_token_count', 'folder_segment_index',
        'regex_pattern', 'regex_group_index', 'manual_overrides',
        'site_instance_threshold', 'site_instance_pattern',
        'site_instance_folder_segment_index'
    ].forEach(function (id) {
        const el = document.getElementById(id);
        el.addEventListener('input', updateLivePreview);
        el.addEventListener('change', updateLivePreview);
    });

    document.getElementById('groupBody').addEventListener('change', function (e) {
        if (e.target.classList.contains('manual-site-checkbox')) updateLivePreview();
    });

    document.getElementById('savedCatalogBody').addEventListener('click', function (e) {
        const btn = e.target.closest('button[data-action]');
        if (!btn) return;
        const id = btn.dataset.id;
        switch (btn.dataset.action) {
            case 'load': loadSavedCatalog(id); break;
            case 'view': viewSavedCatalog(id); break;
            case 'export-flat': exportSavedCatalog(id, 'flat'); break;
            case 'export-grouped': exportSavedCatalog(id, 'grouped'); break;
            case 'delete': deleteSavedCatalog(id); break;
        }
    });

    toggleGroupingFields();
    toggleSiteFields();
    await refreshSavedCatalogs();
});
