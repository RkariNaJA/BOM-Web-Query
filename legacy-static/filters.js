/* BOM Query Web -- filter bar and column picker.
   Loaded before app.js; both share the globals declared there (state, $,
   escapeHtml, fmt, readJson, search, onVisibilityChange). */

// --- Combobox -----------------------------------------------------------

function makeCombo(host, placeholder, onChange, spec) {
  host.innerHTML =
    `<div class="combo-field">
       <svg class="icon muted"><use href="#i-search"/></svg>
       <input autocomplete="off" placeholder="${placeholder}">
       <svg class="icon muted"><use href="#i-chevron-down"/></svg>
     </div>
     <div class="combo-list hidden"></div>`;

  const input = host.querySelector('input');
  const list = host.querySelector('.combo-list');
  const combo = {
    values: [],
    loading: false,
    requested: false,
    setValues(values) { this.values = values; this.loading = false; },
    clear() { input.value = ''; },
  };

  // Fetched on first focus, not at boot: each DISTINCT is a several-second
  // query against a slow view, and most searches touch only one or two fields.
  async function ensureValues() {
    if (combo.requested || !spec.suggest) return;
    combo.requested = true;
    combo.loading = true;
    render();
    try {
      const data = await fetch(
        `/api/distinct?column=${encodeURIComponent(spec.column)}`
      ).then(readJson);
      combo.setValues(data.values);
    } catch (_) {
      combo.setValues([]); // not fatal: the field still takes free text
    }
    render();
  }

  function render() {
    const needle = input.value.trim().toUpperCase();
    if (combo.loading) {
      list.innerHTML = '<div class="combo-note">loading values…</div>';
      return;
    }
    const matches = combo.values.filter((v) => v.toUpperCase().includes(needle));
    // 2,405 options would be pointless to paint; the search narrows it.
    const shown = matches.slice(0, 200);
    list.innerHTML = shown.length
      ? shown.map((v) => `<div data-v="${escapeHtml(v)}">${escapeHtml(v)}</div>`).join('') +
        (matches.length > shown.length
          ? `<div class="combo-note">${fmt(matches.length - shown.length)} more — keep typing</div>`
          : '')
      : '<div class="combo-note">no match — free text is still accepted</div>';
    list.querySelectorAll('[data-v]').forEach((row) => {
      row.onclick = () => {
        input.value = row.dataset.v;
        list.classList.add('hidden');
        onChange(input.value);
      };
    });
  }

  input.onfocus = () => { ensureValues(); render(); list.classList.remove('hidden'); };
  input.oninput = () => { render(); list.classList.remove('hidden'); onChange(input.value); };
  input.onkeydown = (event) => {
    if (event.key === 'Enter') { list.classList.add('hidden'); search(); }
    if (event.key === 'Escape') list.classList.add('hidden');
  };
  document.addEventListener('click', (event) => {
    if (!host.contains(event.target)) list.classList.add('hidden');
  });

  return combo;
}

// --- Filter fields (built from the /api/meta spec) -----------------------

const combos = new Map();

// Hint text only -- purely cosmetic, falls back for any column not listed.
const PLACEHOLDERS = {
  STYLE_NBR: 'e.g. AB1234',
  STYLE_SEASON: 'e.g. AB1234SU27',
  ITEM_NBR: 'e.g. 9000001',
  IM: 'e.g. FPLNI9000001',
};

function buildFilterFields() {
  const host = $('filterFields');
  host.innerHTML = '';
  combos.clear();
  state.values = {};

  state.filterSpec.forEach((spec) => {
    const field = document.createElement('label');
    field.className = 'field';

    const label = document.createElement('span');
    label.className = 'micro-label';
    label.textContent = spec.column;
    field.appendChild(label);

    let note = spec.note || '';
    if (spec.kind === 'date') {
      field.appendChild(buildDateRange(spec));
      if (!note && spec.bounds) {
        note = `data spans ${spec.bounds.min} → ${spec.bounds.max}`;
      }
    } else {
      const mount = document.createElement('div');
      mount.className = 'combo';
      field.appendChild(mount);
      state.values[spec.param] = '';
      combos.set(
        spec.param,
        makeCombo(
          mount,
          PLACEHOLDERS[spec.column] || `any ${spec.column}`,
          (value) => { state.values[spec.param] = value; },
          spec
        )
      );
    }

    if (note) {
      const hint = document.createElement('span');
      hint.className = 'mono field-note';
      hint.textContent = note;
      field.appendChild(hint);
    }
    host.appendChild(field);
  });
}

function buildDateRange(spec) {
  const wrap = document.createElement('div');
  wrap.className = 'date-range';
  const bounds = spec.bounds || {};

  [spec.param_from, spec.param_to].forEach((param, index) => {
    if (index === 1) {
      const arrow = document.createElement('span');
      arrow.className = 'mono muted';
      arrow.textContent = '→';
      wrap.appendChild(arrow);
    }
    state.values[param] = '';
    const cell = document.createElement('div');
    cell.className = 'combo-field';
    const input = document.createElement('input');
    input.type = 'date';
    input.setAttribute('aria-label', `${spec.column} ${index ? 'to' : 'from'}`);
    if (bounds.min) input.min = bounds.min;
    if (bounds.max) input.max = bounds.max;
    input.oninput = () => { state.values[param] = input.value; };
    input.onkeydown = (event) => { if (event.key === 'Enter') search(); };
    cell.appendChild(input);
    wrap.appendChild(cell);
  });
  return wrap;
}

function hasAnyFilter() {
  return Object.values(state.values).some((v) => (v || '').trim());
}

// --- Column picker ------------------------------------------------------

function buildPicker() {
  const body = $('pickerBody');
  body.innerHTML = state.groups.map((group) => `
    <div class="picker-group" data-group="${escapeHtml(group.title)}">
      <div class="picker-group-head"><span class="micro-label">${escapeHtml(group.title)}</span></div>
      <div class="picker-grid">
        ${group.columns.map((name) => pickerItem(name)).join('')}
      </div>
    </div>`).join('');

  body.querySelectorAll('.picker-item:not(.locked)').forEach((item) => {
    item.onclick = () => {
      const name = item.dataset.col;
      if (state.visible.has(name)) state.visible.delete(name);
      else state.visible.add(name);
      syncPicker();
      onVisibilityChange();
    };
  });
  syncPicker();
}

function pickerItem(name) {
  const locked = name === state.pinned;
  const cost = state.costs[name];
  // Measured cost shown inline so nobody ticks a 60 s column blind.
  const badge = cost
    ? `<span class="cost${cost >= 30 ? ' heavy' : ''}">+${Math.round(cost)}s</span>`
    : '';
  return `<div class="picker-item${locked ? ' locked' : ''}" data-col="${escapeHtml(name)}">
      <span class="checkbox checked"><svg class="icon" style="width:9px;height:9px"><use href="#i-tick"/></svg></span>
      <span class="picker-name">${escapeHtml(name)}</span>
      ${locked ? '<span class="pin">pinned</span>' : ''}
      ${badge}
    </div>`;
}

function syncPicker() {
  document.querySelectorAll('.picker-item').forEach((item) => {
    const on = state.visible.has(item.dataset.col);
    item.querySelector('.checkbox').classList.toggle('checked', on);
  });
  $('columnsCount').textContent =
    `${state.visible.size} / ${state.allColumns.length} shown`;
}

function filterPickerRows(needle) {
  const lower = needle.trim().toLowerCase();
  document.querySelectorAll('.picker-group').forEach((group) => {
    let visibleCount = 0;
    group.querySelectorAll('.picker-item').forEach((item) => {
      const match = item.dataset.col.toLowerCase().includes(lower);
      item.classList.toggle('hidden', !match);
      if (match) visibleCount += 1;
    });
    group.classList.toggle('hidden', visibleCount === 0);
  });
}
