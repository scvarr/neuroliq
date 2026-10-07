/* Просмотр ограниченного подграфа; топология и словарь читаются с сервера. */
const $ = id => document.getElementById(id);
let graph;
async function api(path) {
  const response = await fetch('/api/l0' + path);
  if (!response.ok) throw new Error((await response.json()).detail || 'Ошибка запроса');
  return response.json();
}
async function task(work) {
  $('message').textContent = '';
  try { await work(); } catch(e) { $('message').textContent = e.message; }
}
function conceptButton(parent, id, label) {
  const button = document.createElement('button');
  button.textContent = label;
  button.onclick = () => task(() => openConcept(id));
  parent.append(button);
}
async function search() {
  const data = await api('/dictionary?q=' + encodeURIComponent($('query').value));
  $('results').replaceChildren();
  data.entries.forEach(e => conceptButton($('results'), e.concept_id, e.surface + ' → ' + e.concept_id));
  $('searchInfo').textContent = data.truncated ? 'Первые 50 форм. Уточните начало формы.' : `Найдено форм: ${data.entries.length}`;
}
async function openConcept(id) {
  const data = await api('/concepts/' + encodeURIComponent(id) + '?limit=' + $('limit').value);
  $('concept').value = id;
  history.replaceState(null, '', '/l0?concept=' + encodeURIComponent(id));
  const labels = Object.fromEntries(data.dictionary.map(e => [e.concept_id, e.surface]));
  $('selection').textContent = `ConceptId: ${id} · форма во внешнем словаре: ${labels[id] || 'нет'}`;
  $('neighborhoodInfo').textContent = `Степень: ${data.degree} · показано концептов: ${data.concepts.length} · связей: ${data.connections.length}` + (data.truncated ? ' · соседство ограничено, увеличьте лимит до 200' : ' · всё соседство');
  $('neighbors').replaceChildren();
  data.concepts.forEach(c => conceptButton($('neighbors'), c.id, `${labels[c.id] || 'Без формы'} → ${c.id}`));
  if (graph) graph.destroy();
  graph = cytoscape({container:$('graph'), elements:[
    ...data.concepts.map(c => ({data:{id:c.id,label:labels[c.id] || c.id,center:c.id === id}})),
    ...data.connections.map((c,i) => ({data:{id:'edge-'+i,source:c.concept_a,target:c.concept_b}}))
  ],style:[{selector:'node',style:{'label':'data(label)','background-color':'#527d95','color':'#183440','font-size':13}},
    {selector:'node[?center]',style:{'background-color':'#cf8844'}},
    {selector:'edge',style:{'width':1,'line-color':'#a8b8c1'}}],layout:{name:'cose',animate:false}});
  graph.on('tap','node',event => task(() => openConcept(event.target.id())));
}
$('searchForm').onsubmit = e => {e.preventDefault(); task(search);};
$('conceptForm').onsubmit = e => {e.preventDefault(); task(() => openConcept($('concept').value.trim()));};
task(async () => {
  const stats = await api('');
  $('stats').textContent = `Концептов: ${stats.concepts.toLocaleString('ru')} · связей: ${stats.connections.toLocaleString('ru')} · форм словаря: ${stats.dictionary_forms.toLocaleString('ru')}`;
  $('cursor').textContent = stats.corpus_cursors.length ? stats.corpus_cursors.map(c => `${c.corpus}\nСледующая позиция: строка ${c.row}, ordinal ${c.ordinal}`).join('\n') : 'Корпус ещё не обрабатывался.';
  await search();
  const params = new URLSearchParams(location.search);
  if (params.has('concept')) await openConcept(params.get('concept'));
});
