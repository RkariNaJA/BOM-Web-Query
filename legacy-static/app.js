/* BOM Query Web -- front end.
   One screen over the source view. The column picker is deliberately
   client-side only: the server always fetches all 60 columns and projects, so
   toggling visibility never re-runs a query that can cost 5-40 s. */

const state = {
  limit: '100',
  page: 1,
  pageSize: 100,
  partial: false,
  allColumns: [],
  visible: new Set(),
  pinned: 'BOM_ROW_NBR',
  groups: [],
  // Filter spec from /api/meta, plus the current value of each field keyed by
  // query-param name. Nothing here is hardcoded per column.
  filterSpec: [],
  values: {},
  // Measured seconds each expensive column adds, and the column set the server
  // currently holds for this filter. Anything inside `fetched` can be shown
  // without a new query; anything outside it costs one.
  costs: {},
  fetched: new Set(),
  busy: false,
};

const $ = (id) => document.getElementById(id);
const fmt = (n) => (n === null || n === undefined ? '—' : n.toLocaleString('en-US'));

function escapeHtml(value) {
  return String(value)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function setConn(kind, text) {
  $('connGlyph').className = 'glyph ' + kind;
  $('connText').textContent = text;
}

function showNotice(text) {
  $('noticeText').textContent = text;
  $('notice').classList.remove('hidden');
}

// --- Boot ---------------------------------------------------------------

async function boot() {
  buildSegmented('rowLimit', ['100', '1000', '10000', 'all'],
    (v) => (v === 'all' ? 'ALL' : Number(v).toLocaleString('en-US')),
    (v) => { state.limit = v; state.page = 1; onLimitChange(); });

  buildSegmented('pageSize', [100, 250, 500, 1000],
    (v) => v.toLocaleString('en-US'),
    (v) => { state.pageSize = v; state.page = 1; if (hasRun) search(); });

  wireStaticControls();
  onLimitChange();

  try {
    const health = await fetch('/api/health').then(readJson);
    setConn('ready', 'connected');
    $('source').textContent = `${health.database} / ${health.view}`;
  } catch (err) {
    setConn('error', 'not connected');
    fail(`Cannot reach the database. ${err.message}`);
    return;
  }

  try {
    const meta = await fetch('/api/meta').then(readJson);
    state.allColumns = meta.columns.map((c) => c.name);
    state.groups = meta.groups;
    state.pinned = meta.pinned;
    state.filterSpec = meta.filters;
    state.costs = meta.column_costs || {};
    // Start from the server's default set, which omits the two nvarchar(max)
    // detection columns at ~60 s each.
    state.defaultColumns = meta.default_columns;
    state.visible = new Set(meta.default_columns);
    $('source').textContent = meta.source;
    $('totalRows').textContent = `${fmt(meta.total_rows)} rows`;
    buildFilterFields();
    buildPicker();
    if (meta.total_rows === null) pollTotal();
  } catch (err) {
    fail(`Could not load column metadata. ${err.message}`);
    return;
  }
}

/* /api/meta only peeks at the cached row count, so on a cold server it comes
   back null. Check back a few times while the background warm-up runs, then
   give up quietly -- the header total is informational only. */
async function pollTotal(attempt = 0) {
  if (attempt >= 6) return;
  await new Promise((resolve) => setTimeout(resolve, 10000));
  try {
    const meta = await fetch('/api/meta').then(readJson);
    if (meta.total_rows !== null) {
      $('totalRows').textContent = `${fmt(meta.total_rows)} rows`;
      return;
    }
  } catch (_) { /* leave the dash in place */ }
  pollTotal(attempt + 1);
}

async function readJson(response) {
  if (!response.ok) {
    let detail = `HTTP ${response.status}`;
    try { detail = (await response.json()).detail || detail; } catch (_) {}
    throw new Error(detail);
  }
  return response.json();
}

function fail(message) {
  $('tableWrap').classList.add('hidden');
  const holder = $('placeholder');
  holder.classList.remove('hidden');
  holder.classList.add('error');
  $('placeholderText').textContent = message;
  $('placeholderHint').textContent = '';
}

// --- Segmented controls -------------------------------------------------

function buildSegmented(hostId, values, label, onPick) {
  const host = $(hostId);
  host.innerHTML = '';
  values.forEach((value, index) => {
    const button = document.createElement('button');
    button.textContent = label(value);
    button.className = index === 0 ? 'active' : '';
    button.onclick = () => {
      [...host.children].forEach((child) => child.classList.remove('active'));
      button.classList.add('active');
      onPick(value);
    };
    host.appendChild(button);
  });
}

function onLimitChange() {
  const isAll = state.limit === 'all';
  $('rowLimitNote').textContent = isAll
    ? `pages at ${state.pageSize} rows/page`
    : 'capped, fetched once then paged in memory';
  if (isAll) {
    showNotice(
      'ALL selected — the full filtered set streams to CSV; the table pages ' +
      'through it. Unfiltered deep pages are slow (the view scans everything ' +
      'it skips), so filter by style where you can.'
    );
  }
}

// --- Static controls ----------------------------------------------------

let hasRun = false;

function wireStaticControls() {
  $('searchBtn').onclick = () => { state.page = 1; search(); };

  $('resetBtn').onclick = () => {
    Object.keys(state.values).forEach((key) => { state.values[key] = ''; });
    combos.forEach((combo) => combo.clear());
    $('filterFields')
      .querySelectorAll('input[type="date"]')
      .forEach((input) => { input.value = ''; });
    state.partial = false;
    state.page = 1;
    setToggle(false);
    // Back to the default set, not all 60 -- resetting should not quietly
    // re-enable the two ~60 s columns.
    state.visible = new Set(state.defaultColumns);
    syncPicker();
    markStale(false);
    if (hasRun) search();
  };

  const toggle = $('partialToggle');
  const flip = () => setToggle(!state.partial);
  toggle.onclick = flip;
  toggle.onkeydown = (event) => {
    if (event.key === ' ' || event.key === 'Enter') { event.preventDefault(); flip(); }
  };

  $('columnsBtn').onclick = (event) => {
    event.stopPropagation();
    $('picker').classList.toggle('hidden');
  };
  $('picker').onclick = (event) => event.stopPropagation();
  document.addEventListener('click', () => $('picker').classList.add('hidden'));

  $('pickerSearch').oninput = (event) => filterPickerRows(event.target.value);
  $('pickerAll').onclick = () => {
    state.visible = new Set(state.allColumns);
    syncPicker(); onVisibilityChange();
  };
  $('pickerNone').onclick = () => {
    state.visible = new Set([state.pinned]);
    syncPicker(); onVisibilityChange();
  };
  $('pickerDefault').onclick = () => {
    state.visible = new Set(state.defaultColumns);
    syncPicker(); onVisibilityChange();
  };

  $('prevBtn').onclick = () => { if (state.page > 1) { state.page -= 1; search(); } };
  $('nextBtn').onclick = () => { state.page += 1; search(); };
  $('exportBtn').onclick = exportCsv;
  $('noticeDismiss').onclick = () => $('notice').classList.add('hidden');
}

function setToggle(on) {
  state.partial = on;
  const toggle = $('partialToggle');
  toggle.classList.toggle('on', on);
  toggle.setAttribute('aria-checked', String(on));
}

// --- Query --------------------------------------------------------------

function filterParams() {
  const params = new URLSearchParams();
  Object.entries(state.values).forEach(([param, value]) => {
    if ((value || '').trim()) params.set(param, value.trim());
  });
  params.set('partial', String(state.partial));
  return params;
}

let lastPayload = null;

async function search() {
  if (state.busy) return;
  state.busy = true;
  $('searchBtn').disabled = true;
  setConn('working', 'querying…');

  const started = performance.now();
  const ticker = setInterval(() => {
    $('queryTime').textContent =
      `${((performance.now() - started) / 1000).toFixed(1)}s elapsed…`;
  }, 100);

  const params = filterParams();
  params.set('limit', state.limit);
  params.set('page', String(state.page));
  params.set('page_size', String(state.pageSize));
  // Ask only for what is visible so a 60-column payload shrinks when hidden.
  params.set('columns', [...state.visible].join(','));

  try {
    const payload = await fetch(`/api/rows?${params}`).then(readJson);
    lastPayload = payload;
    hasRun = true;
    state.page = payload.page;
    state.fetched = new Set(payload.fetched_columns || payload.columns);
    markStale(false);
    render(payload);
    // A new search or a new page starts at the top-left, otherwise the first
    // rows sit hidden above the scroll position and the table looks truncated.
    $('tableWrap').scrollTop = 0;
    $('tableWrap').scrollLeft = 0;
    setConn('ready', 'connected');
    $('queryTime').textContent =
      `query ${payload.elapsed.toFixed(1)}s${payload.cached ? ' (cached)' : ''}`;
  } catch (err) {
    setConn('error', 'query failed');
    $('queryTime').textContent = 'failed';
    fail(err.message);
  } finally {
    clearInterval(ticker);
    state.busy = false;
    $('searchBtn').disabled = false;
  }
}

/* Called whenever the visible column set changes.

   Hiding a column, or revealing one the server already holds, is a subset of
   `fetched` and refreshes instantly from the cache. Ticking a column outside
   that set means a real query -- up to ~60 s each for the two nvarchar(max)
   detection columns -- so it is never triggered silently: the button is flagged
   and the user decides. */
function onVisibilityChange() {
  if (!hasRun) return; // nothing fetched yet; Search will pick it up
  const added = [...state.visible].filter((column) => !state.fetched.has(column));
  if (added.length === 0) search();
  else markStale(added);
}

function markStale(added) {
  const stale = Array.isArray(added) && added.length > 0;
  $('searchBtn').classList.toggle('stale', stale);
  if (!stale) { $('staleNote').textContent = ''; return; }
  const seconds = added.reduce((sum, c) => sum + (state.costs[c] || 0), 0);
  const plural = added.length > 1 ? 's' : '';
  $('staleNote').textContent = seconds >= 1
    ? `+${added.length} column${plural}, ~${Math.round(seconds)}s — press Search`
    : `+${added.length} column${plural} — press Search`;
}

function render(payload) {
  const shown = state.allColumns.filter((c) => state.visible.has(c));
  const index = new Map(payload.columns.map((name, i) => [name, i]));

  $('theadRow').innerHTML = shown
    .map((name) => `<th class="${name === state.pinned ? 'pinned' : ''}">${escapeHtml(name)}</th>`)
    .join('');

  // One innerHTML write: 60 columns x up to 1,000 rows is 60k cells, and
  // per-node DOM calls at that count are visibly slower.
  const html = payload.rows.map((row) => {
    const cells = shown.map((name) => {
      const at = index.get(name);
      const value = at === undefined ? null : row[at];
      const classes = [];
      if (name === state.pinned) classes.push('pinned');
      if (value === null || value === '') classes.push('null');
      const text = value === null || value === '' ? '—' : escapeHtml(value);
      const title = value === null || value === '' ? '' : ` title="${escapeHtml(value)}"`;
      return `<td class="${classes.join(' ')}"${title}>${text}</td>`;
    }).join('');
    return `<tr>${cells}</tr>`;
  }).join('');

  $('tbody').innerHTML = html;

  const holder = $('placeholder');
  holder.classList.remove('error');
  if (payload.rows.length === 0) {
    $('tableWrap').classList.add('hidden');
    holder.classList.remove('hidden');
    $('placeholderText').textContent = 'No rows match these filters.';
    $('placeholderHint').textContent =
      'Try switching partial match on, or clearing a filter.';
  } else {
    holder.classList.add('hidden');
    $('tableWrap').classList.remove('hidden');
  }

  const capNote = payload.capped
    ? ` (capped at ${fmt(Number(state.limit))})`
    : '';
  $('matchedText').textContent = `${fmt(payload.total)} rows matched${capNote}`;
  $('pageText').textContent = `page ${fmt(payload.page)} / ${fmt(payload.pages)}`;
  $('prevBtn').disabled = payload.page <= 1;
  $('nextBtn').disabled = payload.page >= payload.pages;
}

// --- Export -------------------------------------------------------------

function exportCsv() {
  const total = lastPayload ? lastPayload.total : null;
  if (!hasAnyFilter()) {
    const size = total ? fmt(total) : 'every';
    if (!confirm(
      `No filter is set, so this exports ${size} rows over ` +
      `${state.visible.size} columns. It will take several minutes. Continue?`
    )) return;
  }
  const params = filterParams();
  params.set('columns', [...state.visible].join(','));
  window.location.href = `/api/export.csv?${params}`;
}

// Deferred to DOMContentLoaded so this file does not depend on being the last
// script parsed: boot() calls into filters.js, which loads after it.
document.addEventListener('DOMContentLoaded', boot);
