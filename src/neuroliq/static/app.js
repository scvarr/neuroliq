"use strict";

const details = document.getElementById("details");
const counts = document.getElementById("counts");
const fit = document.getElementById("fit");

function textElement(tag, text) {
  const element = document.createElement(tag);
  element.textContent = text;
  return element;
}

function field(list, name, value) {
  list.append(textElement("dt", name), textElement("dd", value));
}

async function loadGraph() {
  try {
    const response = await fetch("/api/graph", { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const graph = await response.json();
    const configResponse = await fetch("/api/experiment", { cache: "no-store" });
    if (!configResponse.ok) throw new Error(`HTTP ${configResponse.status}`);
    const config = await configResponse.json();
    document.getElementById("experiment-title").textContent = config.title;
    document.title = `Neuroliq — ${config.title}`;
    function setParameters(parameters) {
      document.getElementById("decay").value = parameters.decay;
      document.getElementById("max-active").value = parameters.max_active;
      document.getElementById("max-steps").value = parameters.max_steps;
    }
    setParameters(config.parameters);
    let started = false;
    let state;
    const seedControls = document.getElementById("seeds");
    for (const [index, concept] of graph.concepts.entries()) {
      const row = document.createElement("label");
      const enabled = document.createElement("input");
      enabled.type = "checkbox";
      enabled.checked = index < 2;
      enabled.dataset.id = concept.id;
      enabled.setAttribute("aria-label", `Seed ${concept.label}`);
      const value = document.createElement("input");
      value.type = "number";
      value.min = "0";
      value.step = "0.1";
      value.value = "1";
      value.setAttribute("aria-label", `Activation ${concept.label}`);
      row.append(enabled, textElement("span", concept.label), value);
      seedControls.append(row);
    }
    const concepts = new Map(graph.concepts.map(concept => [concept.id, concept]));
    const cy = cytoscape({
      container: document.getElementById("graph"),
      elements: [
        ...graph.concepts.map(concept => ({ data: concept })),
        ...graph.connections.map(connection => ({ data: {
          ...connection,
          id: `${connection.concept_a}:${connection.concept_b}`,
          source: connection.concept_a,
          target: connection.concept_b
        } }))
      ],
      layout: { name: "circle", padding: 70, avoidOverlap: true },
      selectionType: "single",
      style: [
        { selector: "node", style: {
          "label": "data(label)", "background-color": "#3975a9",
          "width": 42, "height": 42, "color": "#243547",
          "text-valign": "bottom", "text-margin-y": 10, "font-size": 16
        } },
        { selector: "node[activation > 0]", style: { "background-color": "#df8a22", "label": "data(displayLabel)" } },
        { selector: "edge", style: {
          "width": 2, "line-color": "#8a9eb2", "curve-style": "bezier"
        } },
        { selector: "node:selected", style: {
          "border-width": 4, "border-color": "#df8a22"
        } },
        { selector: "edge:selected", style: { "line-color": "#df8a22" } }
      ]
    });
    counts.textContent = `Концептов: ${graph.concepts.length} · Связей: ${graph.connections.length}`;
    fit.disabled = false;
    fit.addEventListener("click", () => cy.fit(undefined, 70));

    function showDetails(element) {
      const data = element.data();
      details.replaceChildren(textElement("h3", element.isNode() ? "Концепт" : "Связь"));
      const list = document.createElement("dl");
      details.append(list);
      if (element.isNode()) {
        field(list, "ID", data.id);
        field(list, "Метка", data.label);
        field(list, "Текущая activation", String(data.activation || 0));
        details.append(textElement("h3", `Соседи (${data.neighbors.length})`));
        if (!data.neighbors.length) details.append(textElement("p", "Нет соседей — изолированный концепт."));
        const neighbors = document.createElement("ul");
        for (const id of data.neighbors) {
          const item = textElement("li", concepts.get(id).label);
          item.append(textElement("small", id));
          neighbors.append(item);
        }
        details.append(neighbors);
      } else {
        for (const [name, id] of [["Конец A", data.concept_a], ["Конец B", data.concept_b]]) {
          field(list, name, `${concepts.get(id).label} · ${id}`);
        }
        field(list, "strength", String(data.strength));
      }
    }
    cy.on("select", "node, edge", event => showDetails(event.target));

    async function request(command, body) {
      const response = await fetch(`/api/activation/${command}`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: body ? JSON.stringify(body) : undefined
      });
      const result = await response.json();
      if (!response.ok) throw new Error(JSON.stringify(result.detail));
      return result;
    }
    function display(result) {
      state = result;
      cy.nodes().forEach(node => {
        const activation = state.activation[node.id()] || 0;
        node.data({ activation, displayLabel: `${node.data("label")} · ${activation}` });
      });
      document.getElementById("activation-status").textContent = state.step < 0
        ? "Временное состояние сброшено"
        : `Шаг ${state.step} / ${state.parameters.max_steps}`;
      document.getElementById("trace").textContent = state.trace
        ? JSON.stringify(state.trace, null, 2) : "Нет временного состояния";
      const ranking = document.getElementById("ranking");
      ranking.replaceChildren();
      for (const candidate of state.trace?.candidates || []) {
        const row = document.createElement("tr");
        row.append(textElement("td", concepts.get(candidate.id).label),
          textElement("td", String(candidate.activation)),
          textElement("td", candidate.kept ? "Сохранён" : "Отсечён"));
        ranking.append(row);
      }
      const contributions = document.getElementById("contributions");
      contributions.replaceChildren();
      for (const transition of state.trace?.transitions || []) {
        const row = document.createElement("tr");
        row.append(textElement("td", `${concepts.get(transition.source).label} → ${concepts.get(transition.target).label}`),
          textElement("td", `${transition.source_activation} × ${transition.strength} × ${transition.decay}`),
          textElement("td", String(transition.contribution)));
        contributions.append(row);
      }
      const selected = cy.$(":selected");
      if (selected.length) showDetails(selected[0]);
    }
    document.querySelectorAll("#seeds input, .parameters input").forEach(input => {
      input.addEventListener("input", () => {
        started = false;
        document.getElementById("scenario-status").textContent = "Ручные параметры";
        document.getElementById("activation-status").textContent = "Параметры изменены — следующая команда начнёт новый запуск";
      });
    });
    const buttons = ["reset", "step", "run"].map(id => document.getElementById(id));
    const scenarioButtons = config.scenarios.map(scenario => {
      const button = textElement("button", scenario.name);
      button.addEventListener("click", () => {
        for (const row of seedControls.children) {
          const id = row.children[0].dataset.id;
          row.children[0].checked = Object.hasOwn(scenario.seeds, id);
          row.children[2].value = scenario.seeds[id] ?? 1;
        }
        setParameters(config.parameters);
        started = false;
        document.getElementById("scenario-status").textContent = `Сценарий: ${scenario.name}`;
        document.getElementById("run").click();
      });
      document.getElementById("scenarios").append(button);
      return button;
    });
    for (const button of buttons) {
      button.addEventListener("click", async () => {
        [...buttons, ...scenarioButtons].forEach(item => { item.disabled = true; });
        document.querySelectorAll("aside input").forEach(input => { input.disabled = true; });
        try {
          if (button.id === "reset") {
            display(await request("reset"));
            started = false;
          } else {
            if (!started) {
              const seeds = {};
              for (const row of seedControls.children) {
                if (row.children[0].checked) seeds[row.children[0].dataset.id] = Number(row.children[2].value);
              }
              display(await request("start", {
                seeds, decay: Number(document.getElementById("decay").value),
                max_active: Number(document.getElementById("max-active").value),
                max_steps: Number(document.getElementById("max-steps").value)
              }));
              started = true;
            }
            display(await request(button.id));
          }
        } catch (error) {
          document.getElementById("activation-status").textContent = `Ошибка: ${error.message}`;
        } finally {
          [...buttons, ...scenarioButtons].forEach(item => { item.disabled = false; });
          document.querySelectorAll("aside input").forEach(input => { input.disabled = false; });
        }
      });
    }
    const initial = await fetch("/api/activation");
    if (!initial.ok) throw new Error(`HTTP ${initial.status}`);
    const initialState = await initial.json();
    display(initialState);
    if (initialState.parameters) {
      document.getElementById("activation-status").textContent += " · следующий запуск использует параметры формы";
    }
    cy.resize();
    cy.fit(undefined, 70);
    cy.on("tap", event => {
      if (event.target === cy) details.replaceChildren(textElement("p", "Выберите концепт или связь на графе."));
    });
  } catch (error) {
    counts.textContent = "Граф не загружен";
    details.replaceChildren(textElement("p", `Не удалось открыть граф: ${error.message}. Проверьте сервер и обновите страницу.`));
  }
}

loadGraph();
