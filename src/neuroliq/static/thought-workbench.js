/* Ручной редактор; annotations используются только для отображения. */
const $ = id => document.getElementById(id);
const base = '/api/thought-workbench';
let state, conceptId = '', sourceId = '', thoughtId = '', elementId = '';
let renderedSourceText = '', renderedSourceContext = '', renderedValue = '';
let queue = Promise.resolve();
const cy = cytoscape({container: $('graph'), elements: [], maxZoom: 1.5, style: [
  {selector: 'node', style: {'label': 'data(label)', 'font-size': 12, 'text-wrap': 'wrap', 'text-max-width': 160, 'background-color': '#356f9e', 'color': '#172c40', 'text-valign': 'bottom', 'text-margin-y': 10}},
  {selector: 'node[kind="literal"]', style: {'shape': 'rectangle', 'background-color': '#bd8138'}},
  {selector: 'edge', style: {'curve-style': 'bezier', 'target-arrow-shape': 'triangle', 'line-color': '#6f8192', 'target-arrow-color': '#6f8192', 'width': 2}},
  {selector: ':selected', style: {'border-width': 3, 'border-color': '#e57a26', 'line-color': '#e57a26', 'target-arrow-color': '#e57a26'}}
]});
function message(text, error = false) { $('message').textContent = text; $('message').style.color = error ? '#a32626' : '#245d42'; }
function action(fn) {
  queue = queue.then(async () => {
    document.querySelectorAll('button').forEach(b => b.disabled = true);
    try { await fn(); message('Сохранено в SQLite.'); }
    catch (e) { message(e.message, true); }
    finally { document.querySelectorAll('button').forEach(b => b.disabled = false); }
  });
}
async function request(path = '', method = 'GET', body) {
  const response = await fetch(base + path, {method, headers: {'Content-Type': 'application/json'}, body: body === undefined ? undefined : JSON.stringify(body)});
  if (!response.ok) { const data = await response.json(); throw new Error(typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail)); }
  return response.json();
}
function options(id, records, selected = '', placeholder = '') {
  const select = $(id); select.replaceChildren();
  if (placeholder) select.add(new Option(placeholder, ''));
  records.forEach(r => select.add(new Option(r.label, r.id)));
  select.value = selected;
}
function thought() { return state.thoughts.find(t => t.id === thoughtId); }
function elementLabel(e) {
  const label = e.kind === 'concept' ? (state.concepts.find(c => c.id === e.concept_id)?.annotation || e.concept_id) : e.value;
  return `${label}${e.annotation ? '\n' + e.annotation : ''}\n[${e.id.slice(0, 8)}]`;
}
function renderCatalog() {
  const query = $('conceptSearch').value.toLocaleLowerCase();
  const concepts = state.concepts.filter(c => (c.annotation + c.id).toLocaleLowerCase().includes(query)).sort((a,b) => a.annotation.localeCompare(b.annotation) || a.id.localeCompare(b.id));
  options('conceptList', concepts.map(c => ({id:c.id,label:c.annotation || c.id})), conceptId);
  options('elementConcept', concepts.map(c => ({id:c.id,label:c.annotation || c.id})), $('elementConcept').value || conceptId, 'Выберите концепт');
  const e = thought()?.elements.find(e => e.id === elementId);
  if (e?.concept_id && !concepts.some(c => c.id === e.concept_id)) {
    const c = state.concepts.find(c => c.id === e.concept_id);
    $('elementConcept').add(new Option(c.annotation || c.id, c.id));
  }
  if (e?.concept_id) $('elementConcept').value = e.concept_id;
}
function renderConcept() {
  $('conceptAnnotation').value = state.concepts.find(c => c.id === conceptId)?.annotation || '';
  $('conceptId').textContent = conceptId || 'Новый концепт получит UUID';
}
function renderSource() {
  const s = state.sources.find(s => s.id === sourceId);
  $('sourceText').value = s?.text || ''; $('sourceContext').value = s?.context || '';
  renderedSourceText = $('sourceText').value; renderedSourceContext = $('sourceContext').value;
  $('sourceId').textContent = sourceId || 'Новый фрагмент получит UUID';
}
function renderElement() {
  const e = thought()?.elements.find(e => e.id === elementId);
  $('elementList').value = elementId;
  $('elementKind').value = e?.kind || 'concept';
  $('elementValue').value = e?.value ?? '';
  renderedValue = $('elementValue').value;
  $('elementAnnotation').value = e?.annotation || '';
  $('elementId').textContent = elementId || 'Новый локальный элемент получит UUID';
  renderCatalog(); if (e?.concept_id) $('elementConcept').value = e.concept_id;
  toggleKind();
}
function toggleKind() { const literal = $('elementKind').value === 'literal'; $('literalLabel').hidden = !literal; $('conceptChoiceLabel').hidden = literal; }
function render() {
  $('counts').textContent = `Концептов: ${state.concepts.length} · фрагментов: ${state.sources.length} · мыслей: ${state.thoughts.length}`;
  renderCatalog(); renderConcept();
  const sources = state.sources.map(s => ({id:s.id,label:s.text.slice(0, 65) || s.id}));
  options('sourceList', sources, sourceId, 'Новый фрагмент'); renderSource();
  options('thoughtList', state.thoughts.map(t => ({id:t.id,label:t.annotation || t.id})), thoughtId, 'Новая мысль');
  const t = thought();
  $('thoughtAnnotation').value = t?.annotation || '';
  options('thoughtSource', sources, t?.source_id || sourceId, 'Выберите источник');
  $('thoughtId').textContent = thoughtId || 'Новая мысль получит UUID';
  const s = state.sources.find(s => s.id === t?.source_id);
  $('thoughtEvidence').textContent = s ? s.text + (s.context ? '\nКонтекст: ' + s.context : '') : '';
  const elements = (t?.elements || []).map(e => ({id:e.id,label:elementLabel(e).replaceAll('\n',' · ')}));
  options('elementList', elements, elementId, 'Новый элемент');
  options('linkSource', elements, $('linkSource').value, 'Выберите начало');
  options('linkTarget', elements, $('linkTarget').value, 'Выберите конец');
  options('linkList', (t?.links || []).map((l,i) => ({id:String(i),label:`${elementLabel(t.elements.find(e=>e.id===l.source)).split('\n')[0]} [${l.source.slice(0,8)}] → ${elementLabel(t.elements.find(e=>e.id===l.target)).split('\n')[0]} [${l.target.slice(0,8)}]`})), '', 'Выберите связь');
  renderElement();
  cy.elements().remove();
  cy.add((t?.elements || []).map(e => ({data:{id:e.id,label:elementLabel(e),kind:e.kind}})));
  cy.add((t?.links || []).map((l,i) => ({data:{id:`link-${i}`,source:l.source,target:l.target}})));
  cy.layout({name:'breadthfirst', directed:true, padding:45, nodeDimensionsIncludeLabels:true, spacingFactor:1.4}).run();
  if (elementId) cy.getElementById(elementId).select();
}
async function save(collection, id, record) { state = await request(`/${collection}${id ? '/' + id : ''}`, id ? 'PUT' : 'POST', record); }
async function remove(collection, id) { if (!id) throw new Error('Выберите сохранённую запись'); state = await request(`/${collection}/${id}`, 'DELETE'); }
async function changeThought(fn) {
  const t = thought(); if (!t) throw new Error('Сначала сохраните мысль');
  const copy = structuredClone(t); fn(copy); await save('thoughts', t.id, copy); render();
}
function submit(id, fn) { $(id).addEventListener('submit', event => { event.preventDefault(); action(fn); }); }
submit('conceptForm', async () => { const id = conceptId || crypto.randomUUID(); await save('concepts', conceptId, {id, annotation:$('conceptAnnotation').value}); conceptId=id; render(); });
$('newConcept').onclick = () => { conceptId=''; $('conceptList').value=''; renderConcept(); };
$('conceptList').onchange = () => { conceptId=$('conceptList').value; renderConcept(); $('elementConcept').value=conceptId; };
$('conceptSearch').oninput = renderCatalog;
$('deleteConcept').onclick = () => action(async () => { await remove('concepts',conceptId); conceptId=''; render(); });
submit('sourceForm', async () => {
  const id=sourceId || crypto.randomUUID(), old=state.sources.find(s=>s.id===sourceId);
  const text=old && $('sourceText').value===renderedSourceText ? old.text : $('sourceText').value;
  const context=old && $('sourceContext').value===renderedSourceContext ? old.context : $('sourceContext').value;
  await save('sources',sourceId,{id,text,context}); sourceId=id; render();
});
$('newSource').onclick = () => { sourceId=''; $('sourceList').value=''; renderSource(); };
$('sourceList').onchange = () => { sourceId=$('sourceList').value; renderSource(); };
$('deleteSource').onclick = () => action(async () => { await remove('sources',sourceId); sourceId=''; render(); });
submit('thoughtForm', async () => { const old=thought(); const id=thoughtId || crypto.randomUUID(); await save('thoughts',thoughtId,{id,source_id:$('thoughtSource').value,annotation:$('thoughtAnnotation').value,elements:old?.elements || [],links:old?.links || []}); thoughtId=id; render(); });
$('newThought').onclick = () => { thoughtId=''; elementId=''; render(); };
$('thoughtList').onchange = () => { thoughtId=$('thoughtList').value; elementId=''; render(); };
$('deleteThought').onclick = () => action(async () => { await remove('thoughts',thoughtId); thoughtId=''; elementId=''; render(); });
submit('elementForm', async () => {
  const id=elementId || crypto.randomUUID(), kind=$('elementKind').value;
  const old=thought()?.elements.find(e=>e.id===id);
  const value=old?.kind==='literal' && $('elementValue').value===renderedValue ? old.value : $('elementValue').value;
  const e={id,kind,annotation:$('elementAnnotation').value,concept_id:kind==='concept' ? $('elementConcept').value : null,value:kind==='literal' ? value : null};
  await changeThought(t => { t.elements=t.elements.filter(e=>e.id!==id); t.elements.push(e); }); elementId=id; renderElement(); cy.getElementById(id).select();
});
$('newElement').onclick = () => { elementId=''; renderElement(); };
$('elementList').onchange = () => { elementId=$('elementList').value; renderElement(); cy.nodes().unselect(); if(elementId) cy.getElementById(elementId).select(); };
$('elementKind').onchange = toggleKind;
$('deleteElement').onclick = () => action(async () => { if(!elementId) throw new Error('Выберите элемент'); const id=elementId; await changeThought(t=>{t.elements=t.elements.filter(e=>e.id!==id);t.links=t.links.filter(l=>l.source!==id && l.target!==id);}); elementId=''; renderElement(); });
submit('linkForm', async () => { await changeThought(t=>t.links.push({source:$('linkSource').value,target:$('linkTarget').value})); });
$('deleteLink').onclick = () => action(async () => { const index=$('linkList').value; if(index==='') throw new Error('Выберите связь'); await changeThought(t=>t.links.splice(Number(index),1)); });
$('fit').onclick = () => cy.fit(undefined,45);
cy.on('tap','node', event => {elementId=event.target.id();renderElement();});
cy.on('tap','edge', event => {$('linkList').value=event.target.id().slice(5);});
$('importButton').onclick = () => action(async () => {
  const file=$('importFile').files[0]; if(!file) throw new Error('Выберите JSON snapshot');
  const raw=await file.text();
  const response=await fetch(base,{method:'PUT',headers:{'Content-Type':'application/json'},body:raw});
  if(!response.ok) {const error=await response.json();throw new Error(error.detail);}
  state=await response.json();conceptId='';thoughtId=state.thoughts[0]?.id || '';sourceId=thought()?.source_id || state.sources[0]?.id || '';elementId='';render();
});
request().then(data=>{state=data;thoughtId=state.thoughts[0]?.id || '';sourceId=thought()?.source_id || state.sources[0]?.id || '';render();message('Состояние загружено из SQLite.');}).catch(e=>message(e.message,true));
