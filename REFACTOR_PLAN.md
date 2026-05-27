# 高一数学知识库 → 题库 + 错题集 + 自适应训练 重构实施方案

> 状态：方案稿（v1） · 待执行
> 决策：单设备自用 / PDF 图片 OCR 录题 / 本地后端 / 自适应推荐 / 暂无 ANTHROPIC_API_KEY（M3 提供降级）

---

## 0. 文档导航

- [1. 背景与目标](#1-背景与目标)
- [2. 现状盘点](#2-现状盘点)
- [3. 目标架构总览](#3-目标架构总览)
- [4. 技术选型](#4-技术选型)
- [5. 数据模型](#5-数据模型)
- [6. 核心流程](#6-核心流程)
- [7. API 设计](#7-api-设计)
- [8. 前端改造](#8-前端改造)
- [9. 目录结构](#9-目录结构)
- [10. 分阶段实施 (M0–M5)](#10-分阶段实施-m0m5)
- [11. OCR 降级与可插拔方案](#11-ocr-降级与可插拔方案)
- [12. 风险与权衡](#12-风险与权衡)
- [13. 后续可选演进](#13-后续可选演进)

---

## 1. 背景与目标

### 1.1 当前能力
项目 `math/` 已有一个**纯静态前端**，把人教 A 版高一必修一/二的知识点（一份 3165 行 markdown）解析为可检索的知识卡片，支持章节浏览、关键词搜索、按"公式/考点/易错/二级结论"筛选、收藏。

### 1.2 新增目标
1. **题库**：录入试卷与练习，把题目、解答关联到知识点，方便按章节/知识点/题型/难度查询。
2. **个人错题集 + 学情分析**：记录做题历史与错题，识别薄弱知识点与题型。
3. **自适应训练**：根据学情自动推荐下一题，把训练集中在弱点。

### 1.3 范围与边界
- **单用户、单设备**（本地 SQLite 即可）
- **不引入前端框架**，保持 vanilla JS + MathJax，避免构建工具
- **不引入云依赖**，但数据模型预留多端同步演进路径
- 录题方式：M1 手动 + M3 OCR 批量
- 不做账户系统、不做协作、不做移动端原生

---

## 2. 现状盘点

| 维度 | 内容 |
|---|---|
| 入口 | `index.html`（81 行） |
| 前端逻辑 | `app.js`（610 行），含 markdown 解析、搜索、筛选、收藏 |
| 样式 | `styles.css`（557 行） |
| 数据源 | `高一数学知识点总整理（人教A版必修一二详版）.md`（3165 行） |
| 持久化 | 仅 `localStorage`（收藏 ID） |
| 启动脚本 | `start.sh` / `stop.sh`（python3 -m http.server） |
| 运行时 | 浏览器 fetch md → 运行时解析为扁平条目 |

### 2.1 可复用资产
- **章节切分逻辑**（`parseMarkdown` in app.js:90）：按一/二/三/四级标题切分，可直接复用作为知识点同步逻辑。
- **slugify 算法**（app.js:587）：哈希式 ID 生成，**必须沿用以保证现有 `#hash` 链接不破**。
- **markdown 渲染器**（app.js:408 `renderMarkdown`）：支持表格、有/无序列表、$$ 数学块，可继续用于题目解析渲染。
- **MathJax 配置**：保留，所有视图共用。

### 2.2 必须淘汰的设计
- **数据只读、单 md**：不再适合"录入题目、记录做题"等写场景。
- **localStorage 唯一持久化**：错题集与做题记录需要关系型查询。

---

## 3. 目标架构总览

```
┌─────────────────────────────────────────────────────────┐
│                   浏览器（前端，静态）                       │
│  index.html  +  views/{kp, questions, intake, practice,  │
│                       dashboard}.js  +  core/{api,router} │
└──────────────────────┬──────────────────────────────────┘
                       │ fetch /api/...
                       ▼
┌─────────────────────────────────────────────────────────┐
│           本地后端  FastAPI  (127.0.0.1:8001)            │
│  routers/  →  services/  →  SQLModel  →  SQLite          │
│                                  │                        │
│                                  ├── ocr  (LLM provider)  │
│                                  ├── kp_sync (md → DB)   │
│                                  └── recommender         │
└──────────────────────┬──────────────────────────────────┘
                       │
                       ▼
              data/math.db (SQLite + FTS5)
```

- 前端**继续静态**，由 `python -m http.server 8000` 提供
- 后端独立进程，监听 8001（仅本地）
- `start.sh` 并行拉起前后端
- 知识点 md 仍是**权威源**，启动时同步到表

---

## 4. 技术选型

| 层 | 选型 | 备选 | 选择理由 |
|---|---|---|---|
| 后端框架 | **FastAPI** | Flask, Hono(JS) | 类型化、Swagger 自动、社区成熟 |
| ORM | **SQLModel** | SQLAlchemy 裸用, Peewee | Pydantic + SQLAlchemy 合一，少写一份 schema |
| 数据库 | **SQLite** + FTS5 | DuckDB, Postgres | 单文件、零运维、备份 = cp |
| PDF 处理 | **PyMuPDF (fitz)** | pdfplumber | 渲染清晰、API 简洁 |
| 图像处理 | **Pillow** | OpenCV | 轻量足够 |
| LLM SDK | **anthropic** | openai, gemini | 题目识别 + 知识点关联一次到位 |
| HTTP 客户端 | **httpx** | requests | 异步友好 |
| 进程管理 | **uvicorn** | hypercorn | FastAPI 标配 |
| 前端 | **Vanilla JS + ESM** | React, Vue | 不引入构建工具，保持启动轻 |
| 图表 | **Chart.js**（CDN） | ECharts, D3 | 用法简单、轻量 |
| 数学渲染 | **MathJax 3**（已用） | KaTeX | 继续沿用 |

> 不引入 Node 工具链；前端不用打包。所有依赖通过 CDN 或 vendor 静态文件引入。

---

## 5. 数据模型

### 5.1 实体关系图（简化）

```
knowledge_points ──N:N── questions ──N:N── question_tags
       │                    │
       │                    ├── 1:N ── attempts
       │                    │            │
       │                    └── 1:N ── mistakes
       │                                 │
       └── stats_kp ◄── 聚合 ◄───────────┘
```

### 5.2 表结构（SQL DDL 草案）

```sql
-- 知识点：从 md 同步，权威源仍是 md
CREATE TABLE knowledge_points (
  id           TEXT PRIMARY KEY,          -- 沿用 app.js slugify('book-chapter-title-index')
  book         TEXT NOT NULL,             -- 必修第一册 / 必修第二册 / 附录
  chapter      TEXT,                      -- 第一章 集合与常用逻辑用语
  section      TEXT,                      -- 1.1 集合的概念与表示
  title        TEXT NOT NULL,             -- 小节标题或子标题
  level        INTEGER NOT NULL,          -- 1/2/3/4
  parent_id    TEXT REFERENCES knowledge_points(id),
  content_md   TEXT NOT NULL,
  tags_json    TEXT,                      -- ["公式","考点",...] 推断标签
  order_index  INTEGER NOT NULL,
  updated_at   DATETIME NOT NULL
);

CREATE INDEX idx_kp_book_chapter ON knowledge_points(book, chapter, section);

-- 题型字典
CREATE TABLE question_types (
  id   INTEGER PRIMARY KEY,
  name TEXT NOT NULL UNIQUE              -- 选择 / 填空 / 解答 / 证明 / 作图
);

-- 题目
CREATE TABLE questions (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  source        TEXT,                    -- 试卷名/页码：'2024 期中卷-第3题'
  type_id       INTEGER REFERENCES question_types(id),
  difficulty    INTEGER,                 -- 1-5
  stem_md       TEXT NOT NULL,           -- 题干 markdown + LaTeX
  options_json  TEXT,                    -- 选择题：[{"key":"A","text":"..."}, ...]
  answer_md     TEXT,                    -- 标准答案
  solution_md   TEXT,                    -- 解析
  image_path    TEXT,                    -- 原图（若 OCR 来）
  hash          TEXT UNIQUE,             -- 题干哈希，去重
  created_at    DATETIME NOT NULL,
  updated_at    DATETIME NOT NULL
);

-- 题目 ⇄ 知识点 N:N
CREATE TABLE question_kp (
  question_id  INTEGER REFERENCES questions(id) ON DELETE CASCADE,
  kp_id        TEXT    REFERENCES knowledge_points(id),
  weight       REAL DEFAULT 1.0,         -- 0-1，LLM 给出关联强度
  is_primary   INTEGER DEFAULT 0,        -- 主考点
  PRIMARY KEY (question_id, kp_id)
);

CREATE INDEX idx_qkp_kp ON question_kp(kp_id);

-- 自由标签：高频考点 / 二级结论 / 易错型 / 压轴 等
CREATE TABLE question_tags (
  question_id  INTEGER REFERENCES questions(id) ON DELETE CASCADE,
  tag          TEXT NOT NULL,
  PRIMARY KEY (question_id, tag)
);

-- 每次做题记录
CREATE TABLE attempts (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  question_id     INTEGER REFERENCES questions(id),
  is_correct      INTEGER NOT NULL,      -- 0/1
  self_rating     INTEGER,               -- 主观题自评 1-5
  time_spent_sec  INTEGER,
  user_answer_md  TEXT,
  attempted_at    DATETIME NOT NULL
);

CREATE INDEX idx_attempts_qid_time ON attempts(question_id, attempted_at);

-- 错题集（每题最多一行；wrong_count 累加）
CREATE TABLE mistakes (
  question_id      INTEGER PRIMARY KEY REFERENCES questions(id) ON DELETE CASCADE,
  first_wrong_at   DATETIME NOT NULL,
  last_wrong_at    DATETIME NOT NULL,
  wrong_count      INTEGER NOT NULL DEFAULT 1,
  last_attempt_id  INTEGER REFERENCES attempts(id),
  note_md          TEXT,                 -- 个人复盘笔记
  mastered_at      DATETIME              -- 标"已掌握"后填，否则 NULL
);

-- 自适应推荐：复习队列（SM-2 简化）
CREATE TABLE review_queue (
  question_id    INTEGER PRIMARY KEY REFERENCES questions(id) ON DELETE CASCADE,
  due_at         DATETIME NOT NULL,
  ease_factor    REAL NOT NULL DEFAULT 2.5,
  interval_days  REAL NOT NULL DEFAULT 1.0,
  repetitions    INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX idx_review_due ON review_queue(due_at);

-- 全文检索（FTS5 虚拟表）
CREATE VIRTUAL TABLE questions_fts USING fts5(
  stem_md, solution_md, source,
  content='questions', content_rowid='id',
  tokenize='unicode61'
);

CREATE VIRTUAL TABLE kp_fts USING fts5(
  title, content_md,
  content='knowledge_points', content_rowid='rowid',
  tokenize='unicode61'
);

-- 触发器维护 FTS（CRUD 时同步）
CREATE TRIGGER questions_ai AFTER INSERT ON questions BEGIN
  INSERT INTO questions_fts(rowid, stem_md, solution_md, source)
  VALUES (new.id, new.stem_md, new.solution_md, new.source);
END;
-- ... 类似的 ad / au 触发器
```

### 5.3 schema 演进策略
- 使用 **Alembic** 或最简手写 `migrations/0001_*.sql` 文件，启动时按序执行未跑过的。
- 单设备场景不需要回滚机制，丢库就重建（md 是源）。

---

## 6. 核心流程

### 6.1 流程 A：知识点同步（M0 启动时）

```
md 文件 → parse_markdown() → diff vs DB → upsert knowledge_points
```

- **触发**：后端启动 + 文件 mtime 变化（监听）+ 手动 `POST /api/admin/sync-kp`
- **id 稳定性**：复用现 `slugify('book-chapter-title-index')`，否则 md 重排会破链接
- **content_md 变更检测**：md5 比对，变了才更新

### 6.2 流程 B：手动录题（M1）

前端"录题"页表单 → `POST /api/questions`：
```json
{
  "source": "2024 春季月考第3题",
  "type_id": 1,
  "difficulty": 3,
  "stem_md": "已知 $f(x)=\\log_2(x-1)$，求定义域。",
  "options_json": null,
  "answer_md": "$\\{x \\mid x > 1\\}$",
  "solution_md": "...",
  "kp_ids": [
    {"id": "k-abc123", "weight": 1.0, "is_primary": true},
    {"id": "k-def456", "weight": 0.6, "is_primary": false}
  ],
  "tags": ["定义域陷阱","易错型"]
}
```

### 6.3 流程 C：OCR 批量录题（M3）

```
上传 PDF/图片
  ├─ PyMuPDF 拆页 → 每页 PNG (300dpi)
  ├─ 调用 OCR provider（详见 §11 降级方案）
  │   └─ 输出结构化 JSON：[{stem, type, options, answer?, solution?, kp_ids[], tags[], difficulty}]
  ├─ 前端"批量预览"页：逐题校对/修改，可直接拖动重排题号
  └─ 一键入库（事务）
```

**关键 prompt 设计**（当 LLM provider 启用时）：
- system prompt 注入**全部 knowledge_points 列表**（id + book/chapter/section + title），强制模型只能从中选 id
- 输出格式锁死 JSON schema（用 Anthropic tool use 强制）
- 大试卷分 batch（一次 5 题），降低单次 token 与失败成本

### 6.4 流程 D：做题与错题（M2）

```
进入做题页（单题模式 / 套题模式）
  → 计时开始
  → 用户作答（客观题选项 / 主观题 markdown 输入）
  → 提交
    ├─ 客观题：自动判对错
    └─ 主观题：用户自评 1-5（M3 后可选 LLM 判分）
  → 写 attempts
  → 若 is_correct = 0：upsert mistakes（wrong_count++）
  → 更新 review_queue（SM-2 算法，M5）
```

### 6.5 流程 E：自适应推荐（M5）

打分公式（首版）：
```
score(q) = 0.4 * kp_weakness(q)
         + 0.3 * overdue(q)
         + 0.2 * novelty(q)
         - 0.1 * recent_seen_penalty(q)

kp_weakness(q)  = mean(error_rate_30d) over kp ∈ q.kps
overdue(q)      = max(0, (now - review_queue.due_at).days) / 7
novelty(q)      = 1 if never attempted else 0
recent_seen     = 1 if attempted in last 24h else 0
```

每次"开始智能练习"取 Top-K（带轻微随机扰动），保证不会反复推同一题。

### 6.6 流程 F：学情仪表盘（M4）

- **知识点热力图**：章节树 + 每节涂色（绿/黄/红，基于该节关联题目的 30 天错误率）
- **题型雷达**：5 类题型的得分率
- **错题趋势**：按周聚合 `mistakes.first_wrong_at`
- **薄弱 Top 10**：按 `kp_weakness * 题量加权` 排序
- **一键针对训练**：选弱点 → 抽 10 道题 → 进入做题流

---

## 7. API 设计

所有路径前缀 `/api`。仅本地访问，无鉴权（127.0.0.1 绑定）。

### 7.1 知识点
```
GET  /api/kp                          # 列表（带筛选）
GET  /api/kp/{id}                     # 详情（含关联题目数）
GET  /api/kp/tree                     # 章节树
POST /api/admin/sync-kp               # 手动触发同步
```

### 7.2 题库
```
GET    /api/questions                 # ?kp=...&type=...&difficulty=...&q=...&page=
GET    /api/questions/{id}
POST   /api/questions                 # 录入
PATCH  /api/questions/{id}            # 修改
DELETE /api/questions/{id}
GET    /api/questions/{id}/related    # 同知识点的题
```

### 7.3 录题 / OCR
```
POST /api/intake/upload               # multipart: pdf 或 image
POST /api/intake/parse                # { upload_id } → 异步任务 id
GET  /api/intake/parse/{task_id}      # 拉取解析结果
POST /api/intake/commit               # 批量入库
```

### 7.4 做题与错题
```
POST /api/attempts                    # 提交一次作答
GET  /api/mistakes                    # 错题列表（支持按 kp / wrong_count / 未掌握筛选）
PATCH /api/mistakes/{qid}             # 更新笔记 / 标掌握
```

### 7.5 推荐 / 训练
```
POST /api/practice/next               # { mode: "smart"|"weak_kp"|"by_kp", kp?, count }
POST /api/practice/session/start
POST /api/practice/session/{id}/end
```

### 7.6 学情
```
GET /api/stats/heatmap                # 各知识点错误率
GET /api/stats/weak_top               # 薄弱 Top N
GET /api/stats/trend?period=week
GET /api/stats/type_radar
```

---

## 8. 前端改造

### 8.1 导航结构
顶部加 5 个 tab：
```
[知识点]  [题库]  [录题]  [练习/错题]  [学情]
```

### 8.2 视图职责

| 视图 | 文件 | 职责 |
|---|---|---|
| 知识点 | `views/kp.js` | **沿用现 app.js 90% 逻辑**，从 `/api/kp` 取数据 |
| 题库 | `views/questions.js` | 列表 + 多维筛选 + 详情抽屉 + 全文搜 |
| 录题 | `views/intake.js` | 手输表单 / PDF 拖拽上传 / 解析预览 / 批量提交 |
| 练习 | `views/practice.js` | 错题列表 + 智能练习模式 + 单题作答 UI |
| 学情 | `views/dashboard.js` | Chart.js 渲染 4 个图 + 薄弱 Top10 + 训练入口 |

### 8.3 公共模块
```
core/
  api.js          # fetch 封装 + base URL + 错误处理
  router.js       # hash 路由：#/kp, #/questions, #/practice/{qid} ...
  markdown.js     # 提取自现 app.js renderMarkdown
  mathjax.js      # typesetPromise 封装
  store.js        # 轻量状态管理（订阅式，不引 redux）
```

### 8.4 兼容策略
- 现有 `#k-xxx` 链接重定向到 `#/kp/k-xxx`
- 收藏数据从 `localStorage('mathFavorites')` 迁移到后端表 `favorites(kp_id)` 或保留 localStorage（看是否要跨设备）

---

## 9. 目录结构

```
math/
├── frontend/
│   ├── index.html              # 改造：加 nav + 五个 mount 点
│   ├── styles.css              # 沿用 + 新视图样式
│   ├── core/
│   │   ├── api.js
│   │   ├── router.js
│   │   ├── markdown.js
│   │   ├── mathjax.js
│   │   └── store.js
│   ├── views/
│   │   ├── kp.js
│   │   ├── questions.js
│   │   ├── intake.js
│   │   ├── practice.js
│   │   └── dashboard.js
│   └── vendor/
│       └── chart.umd.min.js    # 也可走 CDN
│
├── backend/
│   ├── main.py                 # FastAPI app，CORS only 127.0.0.1
│   ├── db.py                   # engine + session
│   ├── models.py               # SQLModel 实体
│   ├── schemas.py              # 请求/响应 Pydantic
│   ├── routers/
│   │   ├── kp.py
│   │   ├── questions.py
│   │   ├── intake.py
│   │   ├── practice.py
│   │   ├── stats.py
│   │   └── admin.py
│   ├── services/
│   │   ├── kp_sync.py          # md → DB
│   │   ├── ocr/
│   │   │   ├── base.py         # Provider 接口
│   │   │   ├── manual.py       # 默认：仅切页，不识别（M3 前/无 key 时）
│   │   │   ├── claude.py       # Claude 视觉（接 key 时启用）
│   │   │   └── mathpix.py      # 备选
│   │   ├── recommender.py
│   │   └── stats.py
│   ├── migrations/
│   │   └── 0001_initial.sql
│   ├── pyproject.toml          # 或 requirements.txt
│   └── .env.example
│
├── data/
│   └── math.db                 # 生成；加入 .gitignore
│
├── 高一数学知识点总整理（人教A版必修一二详版）.md   # 权威源
├── 高中数学必修第一册和第二册教材目录.md
├── 高中数学高考目录.md
├── 高中数学知识点目录.md
├── start.sh                    # 改造：并行 uvicorn + http.server
├── stop.sh                     # 改造：双进程 cleanup
└── REFACTOR_PLAN.md            # 本文件
```

**.gitignore 新增**：`data/`、`.venv/`、`__pycache__/`、`.runtime/`、`backend/.env`

---

## 10. 分阶段实施 (M0–M5)

每个 milestone 独立可用、可停。完成顺序严格按 M0 → M5。

### M0：后端骨架 + 知识点同步

**交付**
- `backend/` 目录与 venv
- FastAPI + SQLModel + SQLite 跑通
- `migrations/0001_initial.sql` 建全表
- `services/kp_sync.py` 把 md 解析入 `knowledge_points`
- `GET /api/kp`、`GET /api/kp/tree` 通
- `start.sh` 改造为并行拉前后端

**验证**
- `curl http://127.0.0.1:8001/api/kp/tree` 返回完整章节树
- 前端原页面不动，仍正常工作
- DB 中知识点数 == 旧前端解析出的条目数

**预计**：0.5 天

---

### M1：题库 + 手动录题

**交付**
- `routers/questions.py` + CRUD
- 前端 `views/questions.js`（列表 + 筛选 + 详情）
- 前端 `views/intake.js`（手输表单：题干/答案/解析 markdown + 知识点多选 + 题型/难度）
- `views/kp.js` 接入后端，沿用现 UI
- 顶部 nav 路由切换

**验证**
- 手动录 5–10 道真题
- 在题库页按知识点筛选、按"易错"标签筛选都能命中
- 知识点详情页能列出该知识点关联的题目

**预计**：1–2 天

---

### M2：做题 + 错题集

**交付**
- 单题做题页（客观题选项、主观题 markdown 输入）
- `POST /api/attempts` + 自动写 `mistakes`
- 错题列表页（按知识点筛、按错次排）
- 错题详情：再次作答 + 复盘笔记 + "已掌握"开关

**验证**
- 做错的题立刻进错题集
- 同一题再错，`wrong_count` 累加，`last_wrong_at` 更新
- 标"已掌握"后从默认列表消失，但可在"已掌握"tab 翻出

**预计**：1–2 天

---

### M3：OCR 批量录题

**前置条件**
- 若有 `ANTHROPIC_API_KEY` → 启用 `services/ocr/claude.py`
- 若无 → 使用 `manual.py`：仅做 PDF 拆页 + 缩略图预览，用户在前端**逐图手输**（仍比纯手输方便：图固定在旁边对照）

**交付**
- 上传 PDF/图片接口
- 拆页 + 缩略图
- OCR provider 接口（base.py 定义 `parse(image_bytes) -> List[ParsedQuestion]`）
- 前端"批量预览"页：左侧图、右侧结构化字段，可改可删可重排
- 一键事务入库 + 自动写 `question_kp`

**验证（有 key 情况）**
- 一份 1 页期中卷 30 秒内出解析结果
- 解析准确率主观评估 > 80%，关联知识点准确率 > 70%

**验证（无 key 降级情况）**
- 至少能拆页、把图按题分块、左右对照手输

**预计**：有 key 1–2 天；无 key 0.5 天（只做拆页 + 对照录入）

---

### M4：学情仪表盘

**交付**
- `routers/stats.py` 四个端点
- `views/dashboard.js` + Chart.js
  - 知识点热力图（按章节树折叠展开）
  - 题型雷达
  - 错题趋势折线
  - 薄弱 Top10 列表 + "一键训练"按钮

**验证**
- 数据真实反映 attempts/mistakes 状态
- 点击薄弱 Top10 中某项 → 跳转题库，自动按该知识点筛选

**预计**：1 天

---

### M5：自适应推荐

**交付**
- `services/recommender.py` 实现打分函数
- `POST /api/practice/next`
- 前端"智能练习"模式：自动连推 10 题，含进度条、跳过、即时统计
- 接入 SM-2 复习算法（基于 attempts 增量更新 `review_queue`）

**验证**
- 推荐结果以薄弱知识点为主，不会反复推同一题
- 24 小时内见过的题被显著降权
- "智能练习"完成后给出本次正确率与覆盖知识点

**预计**：1–2 天

---

### 全程总预算
- 有 API key：约 5–8 天（含调试）
- 无 API key（M3 降级）：约 4–6 天

---

## 11. OCR 降级与可插拔方案

### 11.1 接口抽象

```python
# backend/services/ocr/base.py
class OCRProvider(Protocol):
    name: str
    def parse(self, image_bytes: bytes, context: ParseContext) -> list[ParsedQuestion]: ...

class ParseContext(BaseModel):
    page_index: int
    known_kp_ids: list[str]   # 注入全部知识点 id 供模型选择
    hint_source: str | None   # 试卷名等上下文
```

通过环境变量切换：
```
OCR_PROVIDER=manual   # 默认，不调外部
OCR_PROVIDER=claude   # 需要 ANTHROPIC_API_KEY
OCR_PROVIDER=mathpix  # 需要 MATHPIX_APP_ID/KEY
```

### 11.2 三档实现

| Provider | 依赖 | 输出 | 体验 |
|---|---|---|---|
| `manual` | 仅 PyMuPDF | 切页图片 | 用户对照手输，**不依赖任何外部** |
| `claude` | anthropic SDK | 完整结构化题目（含 LaTeX、答案、解析、kp_ids、难度） | 最优；30 秒/页 |
| `mathpix` | Mathpix API | LaTeX 文本，仍需后续规则切题 | 公式准但缺业务理解 |

### 11.3 当前阶段建议
- M0–M2 完全不依赖 OCR，按计划推进
- M3 上来先把 `manual` 跑通（拆页 + 缩略图对照录入）
- 你拿到 ANTHROPIC_API_KEY 后再切 `OCR_PROVIDER=claude`，**无需改前端**
- 后端在 startup 检测 key 是否存在，前端拉一个 `/api/intake/capabilities` 决定是否显示"AI 自动识别"按钮

---

## 12. 风险与权衡

| 风险 | 影响 | 缓解 |
|---|---|---|
| 后端进程崩溃用户不易发现 | 前端 fetch 失败黑屏 | `start.sh` 加健康检查；前端顶部加"后端状态"指示灯 |
| SQLite 单文件损坏 | 数据丢失 | 启动时自动备份近 7 份 `math.db.YYYYMMDD.bak`；md 是知识点权威源可重建 |
| 知识点 md 重排导致 slug 变化 | 旧链接、旧题目关联失效 | id 公式严格沿用 `slugify('book-chapter-title-index')`；变更时检测并提示 |
| OCR 准确率不可控 | 录题脏数据 | 强制经过"预览校对"步骤，禁止直跳入库 |
| 自适应推荐冷启动 | 数据少推不准 | <30 个 attempts 时退化为"按知识点轮询" |
| 用户主观题判分主观 | 学情失真 | 提供"自评 1-5"+ M3 后可选 LLM 辅助判分 |
| 端口冲突（8000 已用） | 启动失败 | 沿用现 `PORT` 环境变量逻辑，后端用 `BACKEND_PORT` |
| 项目内中文文件名 | shell 处理需引号 | 路径常量化，避免 shell 拼接 |

---

## 13. 后续可选演进

仅作记录，不在本次范围。

- **多端同步**：B → C（Supabase / Cloudflare D1）
- **LLM 主观题判分**：用 Claude 给出"对/部分对/错 + 反馈"
- **试卷生成**：按知识点 + 难度自动组卷输出 PDF
- **错题导出**：错题集导出为 PDF / Anki 牌组
- **学习计划**：基于薄弱点 + 考试日期生成周计划
- **移动端**：PWA 化（标记图标 + 离线缓存）

---

## 14. 决策记录

| 决策点 | 选择 | 决策时间 |
|---|---|---|
| 使用场景 | 单设备自用 | 2026-05-27 |
| 题目录入 | 优先 PDF/图片 OCR | 2026-05-27 |
| 本地后端 | 接受，start.sh 一并拉起 | 2026-05-27 |
| 学情粒度 | 高阶 - 自适应推荐 | 2026-05-27 |
| API key | 暂无，M3 走降级方案 | 2026-05-27 |
| 实施动作 | 先出本文档，待评审 | 2026-05-27 |

---

## 15. 待评审 / 待补充

- [ ] 题目入库去重策略：仅按 `hash(stem_md)` 还是要做近似查重？
- [ ] 是否需要"知识点笔记"功能（用户在知识点页加私人笔记）？
- [ ] 错题"已掌握"判定：纯手工标 vs 自动判定（连续 N 次正确）？
- [ ] 是否要做"每日打卡"/"做题日历"等激励元素？
- [ ] M3 OCR：是否需要处理手写体（如手写错题集图片）？
- [ ] 数据备份策略：自动 vs 手动？是否要导出可读 JSON？

---

> 评审通过后从 M0 开始执行；每个 milestone 完成后回到本文件勾选并记录实际工时。
