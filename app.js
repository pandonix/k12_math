const SOURCE_FILE = "./高一数学知识点总整理（人教A版必修一二详版）.md";

const state = {
  items: [],
  chapters: [],
  query: "",
  book: "全部",
  type: "全部",
  activeId: "",
  shellEventsBound: false,
  favorites: new Set(JSON.parse(localStorage.getItem("mathFavorites") || "[]"))
};

const typeFilters = [
  { key: "全部", label: "全部" },
  { key: "公式", label: "公式" },
  { key: "考点", label: "高频考点" },
  { key: "易错", label: "易错提醒" },
  { key: "二级结论", label: "二级结论" },
  { key: "收藏", label: "收藏" }
];

const els = {
  search: document.querySelector("#searchInput"),
  clear: document.querySelector("#clearSearch"),
  results: document.querySelector("#results"),
  reader: document.querySelector("#reader"),
  resultCount: document.querySelector("#resultCount"),
  sectionCount: document.querySelector("#sectionCount"),
  chapterCount: document.querySelector("#chapterCount"),
  bookFilters: document.querySelector("#bookFilters"),
  typeFilters: document.querySelector("#typeFilters"),
  chapterNav: document.querySelector("#chapterNav")
};

init();

async function init() {
  bindEvents();
  try {
    const response = await fetch(SOURCE_FILE);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const markdown = await response.text();
    const parsed = parseMarkdown(markdown);
    state.items = parsed.items;
    state.chapters = parsed.chapters;
    state.activeId = location.hash.replace("#", "") || state.items[0]?.id || "";
    renderShell();
    render();
  } catch (error) {
    els.reader.innerHTML = `
      <div class="empty-state">
        <strong>Markdown 读取失败</strong>
        <span>请通过本地服务器打开本页面，例如在当前目录运行 python3 -m http.server。</span>
      </div>`;
    els.resultCount.textContent = "加载失败";
    console.error(error);
  }
}

function bindEvents() {
  els.search.addEventListener("input", event => {
    state.query = event.target.value.trim();
    render();
  });

  els.clear.addEventListener("click", () => {
    state.query = "";
    els.search.value = "";
    render();
    els.search.focus();
  });

  window.addEventListener("hashchange", () => {
    const next = location.hash.replace("#", "");
    if (state.items.some(item => item.id === next)) {
      state.activeId = next;
      render();
    }
  });

  document.addEventListener("keydown", event => {
    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
      event.preventDefault();
      els.search.focus();
    }
  });
}

function parseMarkdown(markdown) {
  const lines = markdown.replace(/\r\n/g, "\n").split("\n");
  const items = [];
  const chapterSet = new Map();
  let book = "";
  let chapter = "";
  let current = null;

  const pushCurrent = () => {
    if (!current) return;
    current.content = current.lines.join("\n").trim();
    current.plain = stripMarkdown(`${current.title}\n${current.content}`);
    current.tags = inferTags(current);
    current.summary = buildSummary(current.plain);
    items.push(current);
  };

  for (const line of lines) {
    const heading = line.match(/^(#{1,4})\s+(.+)$/);
    if (!heading) {
      if (current) current.lines.push(line);
      continue;
    }

    const level = heading[1].length;
    const title = heading[2].trim();

    if (level === 1) {
      pushCurrent();
      current = null;
      if (/^必修/.test(title) || /^附录/.test(title)) {
        book = title.includes("附录") ? "附录" : title;
        chapter = title.includes("附录") ? title : "";
      } else {
        book = "";
        chapter = "";
      }
      continue;
    }

    if (level === 2) {
      if (book === "附录") {
        pushCurrent();
        current = createItem({ book, chapter, title, level, index: items.length });
        continue;
      }
      pushCurrent();
      current = null;
      chapter = title;
      if (book && chapter) chapterSet.set(`${book}｜${chapter}`, { book, chapter });
      continue;
    }

    if (level === 3) {
      pushCurrent();
      current = createItem({ book, chapter, title, level, index: items.length });
      continue;
    }

    if (current) current.lines.push(line);
  }

  pushCurrent();

  const chapters = Array.from(chapterSet.values());
  return { items, chapters };
}

function createItem({ book, chapter, title, level, index }) {
  return {
    id: slugify(`${book}-${chapter}-${title}-${index}`),
    book,
    chapter,
    title: cleanMathTitle(title),
    level,
    lines: []
  };
}

function inferTags(item) {
  const text = `${item.title}\n${item.content}`;
  const tags = [];
  if (/\$\$|公式|定理|恒等式|运算律|坐标公式|面积公式|体积|表面积|半径/.test(text)) tags.push("公式");
  if (/高频考点|典型题型|常用思路/.test(text)) tags.push("考点");
  if (/易错提醒|易错点/.test(text)) tags.push("易错");
  if (/二级结论/.test(text)) tags.push("二级结论");
  return tags;
}

function renderShell() {
  const books = ["全部", ...new Set(state.items.map(item => item.book).filter(Boolean))];
  els.bookFilters.innerHTML = books.map(book => `
    <button class="chip ${state.book === book ? "active" : ""}" type="button" data-book="${escapeAttr(book)}">${escapeHtml(book)}</button>
  `).join("");

  els.typeFilters.innerHTML = typeFilters.map(filter => `
    <button class="segment ${state.type === filter.key ? "active" : ""}" type="button" data-type="${filter.key}">${filter.label}</button>
  `).join("");

  els.chapterNav.innerHTML = state.chapters.map(entry => `
    <button class="chapter-link" type="button" data-book="${escapeAttr(entry.book)}" data-chapter="${escapeAttr(entry.chapter)}">
      ${escapeHtml(entry.chapter)}
    </button>
  `).join("");

  els.sectionCount.textContent = state.items.length;
  els.chapterCount.textContent = state.chapters.length;

  if (!state.shellEventsBound) {
    state.shellEventsBound = true;
    els.bookFilters.addEventListener("click", event => {
      const button = event.target.closest("[data-book]");
      if (!button) return;
      state.book = button.dataset.book;
      renderShell();
      render();
    });

    els.typeFilters.addEventListener("click", event => {
      const button = event.target.closest("[data-type]");
      if (!button) return;
      state.type = button.dataset.type;
      renderShell();
      render();
    });

    els.chapterNav.addEventListener("click", event => {
      const button = event.target.closest("[data-chapter]");
      if (!button) return;
      state.book = button.dataset.book;
      const target = state.items.find(item => item.book === button.dataset.book && item.chapter === button.dataset.chapter);
      if (target) selectItem(target.id);
      renderShell();
      render();
    });
  }
}

function render() {
  const filtered = getFilteredItems();
  if (!filtered.some(item => item.id === state.activeId)) {
    state.activeId = filtered[0]?.id || state.items[0]?.id || "";
  }

  renderResults(filtered);
  renderReader(state.items.find(item => item.id === state.activeId));
  updateActiveNav();
  els.resultCount.textContent = `${filtered.length} 个结果`;
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

function renderResults(items) {
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
    button.addEventListener("click", () => selectItem(button.dataset.id));
  });
}

function renderReader(item) {
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
        <button type="button" data-action="top">回到顶部</button>
      </div>
    </header>
    <div class="article-body">${renderMarkdown(readerContent)}</div>
  `;

  els.reader.querySelector("[data-action='favorite']").addEventListener("click", () => toggleFavorite(item.id));
  els.reader.querySelector("[data-action='copy']").addEventListener("click", () => copyCurrentLink(item.id));
  els.reader.querySelector("[data-action='top']").addEventListener("click", () => window.scrollTo({ top: 0, behavior: "smooth" }));

  if (window.MathJax?.typesetPromise) {
    window.MathJax.typesetPromise([els.reader]).catch(console.error);
  }
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

  if (state.type === "公式" && item.tags.includes("公式")) {
    return extractFormulaLines(item.content) || item.content;
  }

  return item.content;
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

    if (!current) {
      current = { heading: "", lines: [] };
    }
    current.lines.push(line);
  }

  if (current) blocks.push(current);
  return blocks.map(block => ({
    ...block,
    raw: block.lines.join("\n").trim()
  })).filter(block => block.raw);
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
      const previous = findPreviousLabel(lines, i - math.length - 2);
      chunks.push([currentHeading, previous, "$$", ...math, "$$"].filter(Boolean).join("\n"));
    }
  }

  return chunks.join("\n\n");
}

function findPreviousLabel(lines, index) {
  for (let i = index; i >= 0; i -= 1) {
    const line = lines[i]?.trim();
    if (!line || line === "$$" || /^####\s+/.test(line)) continue;
    if (/^\|/.test(line) || /^[-\d.]+\s/.test(line)) continue;
    return line;
  }
  return "";
}

function renderMarkdown(markdown) {
  const lines = markdown.split("\n");
  const html = [];
  let i = 0;

  while (i < lines.length) {
    const line = lines[i];
    if (!line.trim()) {
      i += 1;
      continue;
    }

    if (line.trim() === "---") {
      html.push("<hr>");
      i += 1;
      continue;
    }

    if (line.trim() === "$$") {
      const math = [];
      i += 1;
      while (i < lines.length && lines[i].trim() !== "$$") {
        math.push(lines[i]);
        i += 1;
      }
      i += 1;
      html.push(`<div class="math-block">$$${escapeHtml(math.join("\n"))}$$</div>`);
      continue;
    }

    if (/^####\s+/.test(line)) {
      html.push(`<h4>${formatInline(line.replace(/^####\s+/, ""))}</h4>`);
      i += 1;
      continue;
    }

    if (isTableStart(lines, i)) {
      const table = [];
      while (i < lines.length && /^\s*\|.*\|\s*$/.test(lines[i])) {
        table.push(lines[i]);
        i += 1;
      }
      html.push(renderTable(table));
      continue;
    }

    if (/^\s*-\s+/.test(line)) {
      const list = [];
      while (i < lines.length && /^\s*-\s+/.test(lines[i])) {
        list.push(lines[i].replace(/^\s*-\s+/, ""));
        i += 1;
      }
      html.push(`<ul>${list.map(text => `<li>${formatInline(text)}</li>`).join("")}</ul>`);
      continue;
    }

    if (/^\s*\d+\.\s+/.test(line)) {
      const list = [];
      while (i < lines.length && /^\s*\d+\.\s+/.test(lines[i])) {
        list.push(lines[i].replace(/^\s*\d+\.\s+/, ""));
        i += 1;
      }
      html.push(`<ol>${list.map(text => `<li>${formatInline(text)}</li>`).join("")}</ol>`);
      continue;
    }

    const paragraph = [line];
    i += 1;
    while (i < lines.length && lines[i].trim() && !isBlockStart(lines, i)) {
      paragraph.push(lines[i]);
      i += 1;
    }
    html.push(`<p>${formatInline(paragraph.join(" "))}</p>`);
  }

  return html.join("");
}

function isBlockStart(lines, index) {
  const line = lines[index] || "";
  return /^####\s+/.test(line) ||
    line.trim() === "---" ||
    line.trim() === "$$" ||
    /^\s*-\s+/.test(line) ||
    /^\s*\d+\.\s+/.test(line) ||
    isTableStart(lines, index);
}

function isTableStart(lines, index) {
  return /^\s*\|.*\|\s*$/.test(lines[index] || "") && /^\s*\|?\s*:?-{3,}:?\s*\|/.test(lines[index + 1] || "");
}

function renderTable(rows) {
  const cells = rows.map(row => row.trim().replace(/^\||\|$/g, "").split("|").map(cell => cell.trim()));
  const head = cells[0] || [];
  const body = cells.slice(2);
  return `
    <table>
      <thead><tr>${head.map(cell => `<th>${formatInline(cell)}</th>`).join("")}</tr></thead>
      <tbody>${body.map(row => `<tr>${row.map(cell => `<td>${formatInline(cell)}</td>`).join("")}</tr>`).join("")}</tbody>
    </table>
  `;
}

function selectItem(id) {
  state.activeId = id;
  history.replaceState(null, "", `#${id}`);
  render();
}

function toggleFavorite(id) {
  if (state.favorites.has(id)) {
    state.favorites.delete(id);
  } else {
    state.favorites.add(id);
  }
  localStorage.setItem("mathFavorites", JSON.stringify([...state.favorites]));
  render();
}

async function copyCurrentLink(id) {
  const url = `${location.origin}${location.pathname}#${id}`;
  try {
    await navigator.clipboard.writeText(url);
    const button = els.reader.querySelector("[data-action='copy']");
    button.textContent = "已复制";
    setTimeout(() => { button.textContent = "复制链接"; }, 1200);
  } catch {
    prompt("复制此链接：", url);
  }
}

function updateActiveNav() {
  const active = state.items.find(item => item.id === state.activeId);
  els.chapterNav.querySelectorAll("[data-chapter]").forEach(button => {
    button.classList.toggle("active", Boolean(active && button.dataset.book === active.book && button.dataset.chapter === active.chapter));
  });
}

function renderTags(tags) {
  return tags.map(tag => {
    const className = tag === "考点" ? "hot" : tag === "易错" ? "warn" : tag === "公式" ? "formula" : "deep";
    return `<span class="tag ${className}">${tag}</span>`;
  }).join("");
}

function formatInline(text) {
  return escapeHtml(text)
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
}

function highlight(text) {
  if (!state.query) return text;
  const query = escapeRegExp(state.query);
  return text.replace(new RegExp(`(${query})`, "gi"), "<mark>$1</mark>");
}

function buildSummary(text) {
  return text.replace(/\s+/g, " ").trim().slice(0, 118) || "点击查看本节完整内容。";
}

function stripMarkdown(text) {
  return text
    .replace(/```[\s\S]*?```/g, " ")
    .replace(/\$\$([\s\S]*?)\$\$/g, " $1 ")
    .replace(/[#>*_|`[\](){}\\]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function normalize(text) {
  return text.toLowerCase().replace(/\s+/g, "");
}

function cleanMathTitle(title) {
  return title.replace(/\s+/g, " ").trim();
}

function slugify(text) {
  let hash = 0;
  for (let i = 0; i < text.length; i += 1) {
    hash = ((hash << 5) - hash + text.charCodeAt(i)) | 0;
  }
  return `k-${Math.abs(hash).toString(36)}`;
}

function escapeHtml(value) {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function escapeAttr(value) {
  return escapeHtml(value);
}

function escapeRegExp(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}
