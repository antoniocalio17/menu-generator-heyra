// State
let currentYear = new Date().getFullYear();
let currentWeek = getISOWeek(new Date());
let menuData = null;
let catalogue = [];

let modalContext = { track: null, day: null, onSuggest: null };

// Init
document.addEventListener('DOMContentLoaded', async () => {
  await loadCatalogue();
  populateModalSelect();
  await loadWeek(currentWeek, currentYear);
});

// ISO week helpers

function getISOWeek(date) {
  const d = new Date(Date.UTC(date.getFullYear(), date.getMonth(), date.getDate()));
  d.setUTCDate(d.getUTCDate() + 4 - (d.getUTCDay() || 7));
  const yearStart = new Date(Date.UTC(d.getUTCFullYear(), 0, 1));
  return Math.ceil((((d - yearStart) / 86400000) + 1) / 7);
}

function getWeeksInYear(year) {
  // Dec 28 is always in the last ISO week of the year
  return getISOWeek(new Date(year, 11, 28));
}

function isoWeekMonday(year, week) {
  // Jan 4 is always in ISO week 1
  const jan4 = new Date(Date.UTC(year, 0, 4));
  const dayOfWeek = jan4.getUTCDay() || 7; // 1=Mon … 7=Sun
  return new Date(Date.UTC(year, 0, 4 - (dayOfWeek - 1) + (week - 1) * 7));
}

function formatDateRange(year, week) {
  const mon = isoWeekMonday(year, week);
  const fri = new Date(mon);
  fri.setUTCDate(mon.getUTCDate() + 4);
  const fmt = d => d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', timeZone: 'UTC' });
  return `${fmt(mon)} – ${fmt(fri)}`;
}

// API helpers

async function loadCatalogue() {
  const res = await fetch('/api/catalogue');
  const data = await res.json();
  catalogue = data.products;
}

async function loadWeek(week, year) {
  updateHeader(week, year);
  clearGlobalError();
  clearGlobalWarning();

  const res = await fetch(`/api/menu/${year}/${week}`);

  if (res.status === 404) {
    menuData = null;
    renderEmpty();
    return;
  }
  if (!res.ok) {
    showGlobalError('Failed to load menu. Please try again.');
    return;
  }

  menuData = await res.json();
  renderCalendar(menuData);
}

async function generateWeek() {
  const btn = document.getElementById('generate-btn');
  btn.disabled = true;
  btn.textContent = 'Generating...';
  clearGlobalError();
  clearGlobalWarning();

  const res = await fetch(`/api/generate/${currentYear}/${currentWeek}`, { method: 'POST' });

  btn.disabled = false;
  btn.textContent = `Generate Week ${currentWeek}`;

  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    const msgs = err.detail?.errors || [JSON.stringify(err.detail || err)];
    showGlobalError(msgs.join('\n'));
    return;
  }

  menuData = await res.json();
  if (menuData.fallback) {
    showGlobalWarning('LLM unavailable — menu built from past weeks. You can edit dishes manually or try generating again later.');
  }
  renderCalendar(menuData);
}

async function saveDish(track, day) {
  const card = document.getElementById(`card-${track}-${day}`);
  const nameInput = card.querySelector('.dish-name-input');
  const descInput = card.querySelector('.dish-description-input');
  const ingRows = card.querySelectorAll('.ing-row');
  const errDiv = card.querySelector('.edit-errors');

  errDiv.textContent = '';

  const ingredients = Array.from(ingRows).map(row => ({
    product_id: parseInt(row.dataset.productId, 10),
    quantity_g: parseFloat(row.querySelector('.ing-qty').value) || 1,
  }));

  const res = await fetch(`/api/menu/${currentYear}/${currentWeek}/${track}/${day}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      dish_name: nameInput.value.trim(),
      description: descInput ? descInput.value : '',
      ingredients,
    }),
  });

  if (res.status === 422) {
    const err = await res.json();
    errDiv.textContent = (err.detail?.errors || ['Validation error']).join('\n');
    return;
  }
  if (!res.ok) {
    errDiv.textContent = 'Error saving. Please try again.';
    return;
  }

  menuData = await res.json();
  renderCalendar(menuData);
}

// Navigation

function changeWeek(delta) {
  currentWeek += delta;
  if (currentWeek < 1) {
    currentYear--;
    currentWeek = getWeeksInYear(currentYear);
  } else if (currentWeek > getWeeksInYear(currentYear)) {
    currentYear++;
    currentWeek = 1;
  }
  loadWeek(currentWeek, currentYear);
}

// Header helpers

function updateHeader(week, year) {
  const range = formatDateRange(year, week);
  document.getElementById('week-label').textContent = `Week ${week}, ${year} · ${range}`;
  document.getElementById('generate-btn').textContent = `Generate Week ${week}`;
}

function clearGlobalError() {
  document.getElementById('global-error').textContent = '';
}

function showGlobalError(msg) {
  document.getElementById('global-error').textContent = msg;
}

function clearGlobalWarning() {
  document.getElementById('global-warning').textContent = '';
}

function showGlobalWarning(msg) {
  document.getElementById('global-warning').textContent = msg;
}

// Rendering

const DAYS = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday'];
const DAY_LABELS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday'];

function renderEmpty() {
  document.getElementById('calendar').innerHTML =
    '<div class="empty-state">No menu generated yet for this week. Click "Generate" to create one.</div>';
}

function renderCalendar(data) {
  const cal = document.getElementById('calendar');
  cal.innerHTML = '';

  cal.appendChild(el('div', 'header-spacer'));
  DAYS.forEach((day, i) => {
    const mon = isoWeekMonday(currentYear, currentWeek);
    const d = new Date(mon);
    d.setUTCDate(mon.getUTCDate() + i);
    const label = d.toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric', timeZone: 'UTC' });
    cal.appendChild(el('div', 'day-header', label));
  });

  renderTrackRow(cal, data, 'meat', 'Meat');
  renderTrackRow(cal, data, 'vegetarian', 'Vegetarian');
}

function renderTrackRow(container, data, track, label) {
  const trackData = data[track];

  const labelCell = el('div', `track-label track-${track}`);
  labelCell.appendChild(el('strong', '', label));
  labelCell.appendChild(el('small', '', `${trackData.weekly_cost_eur.toFixed(2)} EUR / wk`));
  labelCell.appendChild(el('small', '', `${Math.round(trackData.weekly_calories_kcal)} kcal / wk`));
  if (trackData.allergens.length) {
    labelCell.appendChild(el('span', 'track-allergen-tag', trackData.allergens.join(', ')));
  }
  container.appendChild(labelCell);

  DAYS.forEach(day => {
    const dish = trackData.dishes[day];
    container.appendChild(buildDishCard(track, day, dish));
  });
}

// Dish card

function buildDishCard(track, day, dish) {
  const card = el('div', `dish-card dish-${track}`);
  card.id = `card-${track}-${day}`;

  // View mode
  const view = el('div', 'dish-view');

  view.appendChild(el('div', 'dish-name', dish.dish_name));
  view.appendChild(el('div', 'dish-meta',
    `${dish.total_cost_eur.toFixed(2)} EUR  ·  ${Math.round(dish.total_calories_kcal)} kcal`));

  if (dish.allergens.length) {
    const tags = el('div', 'dish-tags');
    dish.allergens.forEach(a => tags.appendChild(el('span', 'allergen-pill', a)));
    view.appendChild(tags);
  }

  const viewActions = el('div', 'dish-view-actions');

  const infoBtn = el('button', 'info-btn', 'Recipe');
  infoBtn.onclick = () => openDetails(dish);

  const editBtn = el('button', 'edit-btn', 'Edit');
  editBtn.onclick = () => switchToEdit(view, editPane);

  viewActions.appendChild(infoBtn);
  viewActions.appendChild(editBtn);
  view.appendChild(viewActions);

  // Edit mode
  const editPane = el('div', 'dish-edit hidden');

  const nameInput = document.createElement('input');
  nameInput.type = 'text';
  nameInput.className = 'dish-name-input';
  nameInput.value = dish.dish_name;
  editPane.appendChild(nameInput);

  const descInput = document.createElement('input');
  descInput.type = 'hidden';
  descInput.className = 'dish-description-input';
  descInput.value = dish.description || '';
  editPane.appendChild(descInput);

  // Shared suggestion panel (updated whenever an "AI hint" button is clicked)
  const suggestPanel = el('div', 'suggestions-panel hidden');

  const ingEditor = el('div', 'ingredient-editor');
  const onSuggest = (pid, name) =>
    loadSuggestions(track, ingEditor, suggestPanel, nameInput, descInput, pid, name);
  dish.ingredients.forEach(ing => {
    ingEditor.appendChild(buildIngRow(ing.product_id, ing.name, ing.quantity_g, onSuggest));
  });
  editPane.appendChild(ingEditor);

  editPane.appendChild(suggestPanel);

  const addBtn = el('button', 'add-ing-btn', '+ Add ingredient');
  addBtn.onclick = () => openModal(track, day, ingEditor, onSuggest, nameInput, descInput);
  editPane.appendChild(addBtn);

  editPane.appendChild(el('div', 'edit-errors'));

  const editActions = el('div', 'edit-actions');

  const saveBtn = el('button', 'save-btn', 'Save');
  saveBtn.onclick = () => saveDish(track, day);

  const cancelBtn = el('button', 'cancel-btn', 'Cancel');
  cancelBtn.onclick = () => {
    const fresh = buildDishCard(track, day, menuData[track].dishes[day]);
    card.replaceWith(fresh);
  };

  editActions.appendChild(saveBtn);
  editActions.appendChild(cancelBtn);
  editPane.appendChild(editActions);

  card.appendChild(view);
  card.appendChild(editPane);

  return card;
}

function switchToEdit(view, editPane) {
  view.classList.add('hidden');
  editPane.classList.remove('hidden');
}

function buildIngRow(productId, name, quantityG, onSuggest) {
  const row = el('div', 'ing-row');
  row.dataset.productId = productId;

  const suggestBtn = el('button', 'row-suggest-btn', 'AI hint');
  suggestBtn.title = 'Get AI substitution suggestions for this ingredient';
  suggestBtn.onclick = () => onSuggest && onSuggest(productId, name);

  const nameSpan = el('span', 'ing-name', name);

  const qtyInput = document.createElement('input');
  qtyInput.type = 'number';
  qtyInput.className = 'ing-qty';
  qtyInput.value = Math.round(quantityG);
  qtyInput.min = '1';

  const gLabel = el('span', '', 'g');

  const removeBtn = el('button', 'remove-btn', '×');
  removeBtn.onclick = () => row.remove();

  row.appendChild(suggestBtn);
  row.appendChild(nameSpan);
  row.appendChild(qtyInput);
  row.appendChild(gLabel);
  row.appendChild(removeBtn);

  return row;
}

// AI suggestions

async function loadSuggestions(track, ingEditor, panel, nameInput, descInput, targetProductId, targetName) {
  panel.innerHTML = '';
  panel.classList.remove('hidden');
  panel.appendChild(el('div', 'suggestions-loading', `Finding substitutes for "${targetName}"…`));

  const ingRows = ingEditor.querySelectorAll('.ing-row');
  const ingredients = Array.from(ingRows).map(row => ({
    product_id: parseInt(row.dataset.productId, 10),
    quantity_g: parseFloat(row.querySelector('.ing-qty').value) || 1,
  }));

  const res = await fetch('/api/suggest', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ track, target_product_id: targetProductId, ingredients }),
  });

  panel.innerHTML = '';

  if (!res.ok) {
    panel.appendChild(el('div', 'suggestions-error', 'Could not load suggestions. Try again.'));
    return;
  }

  const data = await res.json();

  const header = el('div', 'suggestions-header');
  header.appendChild(el('span', '', `Substitutes for "${targetName}"`));
  const closeBtn = el('button', 'suggestions-close', '×');
  closeBtn.onclick = () => panel.classList.add('hidden');
  header.appendChild(closeBtn);
  panel.appendChild(header);

  if (!data.candidates || !data.candidates.length) {
    panel.appendChild(el('div', 'suggestions-empty', 'No substitutes found in the catalogue.'));
    return;
  }

  data.candidates.forEach(c => {
    const cand = el('div', 'suggestion-candidate');

    const info = el('div', 'suggestion-cand-info');
    info.appendChild(el('div', 'suggestion-cand-name', c.product_name));
    info.appendChild(el('span', 'suggestion-cand-group', c.ingredient_group));
    info.appendChild(el('div', 'suggestion-cand-reason', c.reason));

    const swapBtn = el('button', 'swap-btn', 'Swap');
    swapBtn.onclick = async () => {
      // Replace the target ingredient row
      const rows = ingEditor.querySelectorAll('.ing-row');
      for (const row of rows) {
        if (parseInt(row.dataset.productId, 10) === targetProductId) {
          const qty = parseFloat(row.querySelector('.ing-qty').value) || 100;
          const onSuggest = (pid, name) =>
            loadSuggestions(track, ingEditor, panel, nameInput, descInput, pid, name);
          row.replaceWith(buildIngRow(c.product_id, c.product_name, qty, onSuggest));
          break;
        }
      }
      panel.classList.add('hidden');

      // Re-generate dish name and description to match the updated ingredients
      const updatedRows = ingEditor.querySelectorAll('.ing-row');
      const updatedIngredients = Array.from(updatedRows).map(row => ({
        product_id: parseInt(row.dataset.productId, 10),
        quantity_g: parseFloat(row.querySelector('.ing-qty').value) || 1,
      }));

      nameInput.classList.add('renaming');
      nameInput.disabled = true;

      const renameRes = await fetch('/api/rename-dish', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ track, ingredients: updatedIngredients }),
      });

      nameInput.disabled = false;
      nameInput.classList.remove('renaming');

      if (renameRes.ok) {
        const renamed = await renameRes.json();
        nameInput.value = renamed.dish_name;
        if (descInput) descInput.value = renamed.description;
      }
    };

    cand.appendChild(info);
    cand.appendChild(swapBtn);
    panel.appendChild(cand);
  });
}

// Recipe / details modal

function openDetails(dish) {
  document.getElementById('details-title').textContent = dish.dish_name;

  const descEl = document.getElementById('details-description');
  descEl.textContent = dish.description || '';
  descEl.style.display = dish.description ? 'block' : 'none';

  const tbody = document.getElementById('details-tbody');
  tbody.innerHTML = '';
  dish.ingredients.forEach(ing => {
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td>${ing.name}</td>
      <td class="num">${Math.round(ing.quantity_g)} g</td>
      <td class="allergen-cell">${ing.allergens.length ? ing.allergens.join(', ') : '—'}</td>
    `;
    tbody.appendChild(tr);
  });

  const allergenSection = dish.allergens.length
    ? `<div class="details-allergens">${dish.allergens.map(a => `<span class="allergen-pill">${a}</span>`).join('')}</div>`
    : '';

  document.getElementById('details-footer').innerHTML =
    allergenSection +
    `<div class="details-costs">` +
    `<span>Total cost</span><strong>${dish.total_cost_eur.toFixed(2)} EUR</strong>` +
    `<span class="footer-sep">·</span>` +
    `<span>Calories</span><strong>${Math.round(dish.total_calories_kcal)} kcal</strong>` +
    `</div>`;

  document.getElementById('details-overlay').classList.remove('hidden');
}

function closeDetails() {
  document.getElementById('details-overlay').classList.add('hidden');
}

// Add ingredient modal

let activeIngEditor = null;

function populateModalSelect() {
  const select = document.getElementById('modal-select');
  select.innerHTML = '';
  catalogue.forEach(p => {
    const opt = document.createElement('option');
    opt.value = p.product_id;
    opt.textContent = `${p.product_name}  (${p.ingredient_group})`;
    opt.dataset.name = p.product_name;
    select.appendChild(opt);
  });
}

function filterModal() {
  const q = document.getElementById('modal-search').value.toLowerCase();
  const select = document.getElementById('modal-select');
  Array.from(select.options).forEach(opt => {
    opt.hidden = q.length > 0 && !opt.textContent.toLowerCase().includes(q);
  });
}

function openModal(track, day, ingEditor, onSuggest, nameInput, descInput) {
  modalContext = { track, day, onSuggest: onSuggest || null, nameInput: nameInput || null, descInput: descInput || null };
  activeIngEditor = ingEditor;
  document.getElementById('modal-search').value = '';
  filterModal();
  document.getElementById('modal-qty').value = '100';
  document.getElementById('modal-overlay').classList.remove('hidden');
  document.getElementById('modal-search').focus();
}

function closeModal() {
  document.getElementById('modal-overlay').classList.add('hidden');
  activeIngEditor = null;
}

function confirmAdd() {
  if (!activeIngEditor) return;
  const select = document.getElementById('modal-select');
  const selected = select.options[select.selectedIndex];
  if (!selected) return;

  const productId = parseInt(select.value, 10);
  const name = selected.dataset.name;
  const qty = parseFloat(document.getElementById('modal-qty').value) || 100;

  activeIngEditor.appendChild(buildIngRow(productId, name, qty, modalContext.onSuggest));
  closeModal();
}

// DOM helper

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}
