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
  mistakes: [],
  dashboard: {
    weakTop: [],
    heatmap: [],
    typeRadar: [],
    pitfalls: [],
    trend: [],
    detail: null
  },
  includeMastered: false,
  query: "",
  book: "全部",
  type: "全部",
  activeId: "",
  activeQuestionId: 0,
  activePracticeQuestionId: 0,
  activeWeaknessId: 0,
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
  if (state.tab === "practice") {
    await loadQuestions();
    await loadMistakes();
  }
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
  if (state.tab === "practice" && parts[1]) state.activePracticeQuestionId = Number(parts[1]);
  if (state.tab === "dashboard" && parts[1]) state.activeWeaknessId = Number(parts[1]);
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

async function loadMistakes() {
  const data = await api(`/mistakes?include_mastered=${state.includeMastered ? "true" : "false"}`);
  state.mistakes = data.items;
}

async function loadDashboard() {
  const [weakTop, heatmapData, typeRadarData, pitfalls, trendData] = await Promise.all([
    api("/stats/weak_top?limit=10"),
    api("/stats/heatmap"),
    api("/stats/type_radar?limit=12"),
    api("/stats/personal_pitfalls?limit=10"),
    api("/stats/trend?period=week")
  ]);
  state.dashboard.weakTop = weakTop;
  state.dashboard.heatmap = heatmapData;
  state.dashboard.typeRadar = typeRadarData;
  state.dashboard.pitfalls = pitfalls;
  state.dashboard.trend = trendData;
  if (!state.activeWeaknessId && weakTop[0]) state.activeWeaknessId = weakTop[0].id;
  try {
    state.dashboard.detail = state.activeWeaknessId
      ? await api(`/stats/weaknesses/${state.activeWeaknessId}`)
      : null;
  } catch {
    state.activeWeaknessId = weakTop[0]?.id || 0;
    state.dashboard.detail = state.activeWeaknessId
      ? await api(`/stats/weaknesses/${state.activeWeaknessId}`)
      : null;
  }
}

async function render() {
  renderTabs();
  if (state.tab === "questions") await loadQuestions();
  if (state.tab === "practice") {
    await loadQuestions();
    await loadMistakes();
  }
  if (state.tab === "graph") await loadPatterns();
  if (state.tab === "dashboard") await loadDashboard();

  if (state.tab === "kp") renderKpView();
  if (state.tab === "questions") renderQuestionsView();
  if (state.tab === "intake") renderIntakeView();
  if (state.tab === "graph") renderGraphView();
  if (state.tab === "practice") renderPracticeView();
  if (state.tab === "dashboard") renderDashboardView();
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
  keepActiveKpContextVisible();
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
  els.results.innerHTML = state.questions.map(question => {
    const display = questionDisplay(question);
    return `
      <button class="result-card ${question.id === state.activeQuestionId ? "active" : ""}" type="button" data-id="${question.id}" title="${escapeAttr(display.fullSource)}">
        <h3>${highlight(escapeHtml(display.title))}</h3>
        <span class="path">${escapeHtml(questionMetaPath(question, display))}</span>
        <p class="snippet">${highlight(escapeHtml(buildSummary(stripMarkdown(question.stem_md))))}</p>
        <div class="tags">${renderTags([...question.tags, ...question.knowledge_points.slice(0, 2).map(kp => kp.title)])}</div>
      </button>
    `;
  }).join("");
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
  const display = questionDisplay(question);
  const usedImages = questionRichContent(question);
  els.reader.innerHTML = `
    <header class="article-head">
      <span class="path">${escapeHtml(questionMetaPath(question, display))}</span>
      <h2>${escapeHtml(display.title)}</h2>
      <div class="tags">${renderTags([...question.tags, ...question.patterns.map(p => p.name), ...question.skills.map(s => s.name), ...question.pitfalls.map(p => p.name)])}</div>
    </header>
    <div class="article-body">
      <h4>题干</h4>
      ${renderMarkdown(question.stem_md)}
      ${renderQuestionImages(question.image_path, usedImages)}
      ${question.answer_md ? `<h4>答案</h4>${renderMarkdown(question.answer_md)}` : ""}
      ${question.solution_md ? `<h4>解析</h4>${renderMarkdown(question.solution_md)}` : ""}
      <h4>关联知识点</h4>
      <ul>${question.knowledge_points.map(kp => `<li>${escapeHtml(kp.title)}</li>`).join("") || "<li>未关联</li>"}</ul>
    </div>
  `;
  typeset(els.reader);
}

function renderPracticeView() {
  resetShell();
  renderPracticeSidebar();
  els.typeFilters.innerHTML = `<button class="segment active" type="button">做题</button><button class="segment" type="button" data-mistakes>错题集</button>`;
  els.typeFilters.querySelector("[data-mistakes]").addEventListener("click", () => {
    document.querySelector("#mistakeList")?.scrollIntoView({ behavior: "smooth", block: "start" });
  });
  els.resultCount.textContent = `${state.questions.length} 道可练习题 · ${state.mistakes.length} 条错题`;
  renderPracticeQuestionList();
  const active = state.questions.find(question => question.id === state.activePracticeQuestionId) || state.questions[0];
  state.activePracticeQuestionId = active?.id || 0;
  renderPracticeReader(active);
}

function renderPracticeSidebar() {
  els.sidebar.innerHTML = `
    <section class="panel summary-panel">
      <div class="stat"><strong>${state.questions.length}</strong><span>题库</span></div>
      <div class="stat"><strong>${state.mistakes.length}</strong><span>${state.includeMastered ? "全部错题" : "未掌握"}</span></div>
    </section>
    <section class="panel">
      <h2>错题显示</h2>
      <div class="chip-group">
        <button class="chip ${!state.includeMastered ? "active" : ""}" type="button" data-mastered="0">未掌握</button>
        <button class="chip ${state.includeMastered ? "active" : ""}" type="button" data-mastered="1">含已掌握</button>
      </div>
    </section>
    <section class="panel" id="mistakeList">
      <h2>错题集</h2>
      <div class="mistake-list">
        ${state.mistakes.map(renderMistakeSummary).join("") || `<div class="side-note">暂无错题。</div>`}
      </div>
    </section>
  `;
  els.sidebar.querySelectorAll("[data-mastered]").forEach(button => {
    button.addEventListener("click", async () => {
      state.includeMastered = button.dataset.mastered === "1";
      await loadMistakes();
      renderPracticeView();
    });
  });
  els.sidebar.querySelectorAll("[data-practice-question]").forEach(button => {
    button.addEventListener("click", () => {
      state.activePracticeQuestionId = Number(button.dataset.practiceQuestion);
      route(`/practice/${state.activePracticeQuestionId}`);
    });
  });
  els.sidebar.querySelectorAll("[data-master-question]").forEach(button => {
    button.addEventListener("click", async () => {
      await api(`/mistakes/${button.dataset.masterQuestion}`, {
        method: "PATCH",
        body: JSON.stringify({ mastered: true })
      });
      state.message = "已标记掌握";
      await loadMistakes();
      renderPracticeView();
    });
  });
}

function renderMistakeSummary(mistake) {
  return `
    <div class="mistake-row">
      <button type="button" data-practice-question="${mistake.question.id}">
        ${escapeHtml(questionDisplay(mistake.question).title)}
      </button>
      <span>错 ${mistake.wrong_count} 次 · 连对 ${mistake.mastered_streak}</span>
      ${mistake.mastered_at ? `<span>已掌握</span>` : `<button type="button" data-master-question="${mistake.question.id}">标掌握</button>`}
    </div>
  `;
}

function renderPracticeQuestionList() {
  if (!state.questions.length) {
    els.results.innerHTML = `<div class="no-results">题库为空。先到录题页添加题目。</div>`;
    return;
  }
  els.results.innerHTML = state.questions.map(question => {
    const display = questionDisplay(question);
    return `
      <button class="result-card ${question.id === state.activePracticeQuestionId ? "active" : ""}" type="button" data-id="${question.id}" title="${escapeAttr(display.fullSource)}">
        <h3>${escapeHtml(display.title)}</h3>
        <span class="path">${escapeHtml(questionMetaPath(question, display))}</span>
        <p class="snippet">${escapeHtml(buildSummary(stripMarkdown(question.stem_md)))}</p>
        <div class="tags">${renderTags([...question.knowledge_points.slice(0, 2).map(kp => kp.title), ...question.patterns.slice(0, 2).map(pattern => pattern.name)])}</div>
      </button>
    `;
  }).join("");
  els.results.querySelectorAll("[data-id]").forEach(button => {
    button.addEventListener("click", () => {
      state.activePracticeQuestionId = Number(button.dataset.id);
      route(`/practice/${button.dataset.id}`);
    });
  });
}

function renderPracticeReader(question) {
  if (!question) {
    els.reader.innerHTML = `<div class="empty-state"><strong>暂无练习题</strong><span>先从录题页添加题目。</span></div>`;
    return;
  }
  const display = questionDisplay(question);
  const usedImages = questionRichContent(question);
  els.reader.innerHTML = `
    <header class="article-head">
      <span class="path">${escapeHtml(questionMetaPath(question, display))}</span>
      <h2>${escapeHtml(display.title)}</h2>
      <div class="tags">${renderTags([...question.knowledge_points.map(kp => kp.title), ...question.patterns.map(pattern => pattern.name)])}</div>
      ${state.message ? `<p class="filter-note">${escapeHtml(state.message)}</p>` : ""}
      ${state.error ? `<p class="filter-note">${escapeHtml(state.error)}</p>` : ""}
    </header>
    <div class="article-body">
      <h4>题干</h4>
      ${renderMarkdown(question.stem_md)}
      ${renderQuestionImages(question.image_path, usedImages)}
      <form id="attemptForm" class="question-form compact-form">
        <label>我的作答<textarea name="user_answer_md" rows="4"></textarea></label>
        <div class="form-grid">
          <label>结果<select name="is_correct"><option value="0">错</option><option value="1">对</option></select></label>
          <label>自评<select name="self_rating"><option value="">未评</option>${[1,2,3,4,5].map(n => `<option value="${n}">${n}</option>`).join("")}</select></label>
          <label>用时（秒）<input name="time_spent_sec" type="number" min="0" step="1"></label>
        </div>
        <fieldset class="diagnosis-fieldset">
          <legend>我错在...</legend>
          ${renderDiagnosisChecks(question)}
          <label>自定义错因<input name="custom_label" placeholder="例如：忽略非零条件"></label>
        </fieldset>
        <div class="article-actions">
          <button type="submit">提交作答</button>
        </div>
      </form>
      ${(question.answer_md || question.solution_md) ? `<h4>答案与解析</h4>${question.answer_md ? renderMarkdown(question.answer_md) : ""}${question.solution_md ? renderMarkdown(question.solution_md) : ""}` : ""}
    </div>
  `;
  document.querySelector("#attemptForm").addEventListener("submit", event => submitAttempt(event, question));
  typeset(els.reader);
}

function renderDiagnosisChecks(question) {
  const groups = [
    ["kp", "知识点", question.knowledge_points],
    ["pattern", "题型", question.patterns],
    ["skill", "技巧", question.skills],
    ["pitfall", "易错点", question.pitfalls]
  ];
  return groups.map(([type, label, nodes]) => `
    <div class="diagnosis-group">
      <strong>${label}</strong>
      ${nodes.map(node => `<label><input type="checkbox" name="diagnosis" value="${type}:${node.id}"> ${escapeHtml(node.title || node.name)}</label>`).join("") || `<span>暂无</span>`}
    </div>
  `).join("");
}

async function submitAttempt(event, question) {
  event.preventDefault();
  const form = event.currentTarget;
  const data = new FormData(form);
  const isCorrect = data.get("is_correct") === "1";
  const diagnoses = [...form.querySelectorAll("input[name='diagnosis']:checked")].map(input => {
    const [target_type, target_id] = input.value.split(":");
    return { target_type, target_id: target_type === "kp" ? target_id : Number(target_id), source: "manual" };
  });
  const customLabel = String(data.get("custom_label") || "").trim();
  if (!isCorrect && customLabel) diagnoses.push({ target_type: "custom", custom_label: customLabel, source: "manual" });
  const payload = {
    question_id: question.id,
    is_correct: isCorrect,
    self_rating: data.get("self_rating") ? Number(data.get("self_rating")) : null,
    time_spent_sec: data.get("time_spent_sec") ? Number(data.get("time_spent_sec")) : null,
    user_answer_md: data.get("user_answer_md") || null,
    diagnoses
  };
  try {
    const attempt = await api("/attempts", { method: "POST", body: JSON.stringify(payload) });
    state.message = isCorrect ? `已记录正确作答 #${attempt.id}` : `已加入错题集 #${attempt.id}`;
    state.error = "";
    await loadMistakes();
    renderPracticeView();
  } catch (error) {
    state.error = `提交失败：${error.message}`;
    renderPracticeView();
  }
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
      <section class="upload-panel">
        <h2>批量录题 / 错题沉淀</h2>
        <form id="uploadForm" class="question-form compact-form">
          <div class="form-grid">
            <label>文件<input name="file" type="file" accept=".pdf,.png,.jpg,.jpeg,.webp,.docx" required></label>
            <label>解析目标<select name="schema_name"><option value="mistake">错题沉淀</option><option value="question">新题入库</option></select></label>
            <label>关联知识点<select name="kp_id"><option value="">不关联</option>${state.items.map(item => `<option value="${escapeAttr(item.id)}">${escapeHtml(item.title)}</option>`).join("")}</select></label>
          </div>
          <div class="article-actions">
            <button type="submit">上传并预览</button>
          </div>
        </form>
        <div id="uploadPreview" class="preview-panel"></div>
      </section>
      <section class="preview-panel" id="intakePreview"></section>
    </div>
  `;
  document.querySelector("#questionForm").addEventListener("submit", submitQuestionForm);
  document.querySelector("#uploadForm").addEventListener("submit", uploadIntakeFile);
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

async function uploadIntakeFile(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const preview = document.querySelector("#uploadPreview");
  const data = new FormData(form);
  preview.innerHTML = `<div class="empty-state"><strong>正在上传并生成 manual 预览...</strong></div>`;
  try {
    const uploadResponse = await fetch(`${API_BASE}/intake/upload`, { method: "POST", body: data });
    if (!uploadResponse.ok) throw new Error(await uploadResponse.text());
    const upload = await uploadResponse.json();
    const parsed = await api("/intake/parse", {
      method: "POST",
      body: JSON.stringify({ upload_id: upload.upload_id, schema_name: data.get("schema_name") })
    });
    renderUploadPreview(preview, upload, parsed, data.get("kp_id"));
  } catch (error) {
    preview.innerHTML = `<div class="no-results">上传失败：${escapeHtml(error.message)}</div>`;
  }
}

function renderUploadPreview(container, upload, parsed, kpId) {
  const pageHtml = parsed.pages.map(path => {
    const url = path.startsWith("/") ? path : `/${path}`;
    if (/\.(png|jpg|jpeg|webp)$/i.test(path)) return `<img class="page-preview" src="${escapeAttr(url)}" alt="上传预览">`;
    return `<p class="snippet">${escapeHtml(path)}</p>`;
  }).join("");
  container.innerHTML = `
    <h2>${escapeHtml(upload.filename)} · ${escapeHtml(upload.detected_kind)} · ${escapeHtml(parsed.provider)}</h2>
    <div class="preview-pages">${pageHtml || `<p class="snippet">已上传，暂无可渲染页。</p>`}</div>
    <form id="mistakeCommitForm" class="question-form compact-form">
      <label>题干<textarea name="stem_md" rows="5" required placeholder="manual provider 不自动识别，请对照左侧图片手输"></textarea></label>
      <label>我的作答<textarea name="user_answer_md" rows="3"></textarea></label>
      <label>标准答案<textarea name="answer_md" rows="3"></textarea></label>
      <label>解析<textarea name="solution_md" rows="4"></textarea></label>
      <input type="hidden" name="kp_id" value="${escapeAttr(kpId || "")}">
      <input type="hidden" name="answer_image_path" value="${escapeAttr(parsed.pages[0] || "")}">
      <div class="article-actions">
        <button type="submit">作为错题沉淀</button>
      </div>
    </form>
  `;
  document.querySelector("#mistakeCommitForm").addEventListener("submit", commitUploadedMistake);
}

async function commitUploadedMistake(event) {
  event.preventDefault();
  const data = new FormData(event.currentTarget);
  const kpId = data.get("kp_id");
  const payload = [{
    question: {
      source: "photo_intake",
      stem_md: data.get("stem_md"),
      answer_md: data.get("answer_md") || null,
      solution_md: data.get("solution_md") || null,
      image_path: data.get("answer_image_path") || null,
      kp_ids: kpId ? [{ id: kpId, weight: 1, is_primary: true }] : []
    },
    user_answer_md: data.get("user_answer_md") || null,
    answer_image_path: data.get("answer_image_path") || null,
    is_correct: false,
    mistake_hints: kpId ? [{ target_type: "kp", target_id: kpId, source: "manual" }] : []
  }];
  const preview = document.querySelector("#uploadPreview");
  try {
    const result = await api("/intake/mistakes/commit", { method: "POST", body: JSON.stringify(payload) });
    const hits = (result.matched_weaknesses || []).map((w) => w.title).filter(Boolean);
    const hitNote = hits.length ? `。命中个人薄弱点：${escapeHtml(hits.join(" / "))}` : "";
    preview.insertAdjacentHTML("beforeend", `<p class="filter-note">已沉淀 ${result.committed_n} 题${hitNote}（attempt #${escapeHtml(result.attempt_ids.join(", "))}）</p>`);
    await loadQuestions();
    await loadMistakes();
  } catch (error) {
    preview.insertAdjacentHTML("beforeend", `<p class="filter-note">提交失败：${escapeHtml(error.message)}</p>`);
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

function renderDashboardView() {
  renderDashboardSidebar();
  const detail = state.dashboard.detail;
  const topWeakness = state.dashboard.weakTop[0];
  els.workspace.innerHTML = `
    <div class="toolbar">
      <div class="segmented" aria-label="学情视图">
        <button class="segment active" type="button">个人薄弱图谱</button>
      </div>
      <div class="result-meta">${state.dashboard.weakTop.length} 个薄弱点 · 最近 7 天 ${sumTrend("wrong_count")} 次错误</div>
    </div>
    <section class="dashboard-surface">
      <header class="dashboard-head">
        <span class="path">基于 attempts / mistakes / diagnoses / personal_weaknesses</span>
        <h2>${topWeakness ? `现在最该补：${escapeHtml(topWeakness.title)}` : "还没有足够的个人练习证据"}</h2>
        <p>${topWeakness ? escapeHtml(weaknessReason(topWeakness)) : "先完成几次练习或错题沉淀，系统会在这里聚合个人薄弱证据。"}</p>
      </header>
      <div class="dashboard-grid">
        <section class="dashboard-main">
          ${detail ? renderWeaknessDetail(detail) : renderDashboardEmpty()}
          ${renderTrendPanel()}
        </section>
        <aside class="dashboard-aside">
          ${renderHeatmapPanel()}
          ${renderTypeRadarPanel()}
          ${renderPitfallPanel()}
        </aside>
      </div>
    </section>
  `;
  els.workspace.querySelectorAll("[data-train-question]").forEach(button => {
    button.addEventListener("click", () => route(`/practice/${button.dataset.trainQuestion}`));
  });
  els.workspace.querySelectorAll("[data-weakness]").forEach(button => {
    button.addEventListener("click", () => {
      state.activeWeaknessId = Number(button.dataset.weakness);
      route(`/dashboard/${state.activeWeaknessId}`);
    });
  });
}

function renderDashboardSidebar() {
  const totalAttempts = sumTrend("attempt_count");
  const wrongCount = sumTrend("wrong_count");
  els.sidebar.innerHTML = `
    <section class="panel summary-panel">
      <div class="stat"><strong>${state.dashboard.weakTop.length}</strong><span>薄弱点</span></div>
      <div class="stat"><strong>${wrongCount}</strong><span>近 7 天错题</span></div>
    </section>
    <section class="panel">
      <h2>个人薄弱 Top 10</h2>
      <div class="weakness-list">
        ${state.dashboard.weakTop.map(renderWeaknessButton).join("") || `<div class="side-note">暂无个人薄弱证据。</div>`}
      </div>
    </section>
    <section class="panel">
      <h2>证据状态</h2>
      <div class="side-note">${totalAttempts ? `最近 7 天记录 ${totalAttempts} 次作答，错误率 ${Math.round((wrongCount / totalAttempts) * 100)}%。` : "最近 7 天暂无作答记录。"}</div>
    </section>
  `;
  els.sidebar.querySelectorAll("[data-weakness]").forEach(button => {
    button.addEventListener("click", () => {
      state.activeWeaknessId = Number(button.dataset.weakness);
      route(`/dashboard/${state.activeWeaknessId}`);
    });
  });
}

function renderWeaknessButton(item) {
  return `
    <button class="weakness-button ${item.id === state.activeWeaknessId ? "active" : ""}" type="button" data-weakness="${item.id}">
      <span>${escapeHtml(item.title)}</span>
      <small>${targetLabel(item.target_type)} · 证据 ${item.evidence_count} · 强度 ${percent(item.strength)}</small>
      <i style="width:${Math.min(100, Math.max(4, Math.round((item.score || item.strength) * 20)))}%"></i>
    </button>
  `;
}

function renderWeaknessDetail(detail) {
  const firstQuestion = detail.related_questions[0] || detail.evidence[0]?.question;
  return `
    <article class="reader dashboard-detail">
      <header class="article-head">
        <span class="path">${targetLabel(detail.weakness.target_type)} · 证据 ${detail.weakness.evidence_count} · 掌握度 ${percent(detail.weakness.mastery)}</span>
        <h2>${escapeHtml(detail.weakness.title)}</h2>
        <p class="filter-note">${escapeHtml(weaknessReason(detail.weakness))}</p>
        <div class="article-actions">
          ${firstQuestion ? `<button type="button" data-train-question="${firstQuestion.id}">一键针对训练</button>` : ""}
        </div>
      </header>
      <div class="article-body">
        <h4>证据错题</h4>
        ${detail.evidence.map(renderEvidenceItem).join("") || "<p>暂无可展开证据。</p>"}
        <h4>建议训练入口</h4>
        <ul>
          ${detail.related_questions.map(question => `<li><button class="inline-link" type="button" data-train-question="${question.id}">${escapeHtml(questionDisplay(question).title)}</button> ${escapeHtml(buildSummary(stripMarkdown(question.stem_md)))}</li>`).join("") || "<li>先补充关联题目，再生成训练入口。</li>"}
        </ul>
      </div>
    </article>
  `;
}

function renderEvidenceItem(item) {
  return `
    <div class="evidence-item">
      <strong>${escapeHtml(questionDisplay(item.question).title)}</strong>
      <span>${formatDate(item.attempted_at)} · ${escapeHtml(item.source)} · 置信度 ${percent(item.confidence)}</span>
      <p>${escapeHtml(buildSummary(stripMarkdown(item.question.stem_md)))}</p>
      ${item.user_answer_md ? `<p><b>我的作答：</b>${escapeHtml(buildSummary(stripMarkdown(item.user_answer_md)))}</p>` : ""}
      ${item.note_md ? `<p><b>复盘：</b>${escapeHtml(item.note_md)}</p>` : ""}
    </div>
  `;
}

function renderDashboardEmpty() {
  return `<article class="reader"><div class="empty-state"><strong>暂无学情证据</strong><span>完成练习或错题拍照沉淀后，这里会显示个人薄弱链路。</span></div></article>`;
}

function renderHeatmapPanel() {
  return `
    <section class="dashboard-panel">
      <h3>知识点热力图</h3>
      <div class="heatmap-list">
        ${state.dashboard.heatmap.slice(0, 12).map(item => `
          <div class="heatmap-row">
            <span>${escapeHtml(item.title)}</span>
            <meter min="0" max="1" value="${item.strength}"></meter>
            <small>${escapeHtml(item.chapter || item.book)} · 错 ${item.wrong_count}</small>
          </div>
        `).join("") || `<p class="snippet">暂无知识点薄弱记录。</p>`}
      </div>
    </section>
  `;
}

function renderTypeRadarPanel() {
  const max = Math.max(1, ...state.dashboard.typeRadar.map(item => item.strength));
  return `
    <section class="dashboard-panel">
      <h3>题型掌握度</h3>
      <div class="radar-list">
        ${state.dashboard.typeRadar.slice(0, 8).map(item => `
          <div class="radar-row">
            <span>${escapeHtml(item.name)}</span>
            <i style="width:${Math.round((1 - item.strength / max) * 76 + 12)}%"></i>
            <small>掌握 ${percent(item.mastery)} · 错 ${item.wrong_count}</small>
          </div>
        `).join("") || `<p class="snippet">暂无题型弱点。</p>`}
      </div>
    </section>
  `;
}

function renderPitfallPanel() {
  return `
    <section class="dashboard-panel">
      <h3>个人易错模式</h3>
      <div class="pitfall-list">
        ${state.dashboard.pitfalls.map(item => `
          <button type="button" data-weakness="${item.id}" class="${item.id === state.activeWeaknessId ? "active" : ""}">
            <span>${escapeHtml(item.title)}</span>
            <small>${targetLabel(item.target_type)} · ${percent(item.strength)}</small>
          </button>
        `).join("") || `<p class="snippet">暂无反复易错模式。</p>`}
      </div>
    </section>
  `;
}

function renderTrendPanel() {
  const max = Math.max(1, ...state.dashboard.trend.map(item => item.attempt_count));
  return `
    <section class="dashboard-panel trend-panel">
      <h3>错题趋势</h3>
      <div class="trend-bars">
        ${state.dashboard.trend.map(item => `
          <div class="trend-bar">
            <span style="height:${Math.max(4, Math.round((item.wrong_count / max) * 96))}px"></span>
            <small>${item.date.slice(5)}</small>
          </div>
        `).join("")}
      </div>
    </section>
  `;
}

function sumTrend(key) {
  return state.dashboard.trend.reduce((sum, item) => sum + Number(item[key] || 0), 0);
}

function weaknessReason(item) {
  return `${targetLabel(item.target_type)}节点，薄弱强度 ${percent(item.strength)}，来自 ${item.evidence_count} 条个人证据，关联 ${item.question_count} 道训练题。`;
}

function targetLabel(type) {
  return { kp: "知识点", pattern: "题型", skill: "技巧", pitfall: "易错点", custom: "个人错因" }[type] || type;
}

function percent(value) {
  return `${Math.round(Number(value || 0) * 100)}%`;
}

function formatDate(value) {
  if (!value) return "";
  return String(value).slice(0, 10);
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
    if (isChoiceLine(line)) {
      const choices = [];
      while (i < lines.length && isChoiceLine(lines[i])) { choices.push(lines[i].trim()); i += 1; }
      html.push(`<div class="question-options">${choices.map(text => `<p>${formatInline(text)}</p>`).join("")}</div>`);
      continue;
    }
    const paragraph = [line];
    i += 1;
    while (i < lines.length && lines[i].trim() && !isBlockStart(lines, i)) { paragraph.push(lines[i]); i += 1; }
    html.push(`<p>${paragraph.map(formatInline).join("<br>")}</p>`);
  }
  return html.join("");
}

function isBlockStart(lines, index) {
  const line = lines[index] || "";
  return /^####\s+/.test(line) || line.trim() === "---" || line.trim() === "$$" || /^\s*-\s+/.test(line) || /^\s*\d+\.\s+/.test(line) || isChoiceLine(line) || isTableStart(lines, index);
}

function isChoiceLine(line) {
  return /^\s*[A-H][．.、]\s*/.test(line || "");
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

function keepActiveKpContextVisible() {
  const activeCard = els.results?.querySelector(".result-card.active");
  if (activeCard && els.results) {
    const resultsRect = els.results.getBoundingClientRect();
    const activeRect = activeCard.getBoundingClientRect();
    els.results.scrollTop += activeRect.top - resultsRect.top - 12;
  }

  const activeChapter = els.chapterNav?.querySelector(".chapter-link.active");
  if (!activeChapter || !els.sidebar || window.matchMedia("(max-width: 1040px)").matches) return;

  const sidebarRect = els.sidebar.getBoundingClientRect();
  const chapterRect = activeChapter.getBoundingClientRect();
  if (chapterRect.top < sidebarRect.top || chapterRect.bottom > sidebarRect.bottom) {
    els.sidebar.scrollTop += chapterRect.top - sidebarRect.top - 18;
  }
}

function splitText(value) {
  return String(value || "").replace("，", ",").split(",").map(item => item.trim()).filter(Boolean);
}

function splitNodes(value, primaryFirst = false) {
  return splitText(value).map((name, index) => ({ name, weight: index === 0 ? 1 : 0.75, is_primary: primaryFirst && index === 0 }));
}

function questionDisplay(question) {
  const fallbackTitle = `题目 #${question.id}`;
  const source = String(question.source || "").trim();
  if (!source) {
    return { title: fallbackTitle, meta: [], fullSource: fallbackTitle };
  }

  const parts = splitQuestionSource(source);
  if (parts.length >= 3) {
    const collection = compactQuestionCollection(parts[0]);
    const section = parts[1];
    const labels = parts.slice(2).join(" · ");
    return {
      title: [questionSectionTitle(section), labels].filter(Boolean).join(" · "),
      meta: [collection, questionSectionMarker(section)].filter(Boolean),
      fullSource: source
    };
  }

  if (parts.length === 2) {
    return {
      title: questionSectionTitle(parts[1]) || parts[1],
      meta: [compactQuestionCollection(parts[0])].filter(Boolean),
      fullSource: source
    };
  }

  return { title: source || fallbackTitle, meta: [], fullSource: source || fallbackTitle };
}

function questionMetaPath(question, display = questionDisplay(question)) {
  return [
    question.format_name,
    question.difficulty ? `难度 ${question.difficulty}` : "",
    ...display.meta
  ].filter(Boolean).join(" / ");
}

function splitQuestionSource(source) {
  return String(source || "").split(/[|｜]/).map(part => part.trim()).filter(Boolean);
}

function compactQuestionCollection(collection) {
  return collection.replace(/[（(]\s*解析版\s*[）)]/g, "").trim();
}

function questionSectionTitle(section) {
  const title = String(section || "")
    .replace(/^(方法技巧|易混易错)\s*\d+\s*/, "")
    .replace(/^题型[一二三四五六七八九十百\d]+\s*/, "")
    .trim();
  return title || section;
}

function questionSectionMarker(section) {
  const method = String(section || "").match(/^(方法技巧|易混易错)\s*(\d+)/);
  if (method) return `${method[1]}${method[2]}`;

  const type = String(section || "").match(/^(题型[一二三四五六七八九十百\d]+)/);
  return type ? type[1] : "";
}

function renderTags(tags) {
  return [...new Set(tags.filter(Boolean))].map(tag => {
    const className = tag === "考点" ? "hot" : tag === "易错" || /错/.test(tag) ? "warn" : tag === "公式" ? "formula" : "deep";
    return `<span class="tag ${className}">${escapeHtml(tag)}</span>`;
  }).join("");
}

function renderQuestionImages(rawPaths, usedContent = "") {
  const paths = questionImagePaths(rawPaths).filter(path => !usedContent.includes(`[[img:${path}]]`));
  if (!paths.length) return "";
  return `
    <div class="question-images" aria-label="题目配图">
      ${paths.map((path, index) => `
        <figure class="question-figure">
          <img src="${escapeAttr(imageUrl(path))}" alt="题目配图 ${index + 1}" loading="lazy">
        </figure>
      `).join("")}
    </div>
  `;
}

function questionRichContent(question) {
  return [question?.stem_md, question?.answer_md, question?.solution_md].filter(Boolean).join("\n");
}

function questionImagePaths(rawPaths) {
  if (!rawPaths) return [];
  if (Array.isArray(rawPaths)) return rawPaths.filter(Boolean);
  const value = String(rawPaths).trim();
  if (!value) return [];
  if (value.startsWith("[")) {
    try {
      const parsed = JSON.parse(value);
      if (Array.isArray(parsed)) return parsed.filter(Boolean);
    } catch {}
  }
  return value.split(/\n+/).map(path => path.trim()).filter(Boolean);
}

function imageUrl(path) {
  if (/^https?:\/\//i.test(path) || path.startsWith("/")) return path;
  const normalized = path.replace(/^\/+/, "");
  const version = normalized.startsWith("data/uploads/extracted/") ? "?v=docx-readable-7" : "";
  return `/${normalized}${version}`;
}

function formatInline(text) {
  return String(text).split(/(\[\[img:[^\]]+\]\])/g).map(part => {
    const image = part.match(/^\[\[img:([^\]]+)\]\]$/);
    if (image) {
      let path = image[1];
      let sizeStyle = "";
      const sized = path.match(/^(.*)\|(\d+)x(\d+)$/);
      if (sized) {
        path = sized[1];
        sizeStyle = ` style="width:${sized[2]}px;height:${sized[3]}px"`;
      }
      return `<span class="docx-inline-wrap"><img class="docx-inline-image${sized ? " docx-equation" : ""}" src="${escapeAttr(imageUrl(path))}" alt="公式或配图" loading="lazy"${sizeStyle}></span>`;
    }
    return escapeHtml(part).replace(/`([^`]+)`/g, "<code>$1</code>").replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  }).join("");
}

function highlight(text) {
  if (!state.query) return text;
  return text.replace(new RegExp(`(${escapeRegExp(state.query)})`, "gi"), "<mark>$1</mark>");
}

function buildSummary(text) {
  return text.replace(/\s+/g, " ").trim().slice(0, 118) || "点击查看完整内容。";
}

function stripMarkdown(text) {
  return String(text || "").replace(/\[\[img:[^\]]+\]\]/g, "公式").replace(/```[\s\S]*?```/g, " ").replace(/\$\$([\s\S]*?)\$\$/g, " $1 ").replace(/[#>*_|`[\](){}\\]/g, " ").replace(/\s+/g, " ").trim();
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
