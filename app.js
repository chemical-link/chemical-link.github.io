const state = { groups: [], chemical: "all", query: "" };
const $ = (id) => document.getElementById(id);

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function icon(kind) {
  const span = element("span");
  span.innerHTML = kind === "flask"
    ? '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M9 2h6m-5 0v7l-5.7 9.1A2.6 2.6 0 0 0 6.5 22h11a2.6 2.6 0 0 0 2.2-3.9L14 9V2M7 16h10"/></svg>'
    : kind === "down"
      ? '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="m3 6 5 5 5-5"/></svg>'
      : '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M6 3h7v7M13 3 5 11M11 9v4H3V5h4"/></svg>';
  return span.firstChild;
}

function kindLabel(type) {
  if (!type) return "";
  const value = type.toLowerCase();
  if (value.includes("book-chapter")) return "BOOK CHAPTER";
  if (value.includes("book")) return "BOOK";
  if (value.includes("report")) return "REPORT";
  if (value.includes("database")) return "DATABASE RECORD";
  if (value.includes("repository")) return "REPOSITORY";
  if (value.includes("posted-content") || value.includes("preprint")) return "PREPRINT";
  if (value === "resource") return "RESOURCE";
  return "";
}

function paperCard(paper) {
  const card = element("article", "paper-card");
  const meta = element("div", "paper-meta");
  meta.append(element("span", "", paper.year ? String(paper.year) : "DATE NOT LISTED"));
  if (paper.doi) {
    meta.append(element("span", "dot", "·"));
    meta.append(element("span", "", "DOI AVAILABLE"));
  }
  card.append(meta);
  card.append(element("h4", "paper-title", paper.title || "Title unavailable from source"));
  card.append(element("p", "paper-journal" + (paper.journal ? "" : " missing"), paper.journal || "Journal or publication not listed"));

  const actions = element("div", "paper-actions");
  const details = element("details", "abstract-details");
  const isBook = (paper.type || "").toLowerCase().includes("book");
  const summary = element("summary", "", paper.abstract ? (isBook ? "Read description" : "Read abstract") : (isBook ? "Description unavailable" : "Abstract unavailable"));
  summary.append(icon("down"));
  details.append(summary);
  const body = element("div", "abstract-body" + (paper.abstract ? "" : " empty"));
  body.append(element("p", "", paper.abstract || (isBook ? "A book description was not available from the linked source. Open the source for more information." : "A verifiable abstract was not available from the linked source. Open the source for more information.")));
  details.append(body);
  actions.append(details);
  const link = element("a", "", "Open source");
  link.href = paper.url;
  link.target = "_blank";
  link.rel = "noopener noreferrer";
  link.setAttribute("aria-label", `Open source for ${paper.title || "reference"} in a new tab`);
  link.append(icon("external"));
  actions.append(link);
  const label = kindLabel(paper.type);
  if (label) actions.append(element("span", "source-type", label));
  card.append(actions);
  return card;
}

function renderNav() {
  const nav = $("chemical-nav");
  nav.replaceChildren();
  const allCount = state.groups.reduce((sum, group) => sum + group.papers.length, 0);
  const entries = [{ chemical: "All chemicals", papers: Array(allCount), value: "all" }, ...state.groups.map(group => ({ ...group, value: group.chemical }))];
  for (const entry of entries) {
    const button = element("button", "nav-button" + (state.chemical === entry.value ? " active" : ""));
    button.type = "button";
    button.setAttribute("aria-current", state.chemical === entry.value ? "true" : "false");
    button.append(element("span", "nav-name", entry.chemical), element("span", "nav-count", String(entry.papers.length).padStart(2, "0")));
    button.addEventListener("click", () => setChemical(entry.value));
    nav.append(button);
  }
}

function setChemical(value) {
  state.chemical = value;
  $("chemical-select").value = value;
  renderNav();
  renderGroups();
  if (window.innerWidth > 800) $("result-count").scrollIntoView({ behavior: "smooth", block: "start" });
}

function renderGroups() {
  const container = $("paper-groups");
  container.replaceChildren();
  let count = 0;
  let visibleGroups = 0;
  const query = state.query.trim().toLocaleLowerCase();
  for (const [index, group] of state.groups.entries()) {
    if (state.chemical !== "all" && state.chemical !== group.chemical) continue;
    const papers = group.papers.filter(paper => !query || [group.chemical, paper.title, paper.journal, paper.abstract].some(value => String(value || "").toLocaleLowerCase().includes(query)));
    if (!papers.length) continue;
    count += papers.length;
    visibleGroups += 1;
    const section = element("section", "chemical-section");
    section.setAttribute("aria-label", group.chemical);
    const head = element("div", "group-head");
    const titleWrap = element("div", "group-title-wrap");
    const groupIcon = element("span", "group-icon");
    groupIcon.append(icon("flask"));
    const titleBlock = element("div");
    titleBlock.append(element("p", "group-number", `CHEMICAL ${String(index + 1).padStart(2, "0")}`));
    titleBlock.append(element("h3", "", group.chemical));
    titleWrap.append(groupIcon, titleBlock);
    head.append(titleWrap, element("span", "group-count", `${papers.length} ${papers.length === 1 ? "reference" : "references"}`));
    section.append(head);
    const cards = element("div", "cards");
    for (const paper of papers) cards.append(paperCard(paper));
    section.append(cards);
    container.append(section);
  }
  $("result-count").innerHTML = `<strong>${count}</strong> ${count === 1 ? "reference" : "references"} across <strong>${visibleGroups}</strong> ${visibleGroups === 1 ? "chemical" : "chemicals"}`;
  $("view-label").textContent = state.chemical === "all" ? "GROUPED BY CHEMICAL" : "SELECTED CHEMICAL";
  $("empty-state").hidden = count > 0;
  $("clear-filters").hidden = state.chemical === "all" && !query;
}

function clearFilters() {
  state.query = "";
  $("paper-search").value = "";
  setChemical("all");
}

async function init() {
  try {
    const response = await fetch("data/papers.json");
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    if (!Array.isArray(data.groups)) throw new Error("Invalid data");
    state.groups = data.groups;
    $("chemical-total").textContent = String(state.groups.length);
    $("paper-total").textContent = String(state.groups.reduce((sum, group) => sum + group.papers.length, 0));
    const select = $("chemical-select");
    for (const group of state.groups) {
      const option = element("option", "", `${group.chemical} (${group.papers.length})`);
      option.value = group.chemical;
      select.append(option);
    }
    renderNav();
    renderGroups();
  } catch (error) {
    $("result-count").textContent = "References unavailable";
    $("chemical-nav").replaceChildren();
    $("error-state").hidden = false;
  }
}

$("chemical-select").addEventListener("change", event => setChemical(event.target.value));
$("paper-search").addEventListener("input", event => { state.query = event.target.value; renderGroups(); });
$("clear-filters").addEventListener("click", clearFilters);
$("empty-clear").addEventListener("click", clearFilters);
init();
