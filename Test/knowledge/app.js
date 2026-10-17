"use strict";

const $ = (id) => document.getElementById(id);
const fmt = (n) => Number(n).toLocaleString("ko-KR");
const typeNames = {
  Disease: "질환", Symptom: "증상", ExamFinding: "진찰 소견", ClinicalPattern: "임상 패턴",
  ClinicalFeature: "패턴 조건", DiseasePatternAssociation: "질환–패턴 연결", ExpectedValue: "기대값",
  FindingAttribute: "속성", AttributeValue: "속성값", ContextFactor: "맥락 요인",
  BodySystem: "신체 계통", ExamMethod: "진찰 방법", Test: "검사", ValueMatch: "값 비교 경로",
  Class: "스키마 클래스", Property: "관계 정의",
};
const state = {type: "Disease", offset: 0, selected: null, history: [], direction: "out", predicate: "", relationOffset: 0, rowOffset: 0, db: "competition", table: "registry"};
let overview, searchVersion = 0, selectionVersion = 0, rowsVersion = 0, dbVersion = 0;

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function button(text, handler, className = "") {
  const node = el("button", className, text);
  node.type = "button";
  node.addEventListener("click", () => run(handler));
  return node;
}

function error(message) {
  $("error").textContent = message;
  $("error").hidden = !message;
}

async function run(work) {
  error("");
  try { await work(); }
  catch (e) { error(e.message || String(e)); }
}

async function api(route, params = {}) {
  const response = await fetch(`/api/${route}?${new URLSearchParams(params)}`, {cache: "no-store"});
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || `조회 실패 (${response.status})`);
  return data;
}

function option(select, value, label) {
  const node = el("option", "", label);
  node.value = value;
  select.append(node);
}

function typeText(item) { return item.types.map((t) => typeNames[t] || t).join(" / ") || "스키마 항목"; }

async function view(name) {
  document.querySelectorAll(".view").forEach((node) => { node.hidden = node.id !== name; });
  document.querySelectorAll(".nav").forEach((node) => {
    node.classList.toggle("active", node.dataset.view === name);
    node.setAttribute("aria-pressed", String(node.dataset.view === name));
  });
  if (name === "database" && !$("table-select").options.length) await loadTables();
}

function setType(kind) {
  state.type = kind;
  state.offset = 0;
  $("type-select").value = kind;
  document.querySelectorAll(".type-button").forEach((node) => {
    node.classList.toggle("selected", node.dataset.type === kind);
    node.setAttribute("aria-pressed", String(node.dataset.type === kind));
  });
  return search();
}

async function search() {
  const version = ++searchVersion;
  const result = await api("search", {q: $("search").value, type: state.type, offset: state.offset});
  if (version !== searchVersion) return;
  $("result-count").textContent = `${fmt(result.total)}개 항목`;
  $("results").replaceChildren();
  for (const item of result.items) {
    const node = button("", () => select(item.id), "result");
    node.dataset.id = item.id;
    node.append(el("strong", "", item.label), el("small", "", typeText(item)));
    node.classList.toggle("selected", state.selected === item.id);
    node.setAttribute("aria-pressed", String(state.selected === item.id));
    $("results").append(node);
  }
  if (!result.total) $("results").append(el("p", "no-results", "일치하는 항목이 없습니다. 다른 이름이나 SCTID로 검색해 보세요."));
  $("search-prev").disabled = state.offset === 0;
  $("search-next").disabled = state.offset + 50 >= result.total;
  $("search-page").textContent = result.total ? `${Math.floor(state.offset / 50) + 1} / ${Math.ceil(result.total / 50)}` : "0 / 0";
}

function nodeLink(item) { return button(item.label, () => select(item.id), "node-link"); }

function rawValue(value) {
  if (typeof value !== "string") return value;
  try { return JSON.parse(value); } catch (_) { return value; }
}

function sourceIds(value, ids = new Set(), key = "") {
  if (typeof value === "string") {
    for (const match of value.matchAll(/source_row:(\d+)/g)) ids.add(match[1]);
  } else if (typeof value === "number" && /row_id$/.test(key)) ids.add(String(value));
  else if (Array.isArray(value)) value.forEach((item) => sourceIds(item, ids, key.replace(/ids$/, "id")));
  else if (value && typeof value === "object") Object.entries(value).forEach(([k, v]) => sourceIds(v, ids, k));
  return ids;
}

function renderRaw(container, value) {
  const parsed = rawValue(value);
  const ids = [...sourceIds(parsed)];
  if (ids.length) {
    container.append(el("p", "muted small", `원천 행 참조 ${fmt(ids.length)}개 · 버튼을 누르면 원본 행과 파일 위치를 확인합니다.`));
    const links = el("div");
    ids.slice(0, 80).forEach((id) => links.append(button(`행 ${id}`, () => showSource(id), "source-button")));
    container.append(links);
    if (ids.length > 80) container.append(el("p", "muted small", "앞의 80개 참조를 표시했습니다. 전체 참조는 아래 원문에 있습니다."));
  }
  container.append(el("pre", "", typeof parsed === "string" ? parsed : JSON.stringify(parsed, null, 2)));
}

async function showSource(id) {
  const row = await api("source-row", {id});
  const target = $("source-content");
  target.replaceChildren(el("p", "break", row.path), el("p", "muted", `파일의 ${row.line}행 · ${row.dataset} · 원천 행 ID ${row.id}`));
  target.append(el("p", "mono", `SHA-256 ${row.sha256}`));
  renderRaw(target, row.payload);
  if (!$("source-dialog").open) $("source-dialog").showModal();
}

async function select(id, remember = true, resetRelations = true) {
  const version = ++selectionVersion;
  if (remember && state.selected && state.selected !== id) state.history.push(state.selected);
  state.selected = id;
  if (resetRelations) { state.direction = "out"; state.predicate = ""; state.relationOffset = 0; }
  const params = {id, direction: state.direction, predicate: state.predicate, offset: state.relationOffset};
  const [item, graph] = await Promise.all([api("node", params), api("graph", {id})]);
  if (version !== selectionVersion) return;
  document.querySelectorAll(".result").forEach((node) => {
    node.classList.toggle("selected", node.dataset.id === id);
    node.setAttribute("aria-pressed", String(node.dataset.id === id));
  });
  const inspector = $("inspector");
  inspector.replaceChildren();
  const heading = el("div", "node-heading"), title = el("div");
  title.append(el("div", "node-kind", typeText(item)), el("h1", "", item.label));
  heading.append(title);
  if (state.history.length) heading.append(button("뒤로", () => select(state.history.pop(), false), "back-button"));
  inspector.append(heading);
  if (item.derived_label) inspector.append(el("p", "label-note", "그래프 조건으로 구성한 표시 이름입니다. 원천의 공식 명칭과 구분됩니다."));
  const identifier = el("div", "identifier");
  identifier.append(el("code", "", id), button("복사", async () => {
    if (navigator.clipboard) await navigator.clipboard.writeText(id);
    else { const range = document.createRange(); range.selectNodeContents(identifier.firstChild); const selection = window.getSelection(); selection.removeAllRanges(); selection.addRange(range); }
  }));
  inspector.append(identifier);
  if (item.labels.length > 1) {
    const aliases = el("details");
    aliases.append(el("summary", "", `명칭과 동의어 ${fmt(item.labels.length)}개`));
    const list = el("dl", "facts");
    for (const label of item.labels) list.append(el("dt", "", `${label.language || "언어 없음"} · ${label.kind}`), el("dd", "", label.text));
    aliases.append(list); inspector.append(aliases);
  }
  if (item.question) {
    const delivery = el("details");
    delivery.append(el("summary", "", "준비된 한국어 환자 문구"));
    renderRaw(delivery, item.question); inspector.append(delivery);
  }
  const graphSection = el("section", "graph-section"), bar = el("div", "section-bar");
  bar.append(el("h2", "", "주변 연결"), el("span", "", "항목 선택: 이동 · 가로·세로 스크롤"));
  const canvas = el("div", "graph-canvas");
  graphSection.append(bar, canvas, el("div", "graph-note", graph.truncated ? "읽기 쉬운 일부 연결을 표시합니다. 모든 관계는 아래 목록에서 확인할 수 있습니다." : "화살표는 실제 RDF 관계의 방향입니다. 전체 그래프를 한 화면에 펼치지 않고 주변 연결을 표시합니다."));
  inspector.append(graphSection);
  drawGraph(canvas, graph);
  const tabs = el("div", "tabs");
  for (const [direction, label] of [["out", `나가는 연결 ${fmt(item.outgoing)}`], ["in", `들어오는 연결 ${fmt(item.incoming)}`]]) {
    const tab = button(label, () => { state.direction = direction; state.predicate = ""; state.relationOffset = 0; return select(id, false, false); }, direction === state.direction ? "active" : "");
    tab.setAttribute("aria-pressed", String(direction === state.direction)); tabs.append(tab);
  }
  inspector.append(tabs);
  const filters = el("div", "relation-filters"), selectRelation = el("select");
  selectRelation.setAttribute("aria-label", "관계 종류");
  option(selectRelation, "", "모든 관계");
  item.predicates.forEach((p) => option(selectRelation, p.id, `${p.label} (${fmt(p.count)})`));
  selectRelation.value = state.predicate;
  selectRelation.addEventListener("change", () => run(() => { state.predicate = selectRelation.value; state.relationOffset = 0; return select(id, false, false); }));
  filters.append(selectRelation, el("span", "muted small", `${fmt(item.total)}개 연결`)); inspector.append(filters);
  for (const link of item.items) {
    const row = el("div", "relation-row");
    row.append(el("span", "", link.relation), nodeLink(link.node)); inspector.append(row);
  }
  if (!item.total) inspector.append(el("p", "muted small", "이 방향으로 연결된 항목이 없습니다."));
  if (item.total > 50) {
    const pager = el("div", "pager");
    const prev = button("이전", () => { state.relationOffset -= 50; return select(id, false, false); });
    const next = button("다음", () => { state.relationOffset += 50; return select(id, false, false); });
    prev.disabled = !state.relationOffset; next.disabled = state.relationOffset + 50 >= item.total;
    pager.append(prev, el("span", "", `${state.relationOffset + 1}–${Math.min(state.relationOffset + 50, item.total)}`), next); inspector.append(pager);
  }
  const facts = el("details", "raw-section");
  facts.open = item.literals.length < 8;
  facts.append(el("summary", "", `속성·원천 참조 ${fmt(item.literals.length)}개`));
  const values = el("dl", "facts");
  item.literals.forEach((value) => {
    const cell = el("dd"); cell.append(el("pre", "", value.value));
    values.append(el("dt", "", value.relation), cell);
  });
  facts.append(values); inspector.append(facts);
  const provenance = el("details", "raw-section");
  provenance.append(el("summary", "", "준비 DB의 등록 정보와 원천 근거"));
  let fetched = false;
  provenance.addEventListener("toggle", () => {
    if (!provenance.open || fetched) return;
    fetched = true;
    run(async () => {
      try {
        const result = await api("provenance", {id});
        if (!result.registry && !result.assertions.length) provenance.append(el("p", "muted small", result.unavailable ? "준비 데이터베이스가 없습니다." : "직접 등록된 근거가 없습니다. 연결된 질환–패턴 항목의 원천 근거를 확인하세요."));
        else renderRaw(provenance, result);
      } catch (e) { fetched = false; throw e; }
    });
  });
  inspector.append(provenance);
  if (resetRelations) inspector.scrollTop = 0;
}

function drawGraph(container, graph) {
  const ns = "http://www.w3.org/2000/svg";
  const svgEl = (tag, attributes = {}, text) => {
    const node = document.createElementNS(ns, tag);
    Object.entries(attributes).forEach(([key, value]) => node.setAttribute(key, value));
    if (text !== undefined) node.textContent = text;
    return node;
  };
  const ranks = {Disease: 0, DiseasePatternAssociation: 1, ClinicalPattern: 2, Symptom: 3, ExamFinding: 3, ClinicalFeature: 3, ContextFactor: 3, FindingAttribute: 4, ExpectedValue: 4, AttributeValue: 5, BodySystem: 4, ExamMethod: 4};
  const columns = new Map();
  graph.nodes.forEach((node) => {
    const rank = ranks[node.types[0]] ?? 4;
    if (!columns.has(rank)) columns.set(rank, []);
    columns.get(rank).push(node);
  });
  const activeRanks = [...columns.keys()].sort((a, b) => a - b), positions = new Map();
  const width = Math.max(650, activeRanks.length * 220 + 30), height = Math.max(330, ...[...columns.values()].map((items) => items.length * 82 + 48));
  activeRanks.forEach((rank, index) => columns.get(rank).forEach((node, row) => positions.set(node.id, {x: 20 + index * 220, y: 30 + row * 82})));
  const svg = svgEl("svg", {width, height, viewBox: `0 0 ${width} ${height}`, role: "group", "aria-label": "선택한 항목 주변의 지식 연결 그래프"});
  const defs = svgEl("defs"), marker = svgEl("marker", {id: "arrow", viewBox: "0 0 10 10", refX: 9, refY: 5, markerWidth: 6, markerHeight: 6, orient: "auto-start-reverse"});
  marker.append(svgEl("path", {d: "M 0 0 L 10 5 L 0 10 z", fill: "#91a8c5"})); defs.append(marker); svg.append(defs);
  for (const edge of graph.edges) {
    const source = positions.get(edge.source), target = positions.get(edge.target);
    if (!source || !target) continue;
    const forward = target.x > source.x;
    const sx = source.x + (forward ? 180 : 0), tx = target.x + (forward ? 0 : 180), sy = source.y + 27, ty = target.y + 27;
    const mid = (sx + tx) / 2;
    svg.append(svgEl("path", {d: `M${sx},${sy} C${mid},${sy} ${mid},${ty} ${tx},${ty}`, class: "graph-edge", "marker-end": "url(#arrow)"}));
    if (Math.abs(sy - ty) < 100 && Math.abs(sx - tx) > 15) svg.append(svgEl("text", {x: mid, y: (sy + ty) / 2 - 6, "text-anchor": "middle", class: "graph-edge-label"}, edge.label));
  }
  for (const node of graph.nodes) {
    const {x, y} = positions.get(node.id), group = svgEl("g", {transform: `translate(${x},${y})`, class: `graph-node${node.id === graph.focus ? " focus" : ""}`, tabindex: "0", role: "button", "aria-label": `${typeText(node)}: ${node.label}`});
    group.append(svgEl("title", {}, node.label), svgEl("rect", {width: 180, height: 56, rx: 6}));
    group.append(svgEl("text", {x: 10, y: 17, class: "node-type"}, typeText(node)));
    const lines = [""];
    let units = 0;
    for (const char of node.label) {
      const weight = char.charCodeAt(0) > 255 ? 2 : 1;
      if (units + weight > 27) {
        if (lines.length === 2) { lines[1] = lines[1].slice(0, -1) + "…"; break; }
        lines.push(""); units = 0;
      }
      lines[lines.length - 1] += char; units += weight;
    }
    lines.forEach((line, i) => group.append(svgEl("text", {x: 10, y: 34 + i * 14}, line)));
    group.addEventListener("click", () => run(() => select(node.id)));
    group.addEventListener("keydown", (event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); run(() => select(node.id)); } });
    svg.append(group);
  }
  container.append(svg);
  const focus = positions.get(graph.focus);
  if (focus) { container.scrollLeft = Math.max(0, focus.x - container.clientWidth / 2 + 90); container.scrollTop = Math.max(0, focus.y - 110); }
}

async function loadTables() {
  const version = ++dbVersion;
  const data = await api("tables", {db: state.db});
  if (version !== dbVersion) return;
  state.tables = data.tables;
  $("table-select").replaceChildren();
  data.tables.forEach((table) => option($("table-select"), table.name, table.name));
  if (!data.tables.some((t) => t.name === state.table)) state.table = data.tables[0].name;
  $("table-select").value = state.table;
  $("db-path").textContent = overview.databases.find((db) => db.id === state.db).path;
  $("db-metadata").replaceChildren();
  if (data.metadata.source_custody) {
    $("db-metadata").append(document.createTextNode("이 준비 DB의 원천 테이블은 공유 보관 DB를 참조합니다. "), button("Source custody 열기", () => { state.db = "source"; state.table = "source_rows"; $("db-select").value = state.db; return loadTables(); }, "toolbar-button"));
  } else $("db-metadata").textContent = "이 데이터베이스에 실제로 저장된 테이블을 표시합니다. 준비 후보의 상태는 런타임 수용 상태와 다를 수 있습니다.";
  await chooseTable();
}

async function chooseTable() {
  state.rowOffset = 0;
  $("row-query").value = "";
  $("column-select").replaceChildren();
  const table = state.tables.find((t) => t.name === state.table);
  const schema = $("schema-content"); schema.replaceChildren();
  const columns = el("div", "schema-columns");
  for (const column of table.columns) {
    option($("column-select"), column.name, column.name);
    columns.append(el("span", "", `${column.name}: ${column.type || "ANY"}${column.pk ? " · PK" : ""}`));
  }
  schema.append(columns, el("pre", "", table.sql));
  table.foreign_keys.forEach((fk) => schema.append(el("p", "mono", `${fk.from} → ${fk.table}.${fk.to}`)));
  $("row-detail").open = false; $("row-detail-content").replaceChildren();
  await loadRows();
}

async function loadRows() {
  const version = ++rowsVersion;
  $("row-count").textContent = "조회 중…";
  $("raw-table").replaceChildren();
  $("row-detail").open = false;
  $("row-detail-content").replaceChildren();
  $("row-prev").disabled = true; $("row-next").disabled = true;
  let data;
  try {
    data = await api("rows", {db: state.db, table: state.table, column: $("column-select").value, mode: $("match-select").value, q: $("row-query").value, offset: state.rowOffset});
  } catch (e) {
    if (version === rowsVersion) $("row-count").textContent = "조회하지 못했습니다. 검색 조건을 확인해 주세요.";
    throw e;
  }
  if (version !== rowsVersion) return;
  const table = el("table"), head = el("thead"), headRow = el("tr"), body = el("tbody");
  data.columns.forEach((column) => headRow.append(el("th", "", column))); head.append(headRow); table.append(head, body);
  for (const row of data.rows) {
    const tr = el("tr", "raw-table-row"); tr.tabIndex = 0;
    for (const column of data.columns) {
      const td = el("td"), value = row[column];
      if (data.node_refs[value]) {
        const link = button(data.node_refs[value].label, async () => { await view("explore"); await select(value); }, "node-link");
        link.addEventListener("click", (event) => event.stopPropagation()); td.append(link);
      } else if (column === "payload" && rawValue(value)?.label) td.append(el("strong", "", rawValue(value).label));
      td.append(el("div", "cell-preview", value === null ? "NULL" : String(value).slice(0, 180))); tr.append(td);
    }
    const showRow = () => {
      body.querySelectorAll("tr").forEach((r) => r.classList.toggle("selected", r === tr));
      $("row-detail-content").replaceChildren();
      for (const [column, value] of Object.entries(row)) {
        $("row-detail-content").append(el("h3", "", column));
        renderRaw($("row-detail-content"), value);
      }
      if (data.node_refs[row.uri]) $("row-detail-content").prepend(button("지식 그래프에서 보기", async () => { await view("explore"); await select(row.uri); }));
      $("row-detail").open = true;
      $("row-detail").scrollIntoView({block: "nearest"});
    };
    tr.addEventListener("click", showRow);
    tr.addEventListener("keydown", (event) => { if (event.key === "Enter") showRow(); });
    body.append(tr);
  }
  $("raw-table").replaceChildren(table);
  $("row-count").textContent = data.rows.length ? `${fmt(state.rowOffset + 1)}–${fmt(state.rowOffset + data.rows.length)}행${data.count === null ? "" : ` / 전체 ${fmt(data.count)}행`}` : "해당하는 행이 없습니다.";
  $("row-prev").disabled = !state.rowOffset; $("row-next").disabled = !data.has_more;
  $("row-page").textContent = `${Math.floor(state.rowOffset / 50) + 1}페이지`;
}

function renderOverview() {
  const target = $("overview"), metrics = el("div", "status-metrics");
  for (const [value, label] of [[overview.nodes, "지식 항목"], [overview.triples, "RDF 문장"], [overview.types.filter((t) => t.count > 0).length, "저장된 유형"], [overview.pins.length, "해시 확인 자산"]]) {
    const metric = el("div"); metric.append(el("strong", "", fmt(value)), el("span", "", label)); metrics.append(metric);
  }
  target.append(metrics);
  const notice = el("div", "notice");
  notice.append(el("p", "", "지식 탐색은 현재 manifest에 고정된 실행 그래프 전체를 읽습니다. 준비 DB의 후보·원천 행은 별도로 열람합니다."), el("p", "", "원천 지지 등급은 진단 확률이 아닙니다. 표시 이름은 읽기를 위한 표현이며 저장된 URI와 원래 데이터는 유지됩니다."));
  target.append(notice);
  const facts = el("dl", "facts");
  for (const [key, value] of [["수용 상태", overview.status], ["그래프 build", overview.build_id], ["Manifest SHA-256", overview.manifest_sha256], ["읽은 시각", new Date(overview.loaded_at).toLocaleString("ko-KR")]]) facts.append(el("dt", "", key), el("dd", "mono", value));
  target.append(facts);
  function section(title, headers, rows) {
    const section = el("section", "status-section"), table = el("table"), head = el("thead"), tr = el("tr");
    headers.forEach((header) => tr.append(el("th", "", header))); head.append(tr); table.append(head);
    const body = el("tbody");
    rows.forEach((row) => { const tr = el("tr"); row.forEach((value) => { const td = el("td", "break"); if (value instanceof Node) td.append(value); else td.textContent = value; tr.append(td); }); body.append(tr); });
    table.append(body); const scroll = el("div", "table-scroll"); scroll.append(table); section.append(el("h2", "", title), scroll); target.append(section);
  }
  section("유형별 정보", ["유형", "온톨로지 이름", "항목 수"], overview.types.map((type) => [button(type.label, async () => { await view("explore"); await setType(type.id); }, "node-link"), type.id, fmt(type.count)]));
  section("원천·준비 데이터베이스", ["데이터베이스", "크기", "상태"], overview.databases.map((db) => [db.label, db.bytes === null ? "—" : `${(db.bytes / 1024 ** 3).toFixed(2)} GiB`, db.available ? "읽기 전용 열람 가능" : "파일 없음"]));
  section("Manifest 해시 확인", ["자산", "파일", "SHA-256"], overview.pins.map((pin) => [pin.role, pin.path, pin.sha256]));
  target.append(el("p", "muted small", "그래프는 시작 시 로드한 스냅샷입니다. 런타임 지식이 바뀌면 뷰어를 다시 시작하세요. SQLite 행은 조회 시 읽으며 보관 DB를 수정하지 않습니다."));
}

async function init() {
  overview = await api("overview");
  const all = {id: "", label: "전체 유형", count: overview.nodes};
  const priority = ["Disease", "Symptom", "ClinicalPattern", "DiseasePatternAssociation", "ClinicalFeature", "FindingAttribute", "AttributeValue", "ContextFactor", "ExamFinding", "BodySystem", "ExpectedValue"];
  const types = [...overview.types].sort((a, b) => (priority.indexOf(a.id) < 0 ? 99 : priority.indexOf(a.id)) - (priority.indexOf(b.id) < 0 ? 99 : priority.indexOf(b.id)));
  for (const type of [all, ...types]) {
    const node = button("", () => setType(type.id), "type-button"); node.dataset.type = type.id;
    const label = el("span"), dot = el("span", `type-dot ${type.id}`); label.append(dot, document.createTextNode(type.label));
    node.append(label, el("span", "", fmt(type.count))); $("types").append(node);
    if (type.id) option($("type-select"), type.id, `${type.label} (${fmt(type.count)})`);
  }
  overview.databases.forEach((db) => { if (db.available) option($("db-select"), db.id, db.label); });
  document.querySelectorAll(".nav").forEach((node) => node.addEventListener("click", () => run(() => view(node.dataset.view))));
  let debounce;
  $("search").addEventListener("input", () => { clearTimeout(debounce); state.offset = 0; debounce = setTimeout(() => run(search), 180); });
  $("type-select").addEventListener("change", () => run(() => setType($("type-select").value)));
  $("search-prev").addEventListener("click", () => run(() => { state.offset -= 50; return search(); }));
  $("search-next").addEventListener("click", () => run(() => { state.offset += 50; return search(); }));
  $("db-select").addEventListener("change", () => run(() => { state.db = $("db-select").value; return loadTables(); }));
  $("table-select").addEventListener("change", () => run(() => { state.table = $("table-select").value; return chooseTable(); }));
  $("row-search").addEventListener("submit", (event) => { event.preventDefault(); run(() => { state.rowOffset = 0; return loadRows(); }); });
  $("row-reset").addEventListener("click", () => run(() => { $("row-query").value = ""; state.rowOffset = 0; return loadRows(); }));
  $("row-prev").addEventListener("click", () => run(() => { state.rowOffset -= 50; return loadRows(); }));
  $("row-next").addEventListener("click", () => run(() => { state.rowOffset += 50; return loadRows(); }));
  $("close-source").addEventListener("click", () => $("source-dialog").close());
  renderOverview(); await view("explore"); await setType(state.type);
  $("loading").hidden = true;
}

run(init);
