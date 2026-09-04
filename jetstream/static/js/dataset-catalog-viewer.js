// Dataset Catalog Viewer - browse a catalog's images through the GCS proxy.

let catalogPayload = null;
let groupKeys = [];
let currentGroup = '';
let pageIndex = 0;

function getToken() {
    return new URLSearchParams(window.location.search).get('token') || '';
}

function currentUris() {
    if (!catalogPayload) return [];
    if (currentGroup === '__all__') {
        return catalogPayload.flat_instances || catalogPayload.instances || [];
    }
    const grouped = catalogPayload.grouped_instances || catalogPayload.instances_grouped || {};
    return grouped[currentGroup] || [];
}

function pageSize() {
    return parseInt(document.getElementById('dcv-page-size').value, 10);
}

function proxyUrl(uri) {
    return '/api/dataset-creator/proxy?gcs_uri=' + encodeURIComponent(uri);
}

function render() {
    const uris = currentUris();
    const size = pageSize();
    const maxPage = Math.max(0, Math.ceil(uris.length / size) - 1);
    pageIndex = Math.min(pageIndex, maxPage);

    const slice = uris.slice(pageIndex * size, pageIndex * size + size);
    const grid = document.getElementById('dcv-grid');

    if (!slice.length) {
        grid.innerHTML = '<p class="muted-note">No images in this group.</p>';
    } else {
        grid.innerHTML = '';
        slice.forEach(function (uri) {
            const item = document.createElement('div');
            item.className = 'thumbnail-item';

            const img = document.createElement('img');
            img.loading = 'lazy';
            img.alt = uri;
            img.src = proxyUrl(uri);
            img.addEventListener('click', function () { openPreview(uri); });
            img.addEventListener('error', function () {
                item.classList.add('thumbnail-error');
            });

            const caption = document.createElement('div');
            caption.className = 'thumbnail-caption';
            caption.textContent = uri.split('/').pop();
            caption.title = uri;

            item.appendChild(img);
            item.appendChild(caption);
            grid.appendChild(item);
        });
    }

    document.getElementById('dcv-status').textContent =
        uris.length + ' files in group · page ' + (pageIndex + 1) + ' of ' + (maxPage + 1);
    document.getElementById('dcv-prev').disabled = pageIndex === 0;
    document.getElementById('dcv-next').disabled = pageIndex >= maxPage;
}

function openPreview(uri) {
    document.getElementById('dcv-modal-title').textContent = uri;
    document.getElementById('dcv-modal-image').src = proxyUrl(uri);
    document.getElementById('dcv-modal').style.display = 'block';
}

function closePreview() {
    document.getElementById('dcv-modal').style.display = 'none';
    document.getElementById('dcv-modal-image').src = '';
}

async function loadCatalog() {
    const token = getToken();
    const status = document.getElementById('dcv-status');
    if (!token) {
        status.textContent = 'Missing viewer token. Open this page from the Dataset Creator.';
        return;
    }

    try {
        const response = await fetch('/api/dataset-creator/viewer-session/' + encodeURIComponent(token));
        const data = await response.json();
        if (!response.ok) throw new Error(data.detail || 'Viewer session not found or expired');

        catalogPayload = data;
        const grouped = catalogPayload.grouped_instances || catalogPayload.instances_grouped || {};
        const sites = catalogPayload.site_instances || {};
        groupKeys = Object.keys(grouped).sort();

        const select = document.getElementById('dcv-group');
        select.innerHTML = '';
        const allOption = document.createElement('option');
        allOption.value = '__all__';
        allOption.textContent = 'All files';
        select.appendChild(allOption);

        groupKeys.forEach(function (key) {
            const option = document.createElement('option');
            option.value = key;
            option.textContent = key + ' (' + grouped[key].length + ')' +
                (Object.prototype.hasOwnProperty.call(sites, key) ? ' · site' : '');
            select.appendChild(option);
        });

        currentGroup = '__all__';
        render();
    } catch (error) {
        status.textContent = error.message;
        showToast(error.message, 'error');
    }
}

document.addEventListener('DOMContentLoaded', async function () {
    document.getElementById('dcv-group').addEventListener('change', function (e) {
        currentGroup = e.target.value;
        pageIndex = 0;
        render();
    });
    document.getElementById('dcv-page-size').addEventListener('change', function () {
        pageIndex = 0;
        render();
    });
    document.getElementById('dcv-prev').addEventListener('click', function () {
        if (pageIndex > 0) { pageIndex -= 1; render(); }
    });
    document.getElementById('dcv-next').addEventListener('click', function () {
        pageIndex += 1;
        render();
    });
    document.getElementById('dcv-modal-close').addEventListener('click', closePreview);
    document.getElementById('dcv-modal').addEventListener('click', function (e) {
        if (e.target.id === 'dcv-modal') closePreview();
    });

    await loadCatalog();
});
