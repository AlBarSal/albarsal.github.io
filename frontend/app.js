'use strict';

// ── State ─────────────────────────────────────────────────────────────────
let _allCfps = [];
let _sources = [];
let _sourceTypes = [];
let _searches = [];
let _isLoading = false;
let _isSyncingSettings = false;
let _progressTimer = null;

const SOURCE_SETTING_SCHEMAS = {
  generic_html: [
    { key: 'item_selector', label: 'Item', placeholder: 'article, li, .call-item' },
    { key: 'title_selector', label: 'Título', placeholder: 'h2 a, h3 a, .title' },
    { key: 'url_selector', label: 'Enlace', placeholder: 'a, .title a' },
    { key: 'journal_selector', label: 'Revista', placeholder: '.journal, .publication' },
    { key: 'deadline_selector', label: 'Fecha límite', placeholder: '.deadline, time' },
    { key: 'description_selector', label: 'Descripción', placeholder: 'p, .summary, .description' },
  ],
  taylor_francis: [
    { key: 'api_url', label: 'API', type: 'url', placeholder: 'https://think.taylorandfrancis.com/wp-json/wp/v2/special_issues' },
    { key: 'page_size', label: 'Items por página', type: 'number', placeholder: '100' },
    { key: 'max_pages', label: 'Páginas máximas', type: 'number', placeholder: '10' },
    { key: 'max_detail_fetch', label: 'Detalles', type: 'number', placeholder: '60' },
    { key: 'concurrency', label: 'Paralelismo', type: 'number', placeholder: '8' },
  ],
  apa: [],
  sage: [],
  sciencedirect: [
    { key: 'count', label: 'Máximo resultados', type: 'number', placeholder: 'Vacío = todos' },
    { key: 'months', label: 'Meses fallback', type: 'number', placeholder: '12' },
  ],
};

// ── DOM refs ──────────────────────────────────────────────────────────────
const $ = id => document.getElementById(id);
const grid          = $('results-grid');
const loading       = $('loading');
const errorBox      = $('error-box');
const errorMsg      = $('error-msg');
const statsRow      = $('stats-row');
const statCount     = $('stat-count');
const statCache     = $('stat-cache');
const sourcePills   = $('source-statuses');
const progressPanel = $('progress-panel');
const progressSummary = $('progress-summary');
const progressMeta  = $('progress-meta');
const progressList  = $('progress-list');
const emptyState    = $('empty-state');
const statusBar     = $('status-bar');
const usagePanel    = $('usage-panel');
const btnRefresh    = $('btn-refresh');
const btnIcon       = btnRefresh.querySelector('.btn-icon');
const headerSub     = $('header-sub');
const sourceSelect  = $('select-source');
const sourcesPanel  = $('sources-panel');
const sourcesList   = $('sources-list');
const sourceType    = $('source-type');
const guidedSettings = $('guided-settings');
const sourceFormErr = $('source-form-error');
const searchesPanel = $('searches-panel');
const searchesList  = $('searches-list');
const searchFormErr = $('search-form-error');

// ── Init ──────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', init);

async function init() {
  await Promise.all([loadSources(), loadSearches()]);
  resetSourceForm();
  resetSearchForm();
  setDemandReadyState();
}

// ── Fetch ─────────────────────────────────────────────────────────────────
async function fetchJson(url, options = {}) {
  const resp = await fetch(url, {
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    ...options,
  });
  const json = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    throw new Error(json.detail || json.error || `HTTP ${resp.status} — ${resp.statusText}`);
  }
  return json;
}

async function loadData(forceRefresh = false) {
  if (_isLoading) return;
  _isLoading = true;
  setLoading(true);
  hideUsagePanel();
  hideError();
  setStatusBar('info', forceRefresh ? 'Consultando fuentes…' : 'Cargando datos en caché…');
  if (forceRefresh) startProgressPolling();
  else hideProgressPanel();

  try {
    const url = forceRefresh ? '/api/cfp?refresh=true' : '/api/cfp';
    const json = await fetchJson(url);
    if (json.error) throw new Error(json.error);

    _allCfps = json.data || [];
    renderSourceStatuses(json.meta?.statuses || []);
    if (forceRefresh) renderProgress(json.meta?.progress || buildFinalProgress(json.meta));
    renderStats(json.meta);
    hideStatusBar();
    applyFilters();
    await Promise.all([loadSources(), loadSearches()]);
  } catch (err) {
    if (forceRefresh) await loadProgress().catch(() => {});
    showError(`No se pudieron cargar los datos: ${err.message}`);
    setStatusBar('error', `Error al cargar: ${err.message}`);
    renderGrid([]);
  } finally {
    if (forceRefresh) stopProgressPolling();
    setLoading(false);
    _isLoading = false;
  }
}

async function loadSources() {
  try {
    const [sourcesJson, typesJson] = await Promise.all([
      fetchJson('/api/sources'),
      fetchJson('/api/source-types'),
    ]);
    _sources = sourcesJson.data || [];
    _sourceTypes = typesJson.data || [];
    renderHeaderSub();
    renderSourceFilter();
    renderSourceTypeOptions();
    renderSources();
  } catch (err) {
    showError(`No se pudieron cargar las fuentes: ${err.message}`);
  }
}

async function loadSearches() {
  try {
    const json = await fetchJson('/api/searches');
    _searches = json.data || [];
    renderSearches();
  } catch (err) {
    showError(`No se pudieron cargar las búsquedas: ${err.message}`);
  }
}

// ── Filter ────────────────────────────────────────────────────────────────
function applyFilters() {
  const q = $('input-search').value.trim().toLowerCase();
  const source = sourceSelect.value.toLowerCase();
  if (_allCfps.length > 0) hideUsagePanel();
  else showUsagePanel();

  const filtered = _allCfps.filter(cfp => {
    const matchSrc = !source || cfp.source.toLowerCase() === source;
    const matchQ = !q
      || cfp.title.toLowerCase().includes(q)
      || (cfp.journal !== 'No disponible' && cfp.journal.toLowerCase().includes(q))
      || (cfp.description !== 'No disponible' && cfp.description.toLowerCase().includes(q));
    return matchSrc && matchQ;
  });

  renderGrid(filtered);
  statCount.innerHTML = `<strong>${filtered.length}</strong> resultado${filtered.length !== 1 ? 's' : ''}`;
  statsRow.classList.toggle('hidden', _allCfps.length === 0);
  emptyState.classList.toggle('hidden', filtered.length > 0 || _allCfps.length === 0);
}

// ── Render CFP grid ───────────────────────────────────────────────────────
function renderGrid(cfps) {
  if (cfps.length === 0) {
    grid.innerHTML = '';
    return;
  }
  grid.innerHTML = cfps.map(buildCard).join('');
}

function buildCard(cfp) {
  const badgeClass = sourceBadgeClass(cfp.source);
  const sourceLabel = esc(cfp.source);
  const journalVal = cfp.journal !== 'No disponible'
    ? esc(cfp.journal)
    : '<span class="na">No disponible</span>';
  const deadlineVal = cfp.deadline !== 'No disponible'
    ? `<span class="deadline">${esc(cfp.deadline)}</span>`
    : '<span class="na">No disponible</span>';
  const descVal = cfp.description !== 'No disponible' ? esc(cfp.description) : null;
  const hasUrl = cfp.url && cfp.url !== 'No disponible';

  return `
    <article class="cfp-card">
      <div class="card-header">
        <h2 class="card-title">${esc(cfp.title)}</h2>
        <span class="source-badge ${badgeClass}">${sourceLabel}</span>
      </div>
      <div class="card-meta">
        <div class="meta-row">
          <span class="meta-label">Revista</span>
          <span class="meta-value">${journalVal}</span>
        </div>
        <div class="meta-row">
          <span class="meta-label">Fecha límite</span>
          <span class="meta-value">${deadlineVal}</span>
        </div>
      </div>
      ${descVal ? `<p class="card-description">${descVal}</p>` : ''}
      <footer class="card-footer">
        ${hasUrl
          ? `<a class="card-link" href="${esc(cfp.url)}" target="_blank" rel="noopener noreferrer">
               Ver convocatoria ↗
             </a>`
          : '<span class="card-link na">URL no disponible</span>'
        }
      </footer>
    </article>`;
}

function sourceBadgeClass(source) {
  const lower = source.toLowerCase();
  if (lower.includes('taylor')) return 'tf';
  if (lower.includes('apa')) return 'apa';
  return 'generic';
}

// ── Sources admin ─────────────────────────────────────────────────────────
function toggleSourcesPanel() {
  sourcesPanel.classList.toggle('hidden');
  if (!sourcesPanel.classList.contains('hidden')) {
    loadSources();
  }
}

function openSourcesPanel() {
  sourcesPanel.classList.remove('hidden');
  loadSources();
  sourcesPanel.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function renderSources() {
  if (!_sources.length) {
    sourcesList.innerHTML = '<div class="source-row"><div>No hay fuentes configuradas.</div></div>';
    return;
  }

  sourcesList.innerHTML = _sources.map(source => {
    const statusText = source.last_run_at
      ? `${source.last_success ? 'OK' : 'Error'} · ${source.last_count || 0} resultados · ${formatDate(source.last_run_at)}`
      : 'Sin ejecuciones';
    const enabledAction = source.enabled
      ? `<button class="btn-row warn" type="button" onclick="toggleSource(${source.id}, false)">Desactivar</button>`
      : `<button class="btn-row" type="button" onclick="toggleSource(${source.id}, true)">Activar</button>`;

    return `
      <article class="source-row">
        <div>
          <div class="source-row-title">
            <span>${esc(source.name)}</span>
            <span class="source-type-pill">${esc(sourceTypeLabel(source.scraper_type))}</span>
            <span class="enabled-pill ${source.enabled ? 'on' : 'off'}">${source.enabled ? 'Activa' : 'Inactiva'}</span>
          </div>
          <div class="source-row-meta">${esc(source.url)}</div>
          <div class="source-row-meta">${esc(statusText)}</div>
          ${source.last_error ? `<div class="source-row-meta">${esc(source.last_error)}</div>` : ''}
        </div>
        <div class="source-row-actions">
          <button class="btn-row" type="button" onclick="editSource(${source.id})">Editar</button>
          ${enabledAction}
          <button class="btn-row" type="button" onclick="testSource(${source.id})">Probar</button>
          <button class="btn-row danger" type="button" onclick="deleteSource(${source.id})">Borrar</button>
        </div>
      </article>`;
  }).join('');
}

function renderSourceFilter() {
  const previous = sourceSelect.value;
  const enabledSources = _sources.filter(source => source.enabled);
  sourceSelect.innerHTML = [
    '<option value="">Todas las fuentes</option>',
    ...enabledSources.map(source => `<option value="${esc(source.name)}">${esc(source.name)}</option>`),
  ].join('');

  const stillExists = enabledSources.some(source => source.name === previous);
  sourceSelect.value = stillExists ? previous : '';
}

function renderSourceTypeOptions() {
  const previous = sourceType.value;
  sourceType.innerHTML = _sourceTypes
    .map(type => `<option value="${esc(type.type)}">${esc(type.label)}</option>`)
    .join('');
  if (_sourceTypes.some(type => type.type === previous)) {
    sourceType.value = previous;
  }
  renderGuidedSettings();
}

function renderHeaderSub() {
  const activeNames = _sources.filter(source => source.enabled).map(source => source.name);
  headerSub.textContent = activeNames.length ? activeNames.join(' · ') : 'Sin fuentes activas';
}

function resetSourceForm() {
  $('source-id').value = '';
  $('source-name').value = '';
  $('source-url').value = '';
  $('source-enabled').checked = true;
  $('source-settings').value = '{}';
  hideSourceFormError();

  if (_sourceTypes.some(type => type.type === 'generic_html')) {
    sourceType.value = 'generic_html';
  } else if (_sourceTypes[0]) {
    sourceType.value = _sourceTypes[0].type;
  }
  renderGuidedSettings();
}

function editSource(sourceId) {
  const source = _sources.find(item => item.id === sourceId);
  if (!source) return;

  sourcesPanel.classList.remove('hidden');
  $('source-id').value = source.id;
  $('source-name').value = source.name;
  sourceType.value = source.scraper_type;
  $('source-url').value = source.url;
  $('source-enabled').checked = source.enabled;
  $('source-settings').value = JSON.stringify(source.settings || {}, null, 2);
  renderGuidedSettings(source.settings || {});
  hideSourceFormError();
}

function handleSourceTypeChange(applyDefaults = false) {
  if (applyDefaults) {
    const defaults = defaultSettingsForType(sourceType.value);
    $('source-settings').value = JSON.stringify(defaults, null, 2);
    renderGuidedSettings(defaults);
    return;
  }
  renderGuidedSettings();
}

function renderGuidedSettings(settings = currentSettingsFromJson()) {
  const schema = SOURCE_SETTING_SCHEMAS[sourceType.value] || [];
  if (schema.length === 0) {
    guidedSettings.innerHTML = `
      <div class="settings-empty">
        <span class="source-type-pill">${esc(sourceTypeLabel(sourceType.value))}</span>
        <span>Sin parámetros adicionales</span>
      </div>`;
    return;
  }

  guidedSettings.innerHTML = `
    <div class="settings-grid">
      ${schema.map(field => buildSettingField(field, settings[field.key])).join('')}
    </div>`;
}

function buildSettingField(field, value) {
  return `
    <label>
      ${esc(field.label)}
      <input
        type="${esc(field.type || 'text')}"
        data-setting-key="${esc(field.key)}"
        value="${esc(value ?? '')}"
        placeholder="${esc(field.placeholder || '')}"
        oninput="syncJsonFromGuidedSettings()"
      />
    </label>`;
}

function syncJsonFromGuidedSettings() {
  if (_isSyncingSettings) return;
  _isSyncingSettings = true;
  const base = currentSettingsFromJson({ silent: true });
  const settings = collectGuidedSettings(base);
  $('source-settings').value = JSON.stringify(settings, null, 2);
  _isSyncingSettings = false;
}

function syncGuidedSettingsFromJson() {
  if (_isSyncingSettings) return;
  renderGuidedSettings(currentSettingsFromJson({ silent: true }));
}

function collectGuidedSettings(base = {}) {
  const fields = [...guidedSettings.querySelectorAll('[data-setting-key]')];
  const settings = { ...base };
  return fields.reduce((settings, field) => {
    const key = field.dataset.settingKey;
    const raw = field.value.trim();
    if (!raw) {
      delete settings[key];
      return settings;
    }
    settings[key] = field.type === 'number' ? Number(raw) : raw;
    return settings;
  }, settings);
}

function currentSettingsFromJson(options = {}) {
  try {
    const parsed = JSON.parse($('source-settings').value || '{}');
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed : {};
  } catch (err) {
    if (!options.silent) showSourceFormError(`JSON inválido: ${err.message}`);
    return {};
  }
}

function defaultSettingsForType(type) {
  if (type === 'taylor_francis') {
    return {
      api_url: 'https://think.taylorandfrancis.com/wp-json/wp/v2/special_issues',
      page_size: 100,
      max_pages: 10,
      max_detail_fetch: 60,
      concurrency: 8,
    };
  }
  return {};
}

async function saveSource(event) {
  event.preventDefault();
  hideSourceFormError();

  const sourceId = $('source-id').value;
  let settings = {};
  if (sourceId) {
    try {
      const advanced = JSON.parse($('source-settings').value || '{}');
      if (!advanced || typeof advanced !== 'object' || Array.isArray(advanced)) {
        throw new Error('Debe ser un objeto JSON');
      }
      settings = collectGuidedSettings(advanced);
    } catch (err) {
      showSourceFormError(`JSON inválido: ${err.message}`);
      return;
    }
  }

  const payload = sourceId ? {
    name: $('source-name').value.trim(),
    scraper_type: sourceType.value,
    url: $('source-url').value.trim(),
    enabled: $('source-enabled').checked,
    settings,
  } : {
    name: $('source-name').value.trim(),
    url: $('source-url').value.trim(),
    enabled: $('source-enabled').checked,
  };

  try {
    setStatusBar('info', sourceId ? 'Guardando fuente…' : 'Autodescubriendo fuente…');
    await fetchJson(sourceId ? `/api/sources/${sourceId}` : '/api/sources', {
      method: sourceId ? 'PUT' : 'POST',
      body: JSON.stringify(payload),
    });
    resetSourceForm();
    await loadSources();
    setDemandReadyState('Fuente guardada. Consulta las fuentes cuando quieras actualizar los resultados.');
  } catch (err) {
    showSourceFormError(err.message);
    setStatusBar('error', `Error al guardar fuente: ${err.message}`);
  }
}

async function toggleSource(sourceId, enabled) {
  try {
    setStatusBar('info', enabled ? 'Activando fuente…' : 'Desactivando fuente…');
    await fetchJson(`/api/sources/${sourceId}/${enabled ? 'enable' : 'disable'}`, { method: 'PATCH' });
    await loadSources();
    setDemandReadyState(enabled
      ? 'Fuente activada. Consulta las fuentes para actualizar los resultados.'
      : 'Fuente desactivada. Consulta las fuentes para actualizar los resultados.');
  } catch (err) {
    setStatusBar('error', `Error al cambiar fuente: ${err.message}`);
  }
}

async function testSource(sourceId) {
  const source = _sources.find(item => item.id === sourceId);
  try {
    setStatusBar('info', `Probando ${source ? source.name : 'fuente'}…`);
    const json = await fetchJson(`/api/sources/${sourceId}/test`, { method: 'POST' });
    renderSourceStatuses(json.meta?.statuses || []);
    await loadSources();
    setStatusBar('info', `Prueba terminada: ${json.meta?.total || 0} resultados`);
  } catch (err) {
    setStatusBar('error', `Error al probar fuente: ${err.message}`);
  }
}

async function deleteSource(sourceId) {
  const source = _sources.find(item => item.id === sourceId);
  if (!confirm(`¿Borrar la fuente "${source ? source.name : sourceId}"?`)) return;

  try {
    setStatusBar('info', 'Borrando fuente…');
    await fetchJson(`/api/sources/${sourceId}`, { method: 'DELETE' });
    await loadSources();
    setDemandReadyState('Fuente borrada. Consulta las fuentes para actualizar los resultados.');
  } catch (err) {
    setStatusBar('error', `Error al borrar fuente: ${err.message}`);
  }
}

function sourceTypeLabel(type) {
  return _sourceTypes.find(item => item.type === type)?.label || type;
}

function showSourceFormError(msg) {
  sourceFormErr.textContent = msg;
  sourceFormErr.classList.remove('hidden');
}

function hideSourceFormError() {
  sourceFormErr.classList.add('hidden');
}

// ── Searches admin ────────────────────────────────────────────────────────
function toggleSearchesPanel() {
  searchesPanel.classList.toggle('hidden');
  if (!searchesPanel.classList.contains('hidden')) {
    loadSearches();
  }
}

function openSearchesPanel() {
  searchesPanel.classList.remove('hidden');
  loadSearches();
  searchesPanel.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function renderSearches() {
  if (!_searches.length) {
    searchesList.innerHTML = '<div class="source-row"><div>No hay búsquedas configuradas.</div></div>';
    return;
  }

  searchesList.innerHTML = _searches.map(search => {
    const checkedText = search.last_checked_at
      ? `Comprobada · ${search.last_match_count || 0} coincidencias · ${formatDate(search.last_checked_at)}`
      : 'Sin comprobaciones';
    const notifiedText = search.last_notified_at
      ? `Último aviso · ${formatDate(search.last_notified_at)}`
      : 'Sin avisos enviados';
    const enabledAction = search.enabled
      ? `<button class="btn-row warn" type="button" onclick="toggleSearch(${search.id}, false)">Desactivar</button>`
      : `<button class="btn-row" type="button" onclick="toggleSearch(${search.id}, true)">Activar</button>`;

    return `
      <article class="source-row">
        <div>
          <div class="source-row-title">
            <span>${esc(search.name)}</span>
            <span class="enabled-pill ${search.enabled ? 'on' : 'off'}">${search.enabled ? 'Activa' : 'Inactiva'}</span>
          </div>
          <div class="source-row-meta">${esc(search.email)}</div>
          <div class="source-row-meta">${esc(search.keywords_text)}</div>
          <div class="source-row-meta">${esc(checkedText)}</div>
          <div class="source-row-meta">${esc(notifiedText)}</div>
          ${search.last_error ? `<div class="source-row-meta error-text">${esc(search.last_error)}</div>` : ''}
        </div>
        <div class="source-row-actions">
          <button class="btn-row" type="button" onclick="editSearch(${search.id})">Editar</button>
          ${enabledAction}
          <button class="btn-row danger" type="button" onclick="deleteSearch(${search.id})">Borrar</button>
        </div>
      </article>`;
  }).join('');
}

function resetSearchForm() {
  $('saved-search-id').value = '';
  $('saved-search-name').value = '';
  $('saved-search-email').value = '';
  $('saved-search-keywords').value = '';
  $('saved-search-enabled').checked = true;
  hideSearchFormError();
}

function editSearch(searchId) {
  const search = _searches.find(item => item.id === searchId);
  if (!search) return;

  searchesPanel.classList.remove('hidden');
  $('saved-search-id').value = search.id;
  $('saved-search-name').value = search.name;
  $('saved-search-email').value = search.email;
  $('saved-search-keywords').value = search.keywords_text;
  $('saved-search-enabled').checked = search.enabled;
  hideSearchFormError();
}

async function saveSearch(event) {
  event.preventDefault();
  hideSearchFormError();

  const searchId = $('saved-search-id').value;
  const payload = {
    name: $('saved-search-name').value.trim(),
    email: $('saved-search-email').value.trim(),
    keywords_text: $('saved-search-keywords').value.trim(),
    enabled: $('saved-search-enabled').checked,
  };

  try {
    setStatusBar('info', searchId ? 'Guardando búsqueda…' : 'Creando búsqueda…');
    await fetchJson(searchId ? `/api/searches/${searchId}` : '/api/searches', {
      method: searchId ? 'PUT' : 'POST',
      body: JSON.stringify(payload),
    });
    resetSearchForm();
    await loadSearches();
    setStatusBar('info', 'Búsqueda guardada');
  } catch (err) {
    showSearchFormError(err.message);
    setStatusBar('error', `Error al guardar búsqueda: ${err.message}`);
  }
}

async function toggleSearch(searchId, enabled) {
  try {
    setStatusBar('info', enabled ? 'Activando búsqueda…' : 'Desactivando búsqueda…');
    await fetchJson(`/api/searches/${searchId}/${enabled ? 'enable' : 'disable'}`, { method: 'PATCH' });
    await loadSearches();
    setStatusBar('info', enabled ? 'Búsqueda activada' : 'Búsqueda desactivada');
  } catch (err) {
    setStatusBar('error', `Error al cambiar búsqueda: ${err.message}`);
  }
}

async function deleteSearch(searchId) {
  const search = _searches.find(item => item.id === searchId);
  if (!confirm(`¿Borrar la búsqueda "${search ? search.name : searchId}"?`)) return;

  try {
    setStatusBar('info', 'Borrando búsqueda…');
    await fetchJson(`/api/searches/${searchId}`, { method: 'DELETE' });
    await loadSearches();
    setStatusBar('info', 'Búsqueda borrada');
  } catch (err) {
    setStatusBar('error', `Error al borrar búsqueda: ${err.message}`);
  }
}

function showSearchFormError(msg) {
  searchFormErr.textContent = msg;
  searchFormErr.classList.remove('hidden');
}

function hideSearchFormError() {
  searchFormErr.classList.add('hidden');
}

// ── Source statuses ───────────────────────────────────────────────────────
function renderSourceStatuses(statuses) {
  if (!statuses || statuses.length === 0) {
    sourcePills.classList.add('hidden');
    return;
  }
  sourcePills.innerHTML = statuses.map(s => {
    const cls = s.success ? 'ok' : 'err';
    const label = s.success
      ? `${esc(s.source)}: ${s.count} resultados`
      : `${esc(s.source)}: error — ${esc(s.error || 'desconocido')}`;
    return `<span class="source-pill ${cls}"><span class="dot"></span>${label}</span>`;
  }).join('');
  sourcePills.classList.remove('hidden');
}

// ── Refresh progress ──────────────────────────────────────────────────────
function startProgressPolling() {
  stopProgressPolling();
  renderProgress(buildInitialProgress());
  _progressTimer = window.setInterval(() => {
    loadProgress().catch(() => {});
  }, 900);
  window.setTimeout(() => {
    if (_progressTimer) loadProgress().catch(() => {});
  }, 300);
}

function stopProgressPolling() {
  if (!_progressTimer) return;
  window.clearInterval(_progressTimer);
  _progressTimer = null;
}

async function loadProgress() {
  const json = await fetchJson('/api/cfp/progress');
  renderProgress(json.data);
  return json.data;
}

function buildInitialProgress() {
  const activeSources = _sources.filter(source => source.enabled);
  const activeSearches = _searches.filter(search => search.enabled);
  return {
    active: true,
    phase: 'preparing',
    message: 'Preparando consulta',
    total_sources: activeSources.length,
    completed_sources: 0,
    total_items: 0,
    sources: activeSources.map(source => ({
      source_id: source.id,
      source: source.name,
      state: 'pending',
      count: 0,
    })),
    total_searches: activeSearches.length,
    completed_searches: 0,
    searches: [],
  };
}

function buildFinalProgress(meta) {
  const statuses = meta?.statuses || [];
  const notifications = meta?.search_notifications || [];
  return {
    active: false,
    phase: 'complete',
    message: 'Consulta completada',
    total_sources: statuses.length,
    completed_sources: statuses.length,
    total_items: meta?.total || _allCfps.length,
    sources: statuses.map(status => ({
      source_id: status.source_id,
      source: status.source,
      state: status.success ? 'done' : 'error',
      success: status.success,
      count: status.count || 0,
      error: status.error || null,
    })),
    total_searches: notifications.length,
    completed_searches: notifications.length,
    searches: notifications.map(item => ({
      search_id: item.search_id,
      search: item.search,
      state: item.error ? 'error' : 'done',
      match_count: item.match_count || 0,
      notified: item.notified,
      error: item.error || null,
    })),
  };
}

function renderProgress(progress) {
  if (!progress || (!progress.active && progress.phase === 'idle')) {
    hideProgressPanel();
    return;
  }

  progressPanel.classList.remove('hidden');
  progressSummary.textContent = progress.message || progressPhaseLabel(progress.phase);
  progressMeta.textContent = progressMetaText(progress);

  const percent = progressPercent(progress);
  const parts = [
    `<div class="progress-bar" aria-hidden="true"><span style="width:${percent}%"></span></div>`,
  ];

  if ((progress.sources || []).length) {
    parts.push('<div class="progress-section-label">Fuentes</div>');
    parts.push(...progress.sources.map(source => buildProgressRow(
      source.source,
      source.state,
      sourceProgressDetail(source),
      source.error,
    )));
  }

  if ((progress.searches || []).length) {
    parts.push('<div class="progress-section-label">Búsquedas</div>');
    parts.push(...progress.searches.map(search => buildProgressRow(
      search.search,
      search.state,
      searchProgressDetail(search),
      search.error,
    )));
  }

  progressList.innerHTML = parts.join('');
}

function buildProgressRow(label, state, detail, error) {
  const cls = progressStateClass(state);
  const detailText = error || detail;
  return `
    <div class="progress-row ${cls}">
      <span class="progress-dot"></span>
      <span class="progress-name">${esc(label)}</span>
      <span class="progress-state">${esc(progressStateLabel(state))}</span>
      <span class="progress-detail">${esc(detailText)}</span>
    </div>`;
}

function progressMetaText(progress) {
  const parts = [];
  const sourceTotal = Number(progress.total_sources || 0);
  const searchTotal = Number(progress.total_searches || 0);
  if (sourceTotal) parts.push(`${progress.completed_sources || 0}/${sourceTotal} fuentes`);
  if (searchTotal) parts.push(`${progress.completed_searches || 0}/${searchTotal} búsquedas`);
  parts.push(`${progress.total_items || 0} resultados`);
  if (progress.elapsed_seconds !== null && progress.elapsed_seconds !== undefined) {
    parts.push(formatElapsed(progress.elapsed_seconds));
  }
  return parts.join(' · ');
}

function progressPercent(progress) {
  if (progress.phase === 'complete') return 100;
  const sourceTotal = Number(progress.total_sources || 0);
  const searchTotal = Number(progress.total_searches || 0);
  if (progress.phase === 'notifications' && searchTotal) {
    return Math.round(((progress.completed_searches || 0) / searchTotal) * 100);
  }
  if (sourceTotal) {
    return Math.round(((progress.completed_sources || 0) / sourceTotal) * 100);
  }
  return progress.active ? 8 : 0;
}

function sourceProgressDetail(source) {
  if (source.state === 'done') return `${source.count || 0} resultados`;
  if (source.state === 'error') return source.error || 'Error desconocido';
  if (source.state === 'running') return 'Consultando';
  return 'En espera';
}

function searchProgressDetail(search) {
  if (search.state === 'running') return 'Calculando coincidencias';
  if (search.state === 'error') return search.error || 'Error desconocido';
  if (search.state === 'done') {
    const matches = `${search.match_count || 0} coincidencia${search.match_count === 1 ? '' : 's'}`;
    return search.notified ? `${matches} · aviso enviado` : matches;
  }
  return 'En espera';
}

function progressPhaseLabel(phase) {
  if (phase === 'scraping') return 'Consultando fuentes';
  if (phase === 'notifications') return 'Comprobando búsquedas guardadas';
  if (phase === 'complete') return 'Consulta completada';
  if (phase === 'error') return 'Consulta interrumpida';
  return 'Preparando consulta';
}

function progressStateLabel(state) {
  if (state === 'running') return 'En curso';
  if (state === 'done') return 'OK';
  if (state === 'error') return 'Error';
  return 'Pendiente';
}

function progressStateClass(state) {
  if (state === 'running') return 'running';
  if (state === 'done') return 'done';
  if (state === 'error') return 'error';
  return 'pending';
}

function hideProgressPanel() {
  progressPanel.classList.add('hidden');
}

// ── Stats ─────────────────────────────────────────────────────────────────
function renderStats(meta) {
  if (!meta) return;
  const ts = meta.cached_at ? formatDate(meta.cached_at) : '—';
  statCache.textContent = `Actualizado: ${ts}`;
}

// ── UI helpers ────────────────────────────────────────────────────────────
function setLoading(on) {
  loading.classList.toggle('hidden', !on);
  btnRefresh.disabled = on;
  btnIcon.textContent = '↻';
  if (on) btnIcon.classList.add('spinning');
  else btnIcon.classList.remove('spinning');
}

function showError(msg) {
  errorMsg.textContent = msg;
  errorBox.classList.remove('hidden');
}

function hideError() {
  errorBox.classList.add('hidden');
}

function setStatusBar(type, msg) {
  statusBar.textContent = msg;
  statusBar.className = `status-bar ${type}`;
  statusBar.classList.remove('hidden');
}

function hideStatusBar() {
  statusBar.classList.add('hidden');
}

function setDemandReadyState(message = 'Consulta las fuentes para cargar resultados.') {
  _allCfps = [];
  renderGrid([]);
  statsRow.classList.add('hidden');
  sourcePills.classList.add('hidden');
  hideProgressPanel();
  emptyState.classList.add('hidden');
  showUsagePanel();
  setStatusBar('info', message);
}

function showUsagePanel() {
  usagePanel.classList.remove('hidden');
}

function hideUsagePanel() {
  usagePanel.classList.add('hidden');
}

function formatDate(value) {
  return new Date(value).toLocaleString('es-ES');
}

function formatElapsed(seconds) {
  const total = Math.max(0, Math.round(Number(seconds) || 0));
  const minutes = Math.floor(total / 60);
  const rest = total % 60;
  return minutes ? `${minutes}m ${rest}s` : `${rest}s`;
}

// Escape HTML to prevent XSS from scraped and persisted data
function esc(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}
