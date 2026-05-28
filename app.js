const API_BASE = "http://127.0.0.1:8001/api";

const tabs = [
  { key: "kp", label: "知识点" },
  { key: "questions", label: "题库" },
  { key: "intake", label: "录题" },
  { key: "practice", label: "练习/错题" },
  { key: "graph", label: "图谱" },
  { key: "dashboard", label: "学情" }
];

const typeFilters = [
  { key: "全部", label: "全部" },
  { key: "公式", label: "公式" },
  { key: "考点", label: "高频考点" },
  { key: "易错", label: "易错提醒" },
  { key: "二级结论", label: "二级结论" },
  { key: "收藏", label: "收藏" }
];

const state = {
  tab: "kp",
  items: [],
  chapters: [],
  questions: [],
  questionTotal: 0,
  patterns: [],
  query: "",
  book: "全部",
  type: "全部",
  activeId: "",
  activeQuestionId: 0,
  activePatternId: 0,
  questionFilters: { kp: "", difficulty: "" },
  favorites: new Set(JSON.parse(localStorage.getItem("mathFavorites") || "[]")),
  message: "",
  error: ""
};

const els = {
  tabs: document.querySelector("#mainTabs"),
  sidebar: document.querySelector("#sidebar"),
  search: document.querySelector("#searchInput"),
  clear: document.querySelector("#clearSearch"),
  results: document.querySelector("#results"),
  reader: document.querySelector("#reader"),
  resultCount: document.querySelector("#resultCount"),
  sectionCount: document.querySelector("#sectionCount"),
  chapterCount: document.querySelector("#chapterCount"),
  bookFilters: document.querySelector("#bookFilters"),
  typeFilters: document.querySelector("#typeFilters"),
  chapterNav: document.querySelector("#chapterNav"),
  workspace: document.querySelector(".workspace"),
  toolbar: document.querySelector(".toolbar"),
  contentGrid: document.querySelector(".content-grid")
};

init();

async function init() {
  parseRoute();
  bindEvents();
  renderTabs();
  await bootstrap();
  await render();
}

async function bootstrap() {
  await loadKnowledgePoints();
  await loadPatterns();
  if (state.tab === "questions") await loadQuestions();
}

function bindEvents() {
  window.addEventListener("hashchange", async () => {
    parseRoute();
    state.message = "";
    state.error = "";
    await render();
  });

  els.search.addEventListener("input", async event => {
    state.query = event.target.value.trim();
    if (state.tab === "questions") await loadQuestions();
    render();
  });

  els.clear.addEventListener("click", async () => {
    state.query = "";
    els.search.value = "";
    if (state.tab === "questions") await loadQuestions();
    render();
    els.search.focus();
  });

  document.addEventListener("keydown", event => {
    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
      event.preventDefault();
      els.search.focus();
    }
  });
}

function parseRoute() {
  const hash = location.hash || "#/kp";
  if (/^#k-/.test(hash)) {
    state.tab = "kp";
    state.activeId = hash.replace("#", "");
    history.replaceState(null, "", `#/kp/${state.activeId}`);
    return;
  }

  const parts = hash.replace(/^#\/?/, "").split("/").filter(Boolean);
  state.tab = tabs.some(tab => tab.key === parts[0]) ? parts[0] : "kp";
  if (state.tab === "kp" && parts[1]) state.activeId = parts[1];
  if (state.tab === "questions" && parts[1]) state.activeQuestionId = Number(parts[1]);
  if (state.tab === "graph" && parts[1]) state.activePatternId = Number(parts[1]);
}

function route(path) {
  location.hash = path;
}

async function api(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options
  });
  if (!response.ok) {
    const body = await response.text();
    throw new Error(body || `HTTP ${response.status}`);
  }
  if (response.status === 204) return null;
  return response.json();
}

async function loadKnowledgePoints() {
  const items = await api("/kp");
  state.items = items.map(item => ({
    ...item,
    content: item.content_md,
    plain: stripMarkdown(`${item.title}\n${item.content_md}`),
    summary: buildSummary(stripMarkdown(`${item.title}\n${item.content_md}`))
  }));
  const seen = new Map();
  for (const item of state.items) {
    if (item.book && item.chapter) {
      seen.set(`${item.book}｜${item.chapter}`, { book: item.book, chapter: item.chapter });
    }
  }
  state.chapters = Array.from(seen.values());
  state.activeId = state.activeId || state.items[0]?.id || "";
}

async function loadQuestions() {
  const params = new URLSearchParams();
  if (state.query) params.set("q", state.query);
  if (state.questionFilters.kp) params.set("kp", state.questionFilters.kp);
  if (state.questionFilters.difficulty) params.set("difficulty", state.questionFilters.difficulty);
  params.set("page_size", "100");
  const data = await api(`/questions?${params}`);
  state.questions = data.items;
  state.questionTotal = data.total;
  state.activeQuestionId = state.activeQuestionId || state.questions[0]?.id || 0;
}

async function loadPatterns() {
  state.patterns = await api("/graph/patterns");
  state.activePatternId = state.activePatternId || state.patterns[0]?.id || 0;
}

async function render() {
  renderTabs();
  if (state.tab === "questions") await loadQuestions();
  if (state.tab === "graph") await loadPatterns();

  if (state.tab === "kp") renderKpView();
  if (state.tab === "questions") renderQuestionsView();
  if (state.tab === "intake") renderIntakeView();
  if (state.tab === "graph") renderGraphView();
  if (state.tab === "practice") renderPlaceholder("练习/错题", "M2 会在这里接入做题、错题集和错因标注。");
  if (state.tab === "dashboard") renderPlaceholder("学情", "M4 会在这里展示个人薄弱 Top、证据链和训练入口。");
}

function renderTabs() {
  els.tabs.innerHTML = tabs.map(tab => `
    <button type="button" class="${state.tab === tab.key ? "active" : ""}" data-tab="${tab.key}">
      ${escapeHtml(tab.label)}
    </button>
  `).join("");
  els.tabs.querySelectorAll("[data-tab]").forEach(button => {
    button.addEventListener("click", () => route(`/${button.dataset.tab}`));
  });
}

function resetShell() {
  els.workspace.innerHTML = `
    <div class="toolbar">
      <div class="segmented" id="typeFilters" aria-label="内容筛选"></div>
      <div class="result-meta"><span id="resultCount"></span></div>
    </div>
    <div class="content-grid">
      <section class="results" id="results" aria-label="搜索结果"></section>
      <article class="reader" id="reader" aria-label="详情"></article>
    </div>
  `;
  els.toolbar = document.querySelector(".toolbar");
  els.contentGrid = document.querySelector(".content-grid");
  els.typeFilters = document.querySelector("#typeFilters");
  els.resultCount = document.querySelector("#resultCount");
  els.results = document.querySelector("#results");
  els.reader = document.querySelector("#reader");
}

function renderKpView() {
  resetShell();
  renderKpSidebar();
  renderKpToolbar();
  const filtered = getFilteredItems();
  if (!filtered.some(item => item.id === state.activeId)) {
    state.activeId = filtered[0]?.id || state.items[0]?.id || "";
  }
  renderKpResults(filtered);
  renderKpReader(state.items.find(item => item.id === state.activeId));
  updateActiveNav();
  els.resultCount.textContent = `${filtered.length} 个结果`;
}

function renderKpSidebar() {
  els.sidebar.innerHTML = `
    <section class="panel summary-panel">
      <div class="stat"><strong id="sectionCount">${state.items.length}</strong><span>知识点</span></div>
      <div class="stat"><strong id="chapterCount">${state.chapters.length}</strong><span>章节</span></div>
    </section>
    <section class="panel"><h2>范围</h2><div class="chip-group" id="bookFilters"></div></section>
    <section class="panel nav-panel"><h2>章节</h2><nav id="chapterNav" class="chapter-nav"></nav></section>
  `;
  els.bookFilters = document.querySelector("#bookFilters");
  els.chapterNav = document.querySelector("#chapterNav");

  const books = ["全部", ...new Set(state.items.map(item => item.book).filter(Boolean))];
  els.bookFilters.innerHTML = books.map(book => `
    <button class="chip ${state.book === book ? "active" : ""}" type="button" data-book="${escapeAttr(book)}">${escapeHtml(book)}</button>
  `).join("");
  els.chapterNav.innerHTML = state.chapters.map(entry => `
    <button class="chapter-link" type="button" data-book="${escapeAttr(entry.book)}" data-chapter="${escapeAttr(entry.chapter)}">
      ${escapeHtml(entry.chapter)}
    </button>
  `).join("");
  els.bookFilters.querySelectorAll("[data-book]").forEach(button => {
    button.addEventListener("click", () => {
      state.book = button.dataset.book;
      renderKpView();
    });
  });
  els.chapterNav.querySelectorAll("[data-chapter]").forEach(button => {
    button.addEventListener("click", () => {
      state.book = button.dataset.book;
      const target = state.items.find(item => item.book === button.dataset.book && item.chapter === button.dataset.chapter);
      if (target) selectKp(target.id);
    });
  });
}

function renderKpToolbar() {
  els.typeFilters.innerHTML = typeFilters.map(filter => `
    <button class="segment ${state.type === filter.key ? "active" : ""}" type="button" data-type="${filter.key}">${filter.label}</button>
  `).join("");
  els.typeFilters.querySelectorAll("[data-type]").forEach(button => {
    button.addEventListener("click", () => {
      state.type = button.dataset.type;
      renderKpView();
    });
  });
}

function getFilteredItems() {
  const query = normalize(state.query);
  return state.items.filter(item => {
    if (state.book !== "全部" && item.book !== state.book) return false;
    if (state.type === "收藏" && !state.favorites.has(item.id)) return false;
    if (!["全部", "收藏"].includes(state.type) && !item.tags.includes(state.type)) return false;
    if (!query) return true;
    return normalize(`${item.book} ${item.chapter} ${item.title} ${item.plain}`).includes(query);
  });
}

function renderKpResults(items) {
  if (!items.length) {
    els.results.innerHTML = `<div class="no-results">没有找到匹配内容，换个关键词试试。</div>`;
    return;
  }
  els.results.innerHTML = items.map(item => `
    <button class="result-card ${item.id === state.activeId ? "active" : ""}" type="button" data-id="${item.id}">
      <h3>${highlight(escapeHtml(item.title))}</h3>
      <span class="path">${escapeHtml([item.book, item.chapter].filter(Boolean).join(" / "))}</span>
      <p class="snippet">${highlight(escapeHtml(getItemSummary(item)))}</p>
      <div class="tags">${renderTags(item.tags)}</div>
    </button>
  `).join("");
  els.results.querySelectorAll("[data-id]").forEach(button => {
    button.addEventListener("click", () => selectKp(button.dataset.id));
  });
}

function renderKpReader(item) {
  if (!item) {
    els.reader.innerHTML = `<div class="empty-state"><strong>没有可显示内容</strong><span>调整筛选条件后继续浏览。</span></div>`;
    return;
  }
  const readerContent = getReaderContent(item);
  const filterLabel = getActiveTypeLabel();
  els.reader.innerHTML = `
    <header class="article-head">
      <span class="path">${escapeHtml([item.book, item.chapter].filter(Boolean).join(" / "))}</span>
      <h2>${escapeHtml(item.title)}</h2>
      <div class="tags">${renderTags(item.tags)}</div>
      ${filterLabel ? `<p class="filter-note">当前只看：${escapeHtml(filterLabel)}</p>` : ""}
      <div class="article-actions">
        <button type="button" data-action="favorite" class="${state.favorites.has(item.id) ? "active" : ""}">
          ${state.favorites.has(item.id) ? "已收藏" : "收藏"}
        </button>
        <button type="button" data-action="copy">复制链接</button>
        <button type="button" data-action="graph">查看图谱</button>
      </div>
    </header>
    <div class="article-body">${renderMarkdown(readerContent)}</div>
  `;
  els.reader.querySelector("[data-action='favorite']").addEventListener("click", () => toggleFavorite(item.id));
  els.reader.querySelector("[data-action='copy']").addEventListener("click", () => copyCurrentLink(item.id));
  els.reader.querySelector("[data-action='graph']").addEventListener("click", () => route("/graph"));
  typeset(els.reader);
}

function selectKp(id) {
  state.activeId = id;
  route(`/kp/${id}`);
}

function getActiveTypeLabel() {
  if (["全部", "收藏"].includes(state.type)) return "";
  return typeFilters.find(filter => filter.key === state.type)?.label || state.type;
}

function getItemSummary(item) {
  const content = getReaderContent(item);
  return buildSummary(stripMarkdown(`${item.title}\n${content}`));
}

function getReaderContent(item) {
  if (["全部", "收藏"].includes(state.type)) return item.content;
  const matched = getMatchingContentBlocks(item.content, state.type);
  if (matched) return matched;
  if (state.type === "公式" && item.tags.includes("公式")) return extractFormulaLines(item.content) || item.content;
  return item.content;
}

function renderQuestionsView() {
  resetShell();
  renderQuestionsSidebar();
  els.typeFilters.innerHTML = `<button class="segment active" type="button">题库</button><button class="segment" type="button" data-new>录入新题</button>`;
  els.typeFilters.querySelector("[data-new]").addEventListener("click", () => route("/intake"));
  els.resultCount.textContent = `${state.questionTotal} 道题`;
  renderQuestionResults();
  const active = state.questions.find(question => question.id === state.activeQuestionId) || state.questions[0];
  state.activeQuestionId = active?.id || 0;
  renderQuestionReader(active);
}

function renderQuestionsSidebar() {
  const kpOptions = state.items.map(item => `<option value="${escapeAttr(item.id)}" ${state.questionFilters.kp === item.id ? "selected" : ""}>${escapeHtml(item.title)}</option>`).join("");
  els.sidebar.innerHTML = `
    <section class="panel summary-panel">
      <div class="stat"><strong>${state.questionTotal}</strong><span>题目</span></div>
      <div class="stat"><strong>${state.patterns.length}</strong><span>题型</span></div>
    </section>
    <section class="panel form-panel">
      <h2>题库筛选</h2>
      <label>知识点<select id="questionKpFilter"><option value="">全部知识点</option>${kpOptions}</select></label>
      <label>难度<select id="difficultyFilter"><option value="">全部难度</option>${[1,2,3,4,5].map(n => `<option value="${n}" ${String(n) === state.questionFilters.difficulty ? "selected" : ""}>${n}</option>`).join("")}</select></label>
    </section>
  `;
  document.querySelector("#questionKpFilter").addEventListener("change", async event => {
    state.questionFilters.kp = event.target.value;
    await loadQuestions();
    renderQuestionsView();
  });
  document.querySelector("#difficultyFilter").addEventListener("change", async event => {
    state.questionFilters.difficulty = event.target.value;
    await loadQuestions();
    renderQuestionsView();
  });
}

function renderQuestionResults() {
  if (!state.questions.length) {
    els.results.innerHTML = `<div class="no-results">还没有题目，先到录题页添加 5-10 道真题。</div>`;
    return;
  }
  els.results.innerHTML = state.questions.map(question => `
    <button class="result-card ${question.id === state.activeQuestionId ? "active" : ""}" type="button" data-id="${question.id}">
      <h3>${escapeHtml(question.source || `题目 #${question.id}`)}</h3>
      <span class="path">${escapeHtml([question.format_name, question.difficulty ? `难度 ${question.difficulty}` : ""].filter(Boolean).join(" / "))}</span>
      <p class="snippet">${highlight(escapeHtml(buildSummary(stripMarkdown(question.stem_md))))}</p>
      <div class="tags">${renderTags([...question.tags, ...question.knowledge_points.slice(0, 2).map(kp => kp.title)])}</div>
    </button>
  `).join("");
  els.results.querySelectorAll("[data-id]").forEach(button => {
    button.addEventListener("click", () => {
      state.activeQuestionId = Number(button.dataset.id);
      route(`/questions/${button.dataset.id}`);
    });
  });
}

function renderQuestionReader(question) {
  if (!question) {
    els.reader.innerHTML = `<div class="empty-state"><strong>题库为空</strong><span>从录题页添加第一道真题。</span></div>`;
    return;
  }
  els.reader.innerHTML = `
    <header class="article-head">
      <span class="path">${escapeHtml([question.format_name, question.difficulty ? `难度 ${question.difficulty}` : "", question.source].filter(Boolean).join(" / "))}</span>
      <h2>${escapeHtml(question.source || `题目 #${question.id}`)}</h2>
      <div class="tags">${renderTags([...question.tags, ...question.patterns.map(p => p.name), ...question.skills.map(s => s.name), ...question.pitfalls.map(p => p.name)])}</div>
    </header>
    <div class="article-body">
      <h4>题干</h4>
      ${renderMarkdown(question.stem_md)}
      ${question.answer_md ? `<h4>答案</h4>${renderMarkdown(question.answer_md)}` : ""}
      ${question.solution_md ? `<h4>解析</h4>${renderMarkdown(question.solution_md)}` : ""}
      <h4>关联知识点</h4>
      <ul>${question.knowledge_points.map(kp => `<li>${escapeHtml(kp.title)}</li>`).join("") || "<li>未关联</li>"}</ul>
    </div>
  `;
  typeset(els.reader);
}

function renderIntakeView() {
  els.sidebar.innerHTML = `
    <section class="panel summary-panel">
      <div class="stat"><strong>${state.items.length}</strong><span>知识点</span></div>
      <div class="stat"><strong>${state.patterns.length}</strong><span>已建题型</span></div>
    </section>
    <section class="panel"><h2>状态</h2><div class="side-note">${escapeHtml(state.message || state.error || "手动录题会同时建立题目与图谱边。")}</div></section>
  `;
  els.workspace.innerHTML = `
    <div class="form-surface">
      <form id="questionForm" class="question-form">
        <div class="form-grid">
          <label>来源<input name="source" placeholder="2024 春季月考第3题"></label>
          <label>题目形式<select name="format_id"><option value="1">选择</option><option value="2">填空</option><option value="3">解答</option><option value="4">证明</option><option value="5">作图</option></select></label>
          <label>难度<select name="difficulty"><option value="">未定</option>${[1,2,3,4,5].map(n => `<option value="${n}">${n}</option>`).join("")}</select></label>
        </div>
        <label>题干<textarea name="stem_md" rows="6" required placeholder="支持 Markdown + LaTeX"></textarea></label>
        <label>标准答案<textarea name="answer_md" rows="3"></textarea></label>
        <label>解析<textarea name="solution_md" rows="5"></textarea></label>
        <label>关联知识点<select name="kp_ids" multiple size="8">${state.items.map(item => `<option value="${escapeAttr(item.id)}">${escapeHtml(item.title)}</option>`).join("")}</select></label>
        <div class="form-grid">
          <label>题型<input name="patterns_text" placeholder="多个用逗号分隔"></label>
          <label>技巧<input name="skills_text" placeholder="多个用逗号分隔"></label>
          <label>易错点<input name="pitfalls_text" placeholder="多个用逗号分隔"></label>
        </div>
        <label>标签<input name="tags_text" placeholder="易错型, 定义域陷阱"></label>
        <div class="article-actions">
          <button type="submit">保存题目</button>
          <button type="button" id="docxPreview">导入示例 DOCX 预览</button>
        </div>
      </form>
      <section class="preview-panel" id="intakePreview"></section>
    </div>
  `;
  document.querySelector("#questionForm").addEventListener("submit", submitQuestionForm);
  document.querySelector("#docxPreview").addEventListener("click", previewDocxImport);
}

async function submitQuestionForm(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const data = new FormData(form);
  const payload = {
    source: data.get("source") || null,
    format_id: data.get("format_id") ? Number(data.get("format_id")) : null,
    difficulty: data.get("difficulty") ? Number(data.get("difficulty")) : null,
    stem_md: data.get("stem_md"),
    answer_md: data.get("answer_md") || null,
    solution_md: data.get("solution_md") || null,
    kp_ids: [...form.elements.kp_ids.selectedOptions].map((option, index) => ({ id: option.value, weight: index === 0 ? 1 : 0.75, is_primary: index === 0 })),
    patterns: splitNodes(data.get("patterns_text"), true),
    skills: splitNodes(data.get("skills_text")),
    pitfalls: splitNodes(data.get("pitfalls_text")),
    tags: splitText(data.get("tags_text"))
  };
  try {
    const created = await api("/questions", { method: "POST", body: JSON.stringify(payload) });
    state.message = `已保存题目 #${created.id}`;
    state.error = "";
    state.activeQuestionId = created.id;
    await loadQuestions();
    route(`/questions/${created.id}`);
  } catch (error) {
    state.error = `保存失败：${error.message}`;
    renderIntakeView();
  }
}

async function previewDocxImport() {
  const preview = document.querySelector("#intakePreview");
  preview.innerHTML = `<div class="empty-state"><strong>正在抽取 DOCX...</strong></div>`;
  try {
    const data = await api("/intake/import/docx", { method: "POST", body: JSON.stringify({}) });
    preview.innerHTML = `
      <h2>DOCX 预览</h2>
      <p class="snippet">段落 ${data.paragraph_count} · 题型 ${data.type_count} · 题目 ${data.question_count}</p>
      <div class="preview-grid">
        ${data.patterns.map(pattern => `<article><strong>${escapeHtml(pattern.name)}</strong><span>${escapeHtml(pattern.expected_kp)}</span><p>${escapeHtml((pattern.notes || []).slice(0, 2).join(" "))}</p></article>`).join("")}
      </div>
      <h3>前 6 道题</h3>
      ${data.questions.slice(0, 6).map(question => `<details><summary>${escapeHtml(question.source)}</summary><pre>${escapeHtml(question.stem)}</pre></details>`).join("")}
    `;
  } catch (error) {
    preview.innerHTML = `<div class="no-results">DOCX 预览失败：${escapeHtml(error.message)}</div>`;
  }
}

function renderGraphView() {
  resetShell();
  els.sidebar.innerHTML = `
    <section class="panel summary-panel"><div class="stat"><strong>${state.patterns.length}</strong><span>题型</span></div><div class="stat"><strong>${state.items.length}</strong><span>知识点</span></div></section>
    <section class="panel"><h2>新增题型</h2><form id="patternForm" class="mini-form"><input name="name" placeholder="题型名称" required><textarea name="strategy_md" rows="4" placeholder="解题策略"></textarea><button type="submit">保存题型</button></form></section>
  `;
  els.typeFilters.innerHTML = `<button class="segment active" type="button">局部图谱</button>`;
  els.resultCount.textContent = `${state.patterns.length} 个题型`;
  els.results.innerHTML = state.patterns.map(pattern => `
    <button class="result-card ${pattern.id === state.activePatternId ? "active" : ""}" type="button" data-id="${pattern.id}">
      <h3>${escapeHtml(pattern.name)}</h3>
      <p class="snippet">${escapeHtml(buildSummary(stripMarkdown(pattern.strategy_md || "暂未记录策略。")))}</p>
    </button>
  `).join("") || `<div class="no-results">还没有题型。录题时输入题型会自动创建。</div>`;
  els.results.querySelectorAll("[data-id]").forEach(button => {
    button.addEventListener("click", () => {
      state.activePatternId = Number(button.dataset.id);
      route(`/graph/${button.dataset.id}`);
    });
  });
  const pattern = state.patterns.find(item => item.id === state.activePatternId) || state.patterns[0];
  renderPatternReader(pattern);
  document.querySelector("#patternForm").addEventListener("submit", submitPatternForm);
}

async function submitPatternForm(event) {
  event.preventDefault();
  const data = new FormData(event.currentTarget);
  const created = await api("/graph/patterns", {
    method: "POST",
    body: JSON.stringify({ name: data.get("name"), strategy_md: data.get("strategy_md"), source: "manual" })
  });
  state.activePatternId = created.id;
  await loadPatterns();
  route(`/graph/${created.id}`);
}

function renderPatternReader(pattern) {
  if (!pattern) {
    els.reader.innerHTML = `<div class="empty-state"><strong>暂无图谱节点</strong><span>录题时可自动创建题型、技巧和易错点。</span></div>`;
    return;
  }
  els.reader.innerHTML = `
    <header class="article-head"><span class="path">${escapeHtml(pattern.source || "manual")}</span><h2>${escapeHtml(pattern.name)}</h2></header>
    <div class="article-body">
      ${pattern.strategy_md ? renderMarkdown(pattern.strategy_md) : "<p>暂未记录策略。</p>"}
      <h4>关联知识点</h4><ul>${pattern.knowledge_points.map(kp => `<li>${escapeHtml(kp.title)}</li>`).join("") || "<li>暂无</li>"}</ul>
      <h4>技巧</h4><ul>${pattern.skills.map(node => `<li>${escapeHtml(node.name)}</li>`).join("") || "<li>暂无</li>"}</ul>
      <h4>通用易错点</h4><ul>${pattern.pitfalls.map(node => `<li>${escapeHtml(node.name)}</li>`).join("") || "<li>暂无</li>"}</ul>
    </div>
  `;
}

function renderPlaceholder(title, text) {
  els.sidebar.innerHTML = `<section class="panel"><h2>${escapeHtml(title)}</h2><div class="side-note">${escapeHtml(text)}</div></section>`;
  els.workspace.innerHTML = `<article class="reader"><div class="empty-state"><strong>${escapeHtml(title)}</strong><span>${escapeHtml(text)}</span></div></article>`;
}

function getMatchingContentBlocks(content, type) {
  const blocks = splitContentBlocks(content);
  const selected = blocks.filter(block => blockMatchesType(block, type));
  if (!selected.length) return "";
  return selected.map(block => block.raw).join("\n\n");
}

function splitContentBlocks(content) {
  const lines = content.split("\n");
  const blocks = [];
  let current = null;
  for (const line of lines) {
    const heading = line.match(/^####\s+(.+)$/);
    if (heading) {
      if (current) blocks.push(current);
      current = { heading: heading[1].trim(), lines: [line] };
      continue;
    }
    if (!current) current = { heading: "", lines: [] };
    current.lines.push(line);
  }
  if (current) blocks.push(current);
  return blocks.map(block => ({ ...block, raw: block.lines.join("\n").trim() })).filter(block => block.raw);
}

function blockMatchesType(block, type) {
  const text = `${block.heading}\n${block.raw}`;
  if (type === "考点") return /高频考点|典型题型|常用思路/.test(text);
  if (type === "易错") return /易错提醒|易错点/.test(text);
  if (type === "二级结论") return /二级结论/.test(text);
  if (type === "公式") return /\$\$|公式|定理|恒等式|运算律|坐标公式|面积公式|体积|表面积|半径/.test(text);
  return true;
}

function extractFormulaLines(content) {
  const lines = content.split("\n");
  const chunks = [];
  let currentHeading = "";
  for (let i = 0; i < lines.length; i += 1) {
    const heading = lines[i].match(/^####\s+(.+)$/);
    if (heading) {
      currentHeading = lines[i];
      continue;
    }
    if (lines[i].trim() === "$$") {
      const math = [];
      i += 1;
      while (i < lines.length && lines[i].trim() !== "$$") {
        math.push(lines[i]);
        i += 1;
      }
      chunks.push([currentHeading, "$$", ...math, "$$"].filter(Boolean).join("\n"));
    }
  }
  return chunks.join("\n\n");
}

function renderMarkdown(markdown = "") {
  const lines = markdown.split("\n");
  const html = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (!line.trim()) { i += 1; continue; }
    if (line.trim() === "---") { html.push("<hr>"); i += 1; continue; }
    if (line.trim() === "$$") {
      const math = [];
      i += 1;
      while (i < lines.length && lines[i].trim() !== "$$") { math.push(lines[i]); i += 1; }
      i += 1;
      html.push(`<div class="math-block">$$${escapeHtml(math.join("\n"))}$$</div>`);
      continue;
    }
    if (/^####\s+/.test(line)) { html.push(`<h4>${formatInline(line.replace(/^####\s+/, ""))}</h4>`); i += 1; continue; }
    if (isTableStart(lines, i)) {
      const table = [];
      while (i < lines.length && /^\s*\|.*\|\s*$/.test(lines[i])) { table.push(lines[i]); i += 1; }
      html.push(renderTable(table));
      continue;
    }
    if (/^\s*-\s+/.test(line)) {
      const list = [];
      while (i < lines.length && /^\s*-\s+/.test(lines[i])) { list.push(lines[i].replace(/^\s*-\s+/, "")); i += 1; }
      html.push(`<ul>${list.map(text => `<li>${formatInline(text)}</li>`).join("")}</ul>`);
      continue;
    }
    if (/^\s*\d+\.\s+/.test(line)) {
      const list = [];
      while (i < lines.length && /^\s*\d+\.\s+/.test(lines[i])) { list.push(lines[i].replace(/^\s*\d+\.\s+/, "")); i += 1; }
      html.push(`<ol>${list.map(text => `<li>${formatInline(text)}</li>`).join("")}</ol>`);
      continue;
    }
    const paragraph = [line];
    i += 1;
    while (i < lines.length && lines[i].trim() && !isBlockStart(lines, i)) { paragraph.push(lines[i]); i += 1; }
    html.push(`<p>${formatInline(paragraph.join(" "))}</p>`);
  }
  return html.join("");
}

function isBlockStart(lines, index) {
  const line = lines[index] || "";
  return /^####\s+/.test(line) || line.trim() === "---" || line.trim() === "$$" || /^\s*-\s+/.test(line) || /^\s*\d+\.\s+/.test(line) || isTableStart(lines, index);
}

function isTableStart(lines, index) {
  return /^\s*\|.*\|\s*$/.test(lines[index] || "") && /^\s*\|?\s*:?-{3,}:?\s*\|/.test(lines[index + 1] || "");
}

function renderTable(rows) {
  const cells = rows.map(row => row.trim().replace(/^\||\|$/g, "").split("|").map(cell => cell.trim()));
  const head = cells[0] || [];
  const body = cells.slice(2);
  return `<table><thead><tr>${head.map(cell => `<th>${formatInline(cell)}</th>`).join("")}</tr></thead><tbody>${body.map(row => `<tr>${row.map(cell => `<td>${formatInline(cell)}</td>`).join("")}</tr>`).join("")}</tbody></table>`;
}

function toggleFavorite(id) {
  if (state.favorites.has(id)) state.favorites.delete(id);
  else state.favorites.add(id);
  localStorage.setItem("mathFavorites", JSON.stringify([...state.favorites]));
  renderKpView();
}

async function copyCurrentLink(id) {
  const url = `${location.origin}${location.pathname}#/kp/${id}`;
  try {
    await navigator.clipboard.writeText(url);
  } catch {
    prompt("复制此链接：", url);
  }
}

function updateActiveNav() {
  const active = state.items.find(item => item.id === state.activeId);
  document.querySelectorAll("[data-chapter]").forEach(button => {
    button.classList.toggle("active", Boolean(active && button.dataset.book === active.book && button.dataset.chapter === active.chapter));
  });
}

function splitText(value) {
  return String(value || "").replace("，", ",").split(",").map(item => item.trim()).filter(Boolean);
}

function splitNodes(value, primaryFirst = false) {
  return splitText(value).map((name, index) => ({ name, weight: index === 0 ? 1 : 0.75, is_primary: primaryFirst && index === 0 }));
}

function renderTags(tags) {
  return [...new Set(tags.filter(Boolean))].map(tag => {
    const className = tag === "考点" ? "hot" : tag === "易错" || /错/.test(tag) ? "warn" : tag === "公式" ? "formula" : "deep";
    return `<span class="tag ${className}">${escapeHtml(tag)}</span>`;
  }).join("");
}

function formatInline(text) {
  return escapeHtml(text).replace(/`([^`]+)`/g, "<code>$1</code>").replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
}

function highlight(text) {
  if (!state.query) return text;
  return text.replace(new RegExp(`(${escapeRegExp(state.query)})`, "gi"), "<mark>$1</mark>");
}

function buildSummary(text) {
  return text.replace(/\s+/g, " ").trim().slice(0, 118) || "点击查看完整内容。";
}

function stripMarkdown(text) {
  return String(text || "").replace(/```[\s\S]*?```/g, " ").replace(/\$\$([\s\S]*?)\$\$/g, " $1 ").replace(/[#>*_|`[\](){}\\]/g, " ").replace(/\s+/g, " ").trim();
}

function normalize(text) {
  return String(text || "").toLowerCase().replace(/\s+/g, "");
}

function escapeHtml(value) {
  return String(value ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#039;");
}

function escapeAttr(value) {
  return escapeHtml(value);
}

function escapeRegExp(value) {
  return String(value).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function typeset(target) {
  if (window.MathJax?.typesetPromise) window.MathJax.typesetPromise([target]).catch(console.error);
}
