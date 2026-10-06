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

    cy.on("select", "node, edge", event => {
      const element = event.target;
      const data = element.data();
      details.replaceChildren(textElement("h3", element.isNode() ? "Концепт" : "Связь"));
      const list = document.createElement("dl");
      details.append(list);
      if (element.isNode()) {
        field(list, "ID", data.id);
        field(list, "Метка", data.label);
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
    });
    cy.on("tap", event => {
      if (event.target === cy) details.replaceChildren(textElement("p", "Выберите концепт или связь на графе."));
    });
  } catch (error) {
    counts.textContent = "Граф не загружен";
    details.replaceChildren(textElement("p", `Не удалось открыть граф: ${error.message}. Проверьте сервер и обновите страницу.`));
  }
}

loadGraph();
