"use strict";
const $ = id => document.getElementById(id);
let definition, state, cy, queue = Promise.resolve();
const element = (tag, text) => { const item = document.createElement(tag); item.textContent = text; return item; };
const labelFor = id => definition.concepts.find(c => c.id === id)?.label ?? id;
async function api(path, method = "GET", body) {
  const response = await fetch(`/api/${path}`, {method, headers: {"Content-Type": "application/json"}, body});
  if (!response.ok) {
    const error = await response.json();
    throw new Error(typeof error.detail === "string" ? error.detail : JSON.stringify(error.detail));
  }
  return response.json();
}
// Очередь исключает пересечение сохранения формы и команды запуска.
function task(action) {
  queue = queue.then(async () => {
    try { await action(); $("status").textContent = "Готово"; }
    catch (error) { $("status").textContent = `Ошибка: ${error.message}`; }
  });
  return queue;
}
async function replace(next) {
  definition = await api("experiment", "PUT", JSON.stringify(next));
  state = await api("activation");
  render();
}
function edit(change) {
  task(async () => { const next = structuredClone(definition); change(next); await replace(next); });
}
function input(type, value, name, changed) {
  const field = document.createElement("input"); field.type = type; field.value = value;
  field.setAttribute("aria-label", name);
  if (type === "number") field.step = "any";
  field.addEventListener("change", () => changed(type === "number" ? field.valueAsNumber : field.value));
  return field;
}
function render() {
  $("title").value = definition.title;
  $("json").value = JSON.stringify(definition, null, 2);
  $("concepts").replaceChildren(); $("connections").replaceChildren();
  $("counts").textContent = `Концептов: ${definition.concepts.length} · Связей: ${definition.connections.length}`;
  for (const c of definition.concepts) {
    const row = element("div", ""); row.className = "editor-row";
    row.append(input("text", c.label, `Метка ${c.label}`, value => edit(d => { d.concepts.find(x => x.id === c.id).label = value; })));
    row.append(element("small", c.id));
    const seed = input("checkbox", "", `Seed ${c.label}`, () => edit(d => {
      if (seed.checked) d.run.seeds[c.id] = 1; else delete d.run.seeds[c.id];
    }));
    seed.checked = Object.hasOwn(definition.run.seeds, c.id);
    const seedLabel = element("label", "Seed "); seedLabel.append(seed); row.append(seedLabel);
    row.append(input("number", definition.run.seeds[c.id] ?? 1, `activation ${c.label}`, value => edit(d => { d.run.seeds[c.id] = value; })));
    const remove = element("button", "Удалить концепт"); remove.addEventListener("click", () => edit(d => {
      d.concepts = d.concepts.filter(x => x.id !== c.id);
      d.connections = d.connections.filter(x => x.concept_a !== c.id && x.concept_b !== c.id);
      delete d.run.seeds[c.id];
    })); row.append(remove); $("concepts").append(row);
  }
  definition.connections.forEach((c, index) => {
    const row = element("div", `${labelFor(c.concept_a)} ↔ ${labelFor(c.concept_b)} `); row.className = "editor-row";
    row.append(input("number", c.strength, `strength ${labelFor(c.concept_a)} ${labelFor(c.concept_b)}`, value => edit(d => { d.connections[index].strength = value; })));
    const remove = element("button", "Удалить связь"); remove.addEventListener("click", () => edit(d => { d.connections.splice(index, 1); })); row.append(remove);
    $("connections").append(row);
  });
  for (const id of ["connection-a", "connection-b"]) {
    $(id).replaceChildren(...definition.concepts.map(c => { const option = element("option", c.label); option.value = c.id; return option; }));
  }
  if (definition.concepts.length > 1) $("connection-b").selectedIndex = 1;
  for (const [id, key] of [["decay", "decay"], ["max-active", "max_active"], ["max-steps", "max_steps"]]) $(id).value = definition.run[key];
  cy.elements().remove();
  cy.add([
    ...definition.concepts.map(c => ({data: {id: c.id, label: c.label, displayLabel: c.label}})),
    ...definition.connections.map((c, i) => ({data: {id: `edge-${i}`, source: c.concept_a, target: c.concept_b, strength: c.strength}}))
  ]);
  cy.layout({name: "circle"}).run();
  $("details").textContent = "Выберите концепт или связь";
  display();
}
function displayTrace(trace) {
  $("trace").textContent = trace ? JSON.stringify(trace, null, 2) : "Нет временного состояния";
  $("ranking").replaceChildren(); $("contributions").replaceChildren();
  for (const c of trace?.candidates ?? []) {
    const row = element("tr", "");
    for (const value of [labelFor(c.id), c.activation, c.kept ? "Сохранён" : "Отсечён"]) row.append(element("td", value));
    $("ranking").append(row);
  }
  for (const t of trace?.transitions ?? []) {
    const row = element("tr", "");
    for (const value of [`${labelFor(t.source)} → ${labelFor(t.target)}`, `${t.source_activation} × ${t.strength} × ${t.decay}`, t.contribution]) row.append(element("td", value));
    $("contributions").append(row);
  }
}
function showDetails(item) {
  $("details").textContent = JSON.stringify(item.isNode()
    ? {id: item.id(), label: item.data("label"), activation: state.activation[item.id()] ?? 0}
    : {concept_a: item.data("source"), concept_b: item.data("target"), strength: item.data("strength")}, null, 2);
}
function display() {
  cy.nodes().forEach(node => {
    const value = state.activation[node.id()] ?? 0;
    node.data({displayLabel: `${node.data("label")} · ${value}`, active: Object.hasOwn(state.activation, node.id()) ? "yes" : "no"});
  });
  $("activation-status").textContent = state.step < 0 ? "Runtime сброшен" : `Шаг ${state.step} / ${state.parameters.max_steps}`;
  $("trace-step").replaceChildren(...state.traces.map(t => { const option = element("option", `Шаг ${t.step}`); option.value = t.step; return option; }));
  $("trace-step").value = state.step; $("trace-step").disabled = !state.traces.length;
  displayTrace(state.trace);
  const selected = cy.$(":selected"); if (selected.length) showDetails(selected[0]);
}
$("title").addEventListener("change", event => { const value = event.target.value; edit(d => { d.title = value; }); });
for (const [id, key] of [["decay", "decay"], ["max-active", "max_active"], ["max-steps", "max_steps"]]) $(id).addEventListener("change", event => {
  const value = event.target.valueAsNumber; edit(d => { d.run[key] = value; });
});
$("add-concept").onclick = () => { const label = $("new-label").value; edit(d => { d.concepts.push({id: crypto.randomUUID(), label}); }); };
$("add-connection").onclick = () => {
  const connection = {concept_a: $("connection-a").value, concept_b: $("connection-b").value, strength: $("new-strength").valueAsNumber};
  edit(d => { d.connections.push(connection); });
};
$("new").onclick = () => task(() => replace({format_version: 1, title: "Новый эксперимент", concepts: [], connections: [], run: {seeds: {}, decay: 0.5, max_active: 10, max_steps: 2}}));
$("import").onchange = event => { const file = event.target.files[0]; if (file) task(async () => { definition = await api("experiment", "PUT", await file.text()); state = await api("activation"); render(); $("import").value = ""; }); };
$("import-json").onclick = () => { const source = $("json").value; task(async () => { definition = await api("experiment", "PUT", source); state = await api("activation"); render(); }); };
$("export").onclick = () => task(async () => {
  const link = document.createElement("a"); link.href = "/api/experiment/export";
  link.download = "experiment.neuroliq.json"; document.body.append(link); link.click(); link.remove();
});
for (const command of ["start", "step", "run", "reset"]) $(command).onclick = () => task(async () => { state = await api(`activation/${command}`, "POST"); display(); });
$("trace-step").onchange = () => displayTrace(state.traces.find(t => t.step === Number($("trace-step").value)));
$("fit").onclick = () => cy.fit(undefined, 40);
task(async () => {
  cy = cytoscape({container: $("graph"), style: [
    {selector: "node", style: {label: "data(displayLabel)", "background-color": "#617487", color: "#243547", "text-valign": "bottom", "text-margin-y": 8}},
    {selector: 'node[active="yes"]', style: {"background-color": "#e89730"}},
    {selector: "edge", style: {width: 2, "line-color": "#9aabbc"}},
    {selector: ":selected", style: {"border-width": 3, "border-color": "#245e95", "line-color": "#245e95"}}
  ]});
  cy.on("tap", "node, edge", event => showDetails(event.target));
  definition = await api("experiment"); state = await api("activation"); render();
});
