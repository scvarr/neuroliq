/* Общий граф ConceptId и маршруты; подсказки используются только для отображения. */
const $ = id => document.getElementById(id);
const base = '/api/thought-workbench';
let state, conceptId = '', sourceId = '', thoughtId = '';
let renderedSourceText = '', renderedSourceContext = '';
let queue = Promise.resolve();
const cy = cytoscape({container: $('graph'), elements: [], maxZoom: 1.5, style: [
  {selector: 'node', style: {'label': 'data(label)', 'font-size': 12, 'text-wrap': 'wrap', 'text-max-width': 160, 'background-color': '#356f9e', 'color': '#172c40', 'text-valign': 'bottom', 'text-margin-y': 10}},
  {selector: 'edge', style: {'curve-style': 'bezier', 'line-color': '#6f8192', 'width': 2, 'label': 'data(label)', 'font-size': 11, 'text-background-color': '#f4f7fb', 'text-background-opacity': 1, 'text-background-padding': 4}},
  {selector: 'node.route', style: {'background-color': '#ca6a23'}},
  {selector: 'edge.route', style: {'line-color': '#ca6a23', 'width': 4}},
  {selector: 'node:selected', style: {'border-width': 3, 'border-color': '#172c40'}}
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
function label(id) { return state.concepts.find(c => c.id === id)?.annotation || id; }
function pairKey(a, b) { return [a, b].sort().join('/'); }
function renderCatalog() {
  const query = $('conceptSearch').value.toLocaleLowerCase();
  const concepts = state.concepts.filter(c => (c.annotation + c.id).toLocaleLowerCase().includes(query)).sort((a,b) => a.annotation.localeCompare(b.annotation) || a.id.localeCompare(b.id));
  const records = concepts.map(c => ({id:c.id,label:c.annotation || c.id}));
  options('conceptList', records, conceptId);
  options('routeConcept', records, $('routeConcept').value || conceptId, 'Выберите концепт');
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
function renderGraph() {
  const route = thought()?.route || [];
  const steps = new Map(), transitions = new Map();
  route.forEach((id, i) => { if (!steps.has(id)) steps.set(id, []); steps.get(id).push(i + 1); });
  for (let i = 1; i < route.length; i++) {
    const key = pairKey(route[i - 1], route[i]);
    if (!transitions.has(key)) transitions.set(key, []);
    transitions.get(key).push(`${i}→${i + 1}`);
  }
  cy.elements().remove();
  cy.add([...state.concepts].sort((a,b)=>a.id.localeCompare(b.id)).map(c => ({data:{id:c.id,label:(c.annotation || c.id) + (steps.has(c.id) ? '\nШаги: ' + steps.get(c.id).join(', ') : '')},classes:steps.has(c.id) ? 'route' : ''})));
  cy.add(state.connections.map(c => {
    const key = pairKey(c.concept_a, c.concept_b);
    return {data:{id:'connection:' + key,source:c.concept_a,target:c.concept_b,label:transitions.has(key) ? 'Переходы: ' + transitions.get(key).join(', ') : ''},classes:transitions.has(key) ? 'route' : ''};
  }));
  cy.layout({name:'circle', radius:Math.max(70,state.concepts.length*20), padding:60, nodeDimensionsIncludeLabels:true}).run();
  if (conceptId) cy.getElementById(conceptId).select();
}
function render() {
  $('counts').textContent = `Концептов: ${state.concepts.length} · общих связей: ${state.connections.length} · фрагментов: ${state.sources.length} · мыслей: ${state.thoughts.length}`;
  renderCatalog(); renderConcept();
  const concepts = state.concepts.map(c => ({id:c.id,label:c.annotation || c.id}));
  options('connectionA', concepts, $('connectionA').value, 'Выберите ConceptId');
  options('connectionB', concepts, $('connectionB').value, 'Выберите ConceptId');
  options('connectionList', state.connections.map(c => ({id:pairKey(c.concept_a,c.concept_b),label:`${label(c.concept_a)} [${c.concept_a.slice(0,8)}] — ${label(c.concept_b)} [${c.concept_b.slice(0,8)}]`})), '', 'Выберите связь');
  const sources = state.sources.map(s => ({id:s.id,label:s.text.slice(0, 65) || s.id}));
  options('sourceList', sources, sourceId, 'Новый фрагмент'); renderSource();
  options('thoughtList', state.thoughts.map(t => ({id:t.id,label:t.annotation || t.id})), thoughtId, 'Новая мысль');
  const t = thought();
  $('thoughtAnnotation').value = t?.annotation || '';
  options('thoughtSource', sources, t?.source_id || sourceId, 'Выберите источник');
  $('thoughtId').textContent = thoughtId || 'Новая мысль получит UUID';
  const s = state.sources.find(s => s.id === t?.source_id);
  $('thoughtEvidence').textContent = s ? s.text + (s.context ? '\nКонтекст: ' + s.context : '') : '';
  $('routePath').textContent = t ? (t.route.map((id,i)=>`[${i + 1}] ${label(id)}`).join(' → ') || 'Маршрут пуст — добавьте первый ConceptId.') : 'Выберите или сохраните мысль.';
  options('routeSteps', (t?.route || []).map((id,i)=>({id:String(i),label:`${i + 1}. ${label(id)} [${id}]`})), '', 'Выберите шаг');
  renderGraph();
}
async function save(collection, id, record) { state = await request(`/${collection}${id ? '/' + id : ''}`, id ? 'PUT' : 'POST', record); }
async function remove(collection, id) { if (!id) throw new Error('Выберите сохранённую запись'); state = await request(`/${collection}/${id}`, 'DELETE'); }
async function changeRoute(fn, selected = '') {
  const t = thought(); if (!t) throw new Error('Сначала сохраните мысль');
  const copy = structuredClone(t); fn(copy.route); await save('thoughts', t.id, copy); render(); $('routeSteps').value = selected;
}
function selectedStep() { const index = $('routeSteps').value; if (index === '') throw new Error('Выберите шаг маршрута'); return Number(index); }
function submit(id, fn) { $(id).addEventListener('submit', event => { event.preventDefault(); action(fn); }); }
submit('conceptForm', async () => { const id = conceptId || crypto.randomUUID(); await save('concepts', conceptId, {id, annotation:$('conceptAnnotation').value}); conceptId=id; render(); });
$('newConcept').onclick = () => { conceptId=''; $('conceptList').value=''; renderConcept(); };
$('conceptList').onchange = () => { conceptId=$('conceptList').value; renderConcept(); $('routeConcept').value=conceptId; };
$('conceptSearch').oninput = renderCatalog;
$('deleteConcept').onclick = () => action(async () => { await remove('concepts',conceptId); conceptId=''; render(); });
submit('connectionForm', async () => { state=await request('/connections','POST',{concept_a:$('connectionA').value,concept_b:$('connectionB').value}); render(); });
$('deleteConnection').onclick = () => action(async () => { const key=$('connectionList').value; if(!key) throw new Error('Выберите общую связь'); state=await request('/connections/' + key,'DELETE'); render(); });
submit('sourceForm', async () => {
  const id=sourceId || crypto.randomUUID(), old=state.sources.find(s=>s.id===sourceId);
  const text=old && $('sourceText').value===renderedSourceText ? old.text : $('sourceText').value;
  const context=old && $('sourceContext').value===renderedSourceContext ? old.context : $('sourceContext').value;
  await save('sources',sourceId,{id,text,context}); sourceId=id; render();
});
$('newSource').onclick = () => { sourceId=''; $('sourceList').value=''; renderSource(); };
$('sourceList').onchange = () => { sourceId=$('sourceList').value; renderSource(); };
$('deleteSource').onclick = () => action(async () => { await remove('sources',sourceId); sourceId=''; render(); });
submit('thoughtForm', async () => { const old=thought(); const id=thoughtId || crypto.randomUUID(); await save('thoughts',thoughtId,{id,source_id:$('thoughtSource').value,annotation:$('thoughtAnnotation').value,route:old?.route || []}); thoughtId=id; render(); });
$('newThought').onclick = () => { thoughtId=''; render(); };
$('thoughtList').onchange = () => { thoughtId=$('thoughtList').value; render(); };
$('deleteThought').onclick = () => action(async () => { await remove('thoughts',thoughtId); thoughtId=''; render(); });
submit('routeForm', async () => { const id=$('routeConcept').value; if(!id) throw new Error('Выберите существующий ConceptId'); await changeRoute(route=>route.push(id)); });
$('deleteStep').onclick = () => action(async () => { const index=selectedStep(); await changeRoute(route=>route.splice(index,1)); });
function moveStep(delta) { action(async () => { const index=selectedStep(), target=index+delta; if(target<0 || target>=thought().route.length) throw new Error('Шаг уже на границе маршрута'); await changeRoute(route=>{[route[index],route[target]]=[route[target],route[index]];},String(target)); }); }
$('stepUp').onclick = () => moveStep(-1); $('stepDown').onclick = () => moveStep(1);
$('routeSteps').onchange = () => { const index=$('routeSteps').value; cy.nodes().unselect(); if(index!=='') cy.getElementById(thought().route[Number(index)]).select(); };
$('fit').onclick = () => cy.fit(undefined,60);
cy.on('tap','node', event => {conceptId=event.target.id();renderCatalog();renderConcept();$('routeConcept').value=conceptId;});
cy.on('tap','edge', event => {$('connectionList').value=event.target.id().slice('connection:'.length);});
$('importButton').onclick = () => action(async () => {
  const file=$('importFile').files[0]; if(!file) throw new Error('Выберите JSON snapshot');
  const response=await fetch(base,{method:'PUT',headers:{'Content-Type':'application/json'},body:await file.text()});
  if(!response.ok) {const error=await response.json();throw new Error(error.detail);}
  state=await response.json();conceptId='';thoughtId=state.thoughts[0]?.id || '';sourceId=thought()?.source_id || state.sources[0]?.id || '';render();
});
request().then(data=>{state=data;thoughtId=state.thoughts[0]?.id || '';sourceId=thought()?.source_id || state.sources[0]?.id || '';render();message('Состояние загружено из SQLite.');}).catch(e=>message(e.message,true));
