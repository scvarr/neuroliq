/* Отдельный экран ревью; вычисления и решения выполняются сервером. */
const $ = id => document.getElementById(id);
const statuses = {pending: 'Ожидает решения', accepted: 'Принята', rejected: 'Отклонена'};
let workspace, family, busy = false;
const escapeHtml = s => String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const api = async (path, options) => {
  const response = await fetch('/api/lexical' + path, options);
  if (!response.ok) {
    let detail; try { detail = (await response.json()).detail; } catch { detail = response.statusText; }
    throw new Error(typeof detail === 'string' ? detail : 'Проверьте поля запроса: ' + JSON.stringify(detail));
  }
  return response.json();
};
const message = (text = '', error = false) => { $('message').textContent = text; $('message').classList.toggle('error', error); };
async function task(work, progress = '') {
  if (busy) return;
  busy = true;
  const controls = [...document.querySelectorAll('button,input,select,textarea')];
  const disabled = controls.map(c => c.disabled);
  controls.forEach(c => c.disabled = true);
  message(progress);
  try { await work(); message(); } catch (e) { message(e.message, true); }
  finally { controls.forEach((c, i) => c.disabled = disabled[i]); busy = false; syncControls(); }
}
function syncControls() {
  if (!family) return;
  ['accept','reject','split'].forEach(id => $(id).disabled = family.status !== 'pending');
  $('more').disabled = family.examples.length >= family.total;
  document.querySelectorAll('.pick').forEach(c => c.disabled = family.status !== 'pending');
}
async function savedBatches() {
  const batches = await api('');
  $('saved').replaceChildren();
  for (const batch of batches) {
    const b = document.createElement('button');
    b.textContent = `${batch.title} · ${batch.diagnostics.processed_tokens.toLocaleString('ru')} вхождений`;
    b.onclick = () => task(() => openWorkspace(batch.id));
    $('saved').append(b);
  }
  if (!batches.length) $('saved').textContent = 'Пока нет сохранённых батчей.';
}
function filteredFamilies() {
  const query = $('search').value.toLocaleLowerCase('ru');
  return workspace.families.filter(f => ($('statusFilter').value === 'all' || f.status === $('statusFilter').value) && f.forms.some(k => k.includes(query)));
}
function renderQueue(preferred) {
  const list = filteredFamilies();
  $('familySelect').replaceChildren();
  for (const f of list) {
    const option = document.createElement('option'); option.value = f.id;
    option.textContent = `${f.forms.slice(0, 3).join(' / ')} · ${f.total}`;
    option.title = f.forms.join(', ');
    $('familySelect').append(option);
  }
  $('queueStats').textContent = `${list.length} семей в выборке`;
  const selected = list.find(f => f.id === preferred) || list[0];
  $('empty').hidden = !!selected; $('review').hidden = !selected;
  if (selected) { $('familySelect').value = selected.id; return selected.id; }
  family = null;
}
async function openWorkspace(id, preferred) {
  workspace = await api('/' + id);
  localStorage.setItem('lexical-workspace', id);
  $('setup').hidden = true; $('workspace').hidden = false;
  $('batchTitle').textContent = workspace.title;
  const d = workspace.diagnostics;
  $('stats').textContent = `${d.processed_tokens.toLocaleString('ru')} / ${workspace.requested_limit.toLocaleString('ru')} вхождений · ${workspace.families.length} семей · ${d.ungrouped_occurrences.toLocaleString('ru')} вне групп · ${workspace.mapping_count.toLocaleString('ru')} принятых сопоставлений`;
  $('rule').textContent = workspace.generator + ': ' + workspace.rule;
  $('export').href = '/api/lexical/' + id + '/export';
  const selected = renderQueue(preferred);
  if (selected) await openFamily(selected);
}
async function openFamily(id, preserve = false) {
  family = await api(`/${workspace.id}/families/${id}`);
  localStorage.setItem('lexical-family', id);
  $('familyTitle').textContent = family.forms.join(' / ');
  $('familyKind').textContent = family.kind === 'prefix' ? `Строковая гипотеза · префикс «${family.prefix}»` : family.kind === 'exact' ? 'Гипотеза повторной формы' : 'Семья после ручного разделения';
  $('familyStats').textContent = `${family.forms.length} форм · ${family.total} вхождений · ID ${family.id}`;
  $('familyStatus').textContent = statuses[family.status];
  $('lineage').textContent = family.parent ? 'Выделена из семьи ' + family.parent : '';
  if (!preserve) $('note').value = '';
  $('forms').innerHTML = family.forms.map(k => `<div><label><input class="pick form-pick" type="checkbox" value="${escapeHtml(k)}">${escapeHtml(k)} <small>×${family.form_counts[k]}</small></label>${family.concept_ids[k] ? `<a href="/l0?concept=${encodeURIComponent(family.concept_ids[k])}">ConceptId / L0 ↗</a>` : ''}</div>`).join('');
  $('examples').replaceChildren();
  for (const o of family.examples) {
    const el = document.createElement('div'); el.className = 'example';
    el.innerHTML = `<div class="example-top"><input class="pick occurrence-pick" type="checkbox" value="${o.id}" aria-label="Перенести пример ${o.id}"><span>${escapeHtml(o.reason)} · #${o.id} · документ ${o.source_id}, токен ${o.ordinal}</span><button>Открыть источник</button></div><p>${escapeHtml(o.before)}<mark>${escapeHtml(o.surface)}</mark>${escapeHtml(o.after)}</p>`;
    el.querySelector('button').onclick = () => task(async () => {
      const source = await api(`/${workspace.id}/sources/${o.source_id}`);
      $('sourceRef').textContent = source.reference;
      $('sourceMeta').textContent = `SHA-256 исходного UTF-8: ${source.sha256} · NFC · позиция ${o.start}–${o.end} · обработано токенов: ${source.processed_tokens}`;
      $('sourceText').innerHTML = `${escapeHtml(source.text.slice(0, o.start))}<mark id="sourceHighlight">${escapeHtml(source.text.slice(o.start, o.end))}</mark>${escapeHtml(source.text.slice(o.end))}`;
      $('sourceDialog').showModal();
      $('sourceHighlight').scrollIntoView({block:'center'});
    });
    $('examples').append(el);
  }
  $('exampleStats').textContent = `Показано ${family.examples.length} из ${family.total}`;
  $('decisionHelp').textContent = family.status === 'pending' ? 'Решение применяется ко всем вхождениям семьи, включая ещё не показанные. Семантическая метка не назначается.' : `Решение сохранено. ${family.mapping_id ? 'ID сопоставления: ' + family.mapping_id : 'Сопоставление не создано.'} Источники доступны для аудита.`;
  $('events').innerHTML = family.events.length ? family.events.map(e => `<p>${escapeHtml(e.at)} · ${escapeHtml(e.reviewer)} · ${escapeHtml({accept:'Принятие',reject:'Отклонение',split:'Разделение',more:'Дополнительные примеры'}[e.action])}<br>${escapeHtml(e.note)}<br>Состав до действия: ${e.members_before.length}; раскрыто примеров: ${e.inspected.length}${e.child_id ? '; новая семья: ' + escapeHtml(e.child_id) + '; перенесено: ' + e.moved.length : ''}</p>`).join('') : '<p>Создана прозрачным генератором батча. Решений пока нет. Полный состав, параметры и источники доступны в экспорте.</p>';
  syncControls();
}
async function decide(action) {
  const selected = [...document.querySelectorAll('.occurrence-pick:checked')].map(c => Number(c.value));
  const forms = [...document.querySelectorAll('.form-pick:checked')].map(c => c.value);
  if (!$('reviewer').value.trim()) throw new Error('Укажите проверяющего.');
  if (action === 'split' && !selected.length && !forms.length) throw new Error('Отметьте формы или примеры, которые нужно перенести.');
  const id = family.id;
  const checkedForms = forms, checkedExamples = selected;
  await api(`/${workspace.id}/families/${id}`, {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({revision:workspace.revision,action,reviewer:$('reviewer').value,note:$('note').value,selected,forms})});
  localStorage.setItem('lexical-reviewer', $('reviewer').value);
  if (action === 'more') {
    workspace.revision += 1;
    await openFamily(id, true);
    document.querySelectorAll('.form-pick').forEach(c => c.checked = checkedForms.includes(c.value));
    document.querySelectorAll('.occurrence-pick').forEach(c => c.checked = checkedExamples.includes(Number(c.value)));
  } else { await openWorkspace(workspace.id, action === 'split' || $('statusFilter').value === 'all' ? id : undefined); }
}
$('batchForm').onsubmit = e => { e.preventDefault(); task(async () => {
  const documents = [];
  if ($('source').value === 'local') {
    for (const file of [...$('files').files].sort((a,b) => a.name < b.name ? -1 : a.name > b.name ? 1 : 0)) {
      documents.push({reference:file.name,text:new TextDecoder('utf-8',{fatal:true}).decode(await file.arrayBuffer())});
    }
  }
  const result = await api('', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({title:$('title').value,source:$('source').value,limit:Number($('limit').value),documents})});
  $('statusFilter').value = 'pending'; $('search').value = '';
  await openWorkspace(result.id);
}, 'Обрабатывается батч. Скачивание корпуса и группировка могут занять время…'); };
$('source').onchange = () => { const local = $('source').value === 'local'; $('filesLabel').hidden = !local; $('datasetInfo').hidden = local; };
$('newBatch').onclick = () => task(async () => { $('setup').hidden = false; $('workspace').hidden = true; await savedBatches(); });
$('statusFilter').onchange = () => task(async () => { const id = renderQueue(family?.id); if (id) await openFamily(id); });
let searchTimer;
$('search').oninput = () => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => task(async () => { const id = renderQueue(family?.id); if (id) await openFamily(id); }), 180);
};
$('familySelect').onchange = () => task(() => openFamily($('familySelect').value));
for (const action of ['accept','reject','split']) $(action).onclick = () => task(() => decide(action));
$('more').onclick = () => task(() => decide('more'));
$('closeSource').onclick = () => $('sourceDialog').close();
$('reviewer').value = localStorage.getItem('lexical-reviewer') || 'Локальный исследователь';
task(async () => {
  await savedBatches();
  const id = localStorage.getItem('lexical-workspace');
  if (id) {
    const batches = await api('');
    if (batches.some(b => b.id === id)) {
      // Восстановление выбранной принятой семьи также должно открыть её для аудита.
      $('statusFilter').value = 'all';
      await openWorkspace(id, localStorage.getItem('lexical-family'));
    }
  }
});
