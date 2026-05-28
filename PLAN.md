# 高一数学知识库 → 个人薄弱图谱 + 题库 + 自适应训练 重构实施方案

> 状态：方案稿（v2） · M0 POC 已完成 · 待执行
> 决策：单设备自用 / 基础学习图谱 + 个人薄弱图谱 / PDF 图片 OCR 录题 / 本地后端 / 自适应推荐 / 暂无 ANTHROPIC_API_KEY（M3 提供降级）

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
2. **基础学习图谱**：把知识点、题型、解题技巧、通用易错点、题目之间的关系显式建模，不把它们误当成单棵章节树。
3. **个人薄弱图谱 + 学情分析**：记录做题历史、错因诊断与个人易错模式，识别“我真正弱在哪里”，而不仅是统计章节错误率。
4. **自适应训练**：根据个人薄弱图谱自动推荐下一题，把训练集中在最能提升个人复习效率的弱点。

### 1.3 范围与边界
- **单用户、单设备**（本地 SQLite 即可）
- **不引入前端框架**，保持 vanilla JS + MathJax，避免构建工具
- **不引入云依赖**，但数据模型预留多端同步演进路径
- 录题方式：M1 手动 + M3 OCR 批量
- 不做账户系统、不做协作、不做移动端原生
- **不做通用学习辅助工具**：本项目优先服务单个使用者的个人薄弱点诊断、错题归因与高效率复习。通用知识点、通用题型和通用易错点只是底座，不是最终目标。

### 1.4 产品北极星

本项目的最关键目标是：**基于个人日常练习与错题，归纳个人薄弱点，并生成针对性的强化复习训练建议，从而提升复习效率**。

因此所有功能优先级按以下顺序判断：

1. 能否更准确地定位个人薄弱点。
2. 能否解释为什么推荐这些题、这些题型或这些知识点。
3. 能否减少无效刷题，把训练集中在个人反复出错或尚未掌握的节点。
4. 能否沉淀长期可用的个人学习轨迹。
5. 最后才是通用资料浏览、通用题库查询和泛化学习辅助。

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
│                                  ├── graph_builder       │
│                                  ├── weakness_engine     │
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
- SQLite 中同时维护两层图：
  - **基础学习图谱 Base Graph**：知识点、题型、技巧、通用易错点、题目之间的关系。
  - **个人薄弱图谱 Personal Graph**：基于 attempts/mistakes/diagnoses 形成的个人薄弱节点、掌握度、证据和复习优先级。

### 3.1 图谱心智模型

章节目录只是内容入口，不是训练决策模型。训练决策应基于图谱：

```
知识点 ── supports/tests ── 题型 ── uses ── 技巧
  │                         │
  │                         └── has_pitfall ── 通用易错点
  │
题目 ── tests ── 知识点 / 题型 / 技巧 / 易错点
  │
做题记录 / 错题诊断 ── evidence_for ── 个人薄弱点
  │
推荐器 ── targets ── 最值得强化的个人薄弱点
```

M0 POC 结论：

- 现有知识点 md 可稳定转成 56 个知识点行，无重复 ID。
- docx 讲义可抽取“题型 + 技巧 + 易错点 + 典例/变式”结构。
- 对真实讲义中 24 道典例/变式，规则 Top3 关联命中率约 87.5%，说明“Top-K 候选 + 人工/LLM 校对”路径可行。
- 同一题型常同时关联多个知识点，尤其“平面向量模长/最值/共线”会横跨 6.1/6.2/6.3/6.4，不能用单棵树表达。

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
基础学习图谱：

knowledge_points ──N:N── question_patterns ──N:N── skills
        │                       │
        │                       └──N:N── common_pitfalls
        │
        └──N:N── questions ──N:N── question_patterns
                         │
                         ├──N:N── skills / common_pitfalls
                         └──1:N── attempts

个人薄弱图谱：

attempts ──1:N── mistake_diagnoses ── evidence_for ── personal_weaknesses
   │                                      │
   └── upsert mistakes                    └── target_type: kp / pattern / skill / pitfall

recommender ◄── personal_weaknesses + review_queue + recent attempts
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

-- 题目形式字典：选择 / 填空 / 解答等。注意：训练意义上的“题型”使用 question_patterns。
CREATE TABLE question_formats (
  id   INTEGER PRIMARY KEY,
  name TEXT NOT NULL UNIQUE              -- 选择 / 填空 / 解答 / 证明 / 作图
);

-- 题目
CREATE TABLE questions (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  source        TEXT,                    -- 试卷名/页码：'2024 期中卷-第3题'
  format_id     INTEGER REFERENCES question_formats(id),
  difficulty    INTEGER,                 -- 1-5
  stem_md       TEXT NOT NULL,           -- 题干 markdown + LaTeX
  options_json  TEXT,                    -- 选择题：[{"key":"A","text":"..."}, ...]
  answer_key_json TEXT,                  -- 结构化答案；客观题自动判分用，如 {"kind":"single","value":"A"}
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

-- 题型 / 技巧 / 通用易错点：基础学习图谱节点
CREATE TABLE question_patterns (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  name         TEXT NOT NULL,             -- 如：利用共线向量基本定理求参数
  strategy_md  TEXT,                      -- 解题技巧/常用路径
  source       TEXT,                      -- 讲义、人工录入、OCR/LLM 等
  order_index  INTEGER,
  created_at   DATETIME NOT NULL,
  updated_at   DATETIME NOT NULL
);

CREATE TABLE skills (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  name        TEXT NOT NULL UNIQUE,       -- 如：系数比较、首尾相接、构造向量等
  content_md  TEXT,
  created_at  DATETIME NOT NULL,
  updated_at  DATETIME NOT NULL
);

CREATE TABLE common_pitfalls (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  name        TEXT NOT NULL UNIQUE,       -- 通用易错点，如：忽略零向量/非零条件
  content_md  TEXT,
  created_at  DATETIME NOT NULL,
  updated_at  DATETIME NOT NULL
);

CREATE TABLE pattern_kp (
  pattern_id INTEGER REFERENCES question_patterns(id) ON DELETE CASCADE,
  kp_id      TEXT REFERENCES knowledge_points(id),
  weight     REAL DEFAULT 1.0,
  relation   TEXT DEFAULT 'tests',        -- tests / requires / extends
  PRIMARY KEY (pattern_id, kp_id, relation)
);

CREATE TABLE pattern_skills (
  pattern_id INTEGER REFERENCES question_patterns(id) ON DELETE CASCADE,
  skill_id   INTEGER REFERENCES skills(id) ON DELETE CASCADE,
  weight     REAL DEFAULT 1.0,
  PRIMARY KEY (pattern_id, skill_id)
);

CREATE TABLE pattern_pitfalls (
  pattern_id INTEGER REFERENCES question_patterns(id) ON DELETE CASCADE,
  pitfall_id INTEGER REFERENCES common_pitfalls(id) ON DELETE CASCADE,
  weight     REAL DEFAULT 1.0,
  PRIMARY KEY (pattern_id, pitfall_id)
);

CREATE TABLE question_patterns_map (
  question_id INTEGER REFERENCES questions(id) ON DELETE CASCADE,
  pattern_id  INTEGER REFERENCES question_patterns(id) ON DELETE CASCADE,
  weight      REAL DEFAULT 1.0,
  is_primary  INTEGER DEFAULT 0,
  PRIMARY KEY (question_id, pattern_id)
);

CREATE TABLE question_skills (
  question_id INTEGER REFERENCES questions(id) ON DELETE CASCADE,
  skill_id    INTEGER REFERENCES skills(id) ON DELETE CASCADE,
  weight      REAL DEFAULT 1.0,
  PRIMARY KEY (question_id, skill_id)
);

CREATE TABLE question_pitfalls (
  question_id INTEGER REFERENCES questions(id) ON DELETE CASCADE,
  pitfall_id  INTEGER REFERENCES common_pitfalls(id) ON DELETE CASCADE,
  weight      REAL DEFAULT 1.0,
  PRIMARY KEY (question_id, pitfall_id)
);

-- 自由标签：高频考点 / 二级结论 / 易错型 / 压轴 等
CREATE TABLE question_tags (
  question_id  INTEGER REFERENCES questions(id) ON DELETE CASCADE,
  tag          TEXT NOT NULL,
  PRIMARY KEY (question_id, tag)
);

-- 每次做题记录
CREATE TABLE attempts (
  id                 INTEGER PRIMARY KEY AUTOINCREMENT,
  question_id        INTEGER REFERENCES questions(id),
  is_correct         INTEGER NOT NULL,      -- 0/1
  self_rating        INTEGER,               -- 主观题自评 1-5
  time_spent_sec     INTEGER,
  user_answer_md     TEXT,
  answer_image_path  TEXT,                  -- 拍照沉淀错题时的作答原图，纯线上做题为 NULL
  source             TEXT NOT NULL DEFAULT 'practice',  -- 'practice'（线上做题）/ 'photo_intake'（拍照沉淀）
  attempted_at       DATETIME NOT NULL
);

CREATE INDEX idx_attempts_qid_time ON attempts(question_id, attempted_at);

-- 错因诊断：把一次错误归因到知识点/题型/技巧/易错点/自定义个人问题
-- 采用四列互斥可空 FK（exclusive arc），CHECK 保证有且只有一个目标，
-- 避免多态外键导致的类型不一致和孤儿行问题。
CREATE TABLE mistake_diagnoses (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  attempt_id    INTEGER NOT NULL REFERENCES attempts(id) ON DELETE CASCADE,
  kp_id         TEXT    REFERENCES knowledge_points(id)  ON DELETE CASCADE,
  pattern_id    INTEGER REFERENCES question_patterns(id) ON DELETE CASCADE,
  skill_id      INTEGER REFERENCES skills(id)            ON DELETE CASCADE,
  pitfall_id    INTEGER REFERENCES common_pitfalls(id)   ON DELETE CASCADE,
  custom_label  TEXT,                     -- 当本次错因不属于已有节点时使用
  note_md       TEXT,
  confidence    REAL DEFAULT 1.0,
  source        TEXT NOT NULL,            -- manual / rule / llm
  created_at    DATETIME NOT NULL,
  CHECK (
    (kp_id        IS NOT NULL) +
    (pattern_id   IS NOT NULL) +
    (skill_id     IS NOT NULL) +
    (pitfall_id   IS NOT NULL) +
    (custom_label IS NOT NULL) = 1
  )
);

CREATE INDEX idx_diag_attempt ON mistake_diagnoses(attempt_id);
CREATE INDEX idx_diag_kp      ON mistake_diagnoses(kp_id)      WHERE kp_id      IS NOT NULL;
CREATE INDEX idx_diag_pattern ON mistake_diagnoses(pattern_id) WHERE pattern_id IS NOT NULL;
CREATE INDEX idx_diag_skill   ON mistake_diagnoses(skill_id)   WHERE skill_id   IS NOT NULL;
CREATE INDEX idx_diag_pitfall ON mistake_diagnoses(pitfall_id) WHERE pitfall_id IS NOT NULL;

-- 错题集（每题最多一行；wrong_count 累加）
CREATE TABLE mistakes (
  question_id      INTEGER PRIMARY KEY REFERENCES questions(id) ON DELETE CASCADE,
  first_wrong_at   DATETIME NOT NULL,
  last_wrong_at    DATETIME NOT NULL,
  wrong_count      INTEGER NOT NULL DEFAULT 1,
  last_attempt_id  INTEGER REFERENCES attempts(id),
  note_md          TEXT,                 -- 个人复盘笔记
  mastered_at      DATETIME,             -- 标"已掌握"后填，否则 NULL；仅手工写入
  mastered_source  TEXT,                 -- 'manual'，预留 'auto'；v1 只写 'manual'
  mastered_streak  INTEGER NOT NULL DEFAULT 0  -- 连续正确次数；做对 ++ / 做错归零；UI 触发"建议已掌握"提示
);

-- 个人薄弱点：推荐与学情的核心表，不等同于通用易错点
-- 同样采用四列互斥可空 FK，与 mistake_diagnoses 保持一致，便于 weakness_engine 直接 join 累加证据
CREATE TABLE personal_weaknesses (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  kp_id           TEXT    REFERENCES knowledge_points(id)  ON DELETE CASCADE,
  pattern_id      INTEGER REFERENCES question_patterns(id) ON DELETE CASCADE,
  skill_id        INTEGER REFERENCES skills(id)            ON DELETE CASCADE,
  pitfall_id      INTEGER REFERENCES common_pitfalls(id)   ON DELETE CASCADE,
  custom_label    TEXT,                    -- 与 mistake_diagnoses.custom_label 语义对齐
  title           TEXT NOT NULL,           -- 冗余字段：节点名快照，便于列表/解释直接展示
  strength        REAL NOT NULL DEFAULT 0, -- 0-1，越高越需要强化
  mastery         REAL NOT NULL DEFAULT 0, -- 0-1，越高越掌握
  evidence_count  INTEGER NOT NULL DEFAULT 0,
  last_seen_at    DATETIME,
  updated_at      DATETIME NOT NULL,
  CHECK (
    (kp_id        IS NOT NULL) +
    (pattern_id   IS NOT NULL) +
    (skill_id     IS NOT NULL) +
    (pitfall_id   IS NOT NULL) +
    (custom_label IS NOT NULL) = 1
  )
);

-- 每种目标类型各一个部分唯一索引，保证一个节点最多一行 personal_weaknesses
CREATE UNIQUE INDEX uq_pw_kp      ON personal_weaknesses(kp_id)        WHERE kp_id        IS NOT NULL;
CREATE UNIQUE INDEX uq_pw_pattern ON personal_weaknesses(pattern_id)   WHERE pattern_id   IS NOT NULL;
CREATE UNIQUE INDEX uq_pw_skill   ON personal_weaknesses(skill_id)     WHERE skill_id     IS NOT NULL;
CREATE UNIQUE INDEX uq_pw_pitfall ON personal_weaknesses(pitfall_id)   WHERE pitfall_id   IS NOT NULL;
CREATE UNIQUE INDEX uq_pw_custom  ON personal_weaknesses(custom_label) WHERE custom_label IS NOT NULL;

CREATE INDEX idx_weakness_strength ON personal_weaknesses(strength DESC, last_seen_at DESC);

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

**方案：手写 SQL migrations + 极简 runner。** 不引入 Alembic。

#### 5.3.1 选择理由

- 单设备自用，没有多环境协同需求，Alembic 真正解决的问题（多环境、回滚、分支合并）在这里价值接近 0。
- SQLite 几乎不支持 `ALTER TABLE`（drop column / change type / pre-3.25 的 rename column），Alembic 的 autogenerate 在 SQLite 下经常需要手改并走 `batch_alter_table` 的"建新表→拷数据→删旧→重命名"流程，省不下多少功夫。
- 知识点可以从 md 重建，但 `attempts` / `mistakes` / `mistake_diagnoses` / `personal_weaknesses` 是用户真实产出的数据，**不能依赖"丢库重建"**，必须有正式的迁移机制。
- 手写 SQL 与 §5.2 的 DDL 形态一致，可读性高；runner 实现约 30 行，零外部依赖。

#### 5.3.2 目录与命名约定

```
backend/
  migrations/
    0001_initial.sql       # 把 §5.2 全部 DDL 贴入
    0002_add_fts.sql       # questions_fts / kp_fts + ai/ad/au 触发器
    0003_xxx.sql           # 按 milestone 演进
  db.py                    # 含 run_migrations()
  models.py                # SQLModel 运行时实体（不参与建表）
```

- 文件名严格 `NNNN_短描述.sql`，4 位数字保证字典序 = 执行序。
- 每个文件**整体一个事务**，失败自动回滚。
- 用 SQLite 的 `executescript` 一次执行多语句，不要按 `;` 切。

#### 5.3.3 runner 行为

启动时调用 `run_migrations(engine, migrations_dir)`：

1. `CREATE TABLE IF NOT EXISTS schema_migrations (version TEXT PRIMARY KEY, applied_at DATETIME NOT NULL)`。
2. 扫描 `migrations_dir/[0-9][0-9][0-9][0-9]_*.sql`，按文件名排序。
3. 对每个未应用版本：先 `cp math.db math.db.before-NNNN.bak`（与 §12 备份策略合一），再在一个事务里执行整文件，最后写入 `schema_migrations`。
4. 任何一步失败 → 事务回滚 → 启动失败，要求人工介入；**绝不**自动跳过。

#### 5.3.4 SQLModel 与 SQL 的源关系

- `migrations/*.sql` 是 schema 的**唯一权威源**。
- `models.py` 中的 SQLModel 实体只作为运行时 ORM/查询/序列化，**不参与建表**：不要写会影响建表的 `__table_args__`、`Field(..., primary_key=True, sa_column=...)` 等结构化定义；列层面与迁移保持一致即可。
- 新增/修改 schema 的提交流程：先写 migration → 跑通 → 再同步 `models.py`。

#### 5.3.5 防漂移检查（dev-only）

加一个 pytest 用例：

1. 建临时空 SQLite 库。
2. 跑全部 migrations。
3. 对每张表，用 SQLAlchemy `inspect(engine).get_columns(...)` 抓实际列，与 `models.py` 中对应 SQLModel 的字段列表比对（列名 + 基本类型）。
4. 不一致即失败，输出 diff。

不要求 100% 等价（NOT NULL / 默认值表达方式有差异），只要列名集合与基础类型一致就行。

#### 5.3.6 何时切回 Alembic

仅当下列条件之一成立时重新评估：

- §13 多端同步 / 迁到 Postgres 落地。
- schema 改动密度上升到一周 3+ 次。
- 协作者扩到 2+ 人，需要在 PR 中清晰看到 schema diff。

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
  "format_id": 1,
  "difficulty": 3,
  "stem_md": "已知 $f(x)=\\log_2(x-1)$，求定义域。",
  "options_json": null,
  "answer_key_json": null,
  "answer_md": "$\\{x \\mid x > 1\\}$",
  "solution_md": "...",
  "kp_ids": [
    {"id": "k-abc123", "weight": 1.0, "is_primary": true},
    {"id": "k-def456", "weight": 0.6, "is_primary": false}
  ],
  "tags": ["定义域陷阱","易错型"]
}
```

### 6.3 流程 C：资料结构化导入（M1–M3）

资料导入分两条管线：

1. **结构化讲义 / DOCX 导入**：优先利用文档已有结构，抽取题型、解题技巧、易错点、典例/变式、答案、解析。
2. **PDF / 图片 OCR 导入**：当资料没有可读结构时，先转图片，再由 manual/LLM provider 识别。

#### 6.3.1 DOCX 讲义题型抽取（POC 已验证）

本次 POC 使用 `poc/docx_typical_questions.py` 处理《培优01平面向量的概念及线性运算（含共线向量定理）（期末复习讲义）解析版.docx》，流程如下：

```
DOCX
  ├─ 读取 word/document.xml
  ├─ 抽取 w:t + m:t 文本节点（保留普通文本与部分 Office Math 文本）
  ├─ 定位“题型一/题型二/...”段落
  ├─ 抽取“解｜题｜技｜巧”“易｜错｜点｜拨”
  ├─ 抽取【典例】【变式】+【答案】+【详解】
  ├─ 排除“期末基础通关练 / 期末重难突破练”等非题型训练区
  ├─ 生成中间题目 markdown：source/stem/answer/solution/expected_kp
  └─ 喂给 Top-K 图谱关联 POC，输出可审报告
```

POC 结果：

- 抽取 8 个题型、24 道典例/变式。
- 题目到知识图谱 Top3 命中率约 87.5%。
- 暴露出“题型/技巧/易错点”应成为基础学习图谱节点，而不是塞进章节树。
- Word 公式对象在纯文本抽取中仍可能丢符号；后续系统化时，抽取结果必须进入预览校对页，不允许直入库。

系统化建议：

- 将 POC 脚本沉淀为 `backend/services/importers/docx_handout.py`。
- 中间产物统一为 `ParsedLearningMaterial`：
  - `patterns[]`：题型、策略、易错点。
  - `questions[]`：题干、答案、解析、来源位置。
  - `candidate_edges[]`：知识点/题型/技巧/易错点 Top-K 候选。
- 前端复用 intake 预览页，允许逐题校正题型、技巧、易错点和知识点关联。
- 后续可扩展到普通 `.docx`、OCR 后的 markdown、网页复制文本等输入。

#### 6.3.2 OCR 批量录题（M3）

```
上传 PDF/图片
  ├─ PyMuPDF 拆页 → 每页 PNG (300dpi)
  ├─ 调用 OCR provider（详见 §11 降级方案）
  │   └─ 输出结构化 JSON（按入库目的两种 schema）：
  │      ParsedQuestion（新题入库）：
  │        [{stem, type, options, answer?, solution?, kp_ids[], tags[], difficulty}]
  │      ParsedMistake（错题沉淀，见 §6.3.3）：
  │        [{question: ParsedQuestion,
  │          user_answer_md?, user_answer_image_path?,
  │          is_correct (默认 0), mistake_hints[],
  │          attempted_at (默认 today)}]
  ├─ 前端"批量预览"页：逐题校对/修改，可直接拖动重排题号
  └─ 一键入库（事务，按 schema 走 §7.4 对应 commit 端点）
```

**关键 prompt 设计**（当 LLM provider 启用时）：
- system prompt 注入**全部 knowledge_points 列表**（id + book/chapter/section + title），强制模型只能从中选 id
- 输出格式锁死 JSON schema（用 Anthropic tool use 强制）
- 大试卷分 batch（一次 5 题），降低单次 token 与失败成本
- 错题沉淀路径额外要求识别"作答区域"（通常是手写）并落入 `user_answer_md`；手写体识别能力是 M3 前置（§11.3）

#### 6.3.3 错题拍照沉淀（M3）

学生大量练习发生在纸面，错题往往在事后整理时一次性拍照上传。这条流程把"我做错了"作为一等公民语义，**跳过线上做题环节**，直接构造一条 `attempts(is_correct=0)` + `mistakes` 入库。

**入口**：`[录题]` tab 内 sub-tab `错题沉淀`，与 `新题入库` 并列，共享 OCR provider 与预览组件，但走独立 commit。

**主流程**：

```
进入 [录题 / 错题沉淀] sub-tab
  → 拖入或拍照 1..N 张错题图（也支持 PDF 多页）
  → 后端拆页 → OCR provider 输出 ParsedMistake[]（§6.3.2）
      ├─ 题干区域           → ParsedQuestion.stem
      ├─ 我的作答（手写区）  → user_answer_md（手写体走 claude vision；manual 降级为空）
      └─ 标准答案/解析（若有）→ ParsedQuestion.answer / solution
  → 前端"批量预览"页（左原图、右结构化字段）
      逐条校对：
        ├─ 题干              [可编辑]
        ├─ 我的作答          [可编辑，允许留空]
        ├─ 标准答案          [可编辑，允许留空]
        ├─ 对错判定          ◉ 错  ○ 对  ○ 部分对（默认勾"错"）
        ├─ 题库匹配          hash(stem_md) 命中 → "复用现有题《...》" / "作为新题入库"
        ├─ 知识点/题型/技巧/易错点 候选 chips（Top-3，可改）
        └─ 错因区（"我错在..."，详见下方 UI 段）
  → 用户点「全部确认并提交」
      → POST /api/intake/mistakes/commit（事务）
          ├─ 题目：复用 or 新建 questions（+ question_kp / question_patterns_map 等图谱边）
          ├─ 写 attempts(is_correct=0, user_answer_md, answer_image_path, source='photo_intake', attempted_at)
          ├─ upsert mistakes（wrong_count++，last_wrong_at=attempted_at，mastered_streak=0）
          ├─ 写 mistake_diagnoses（规则归因 + 用户勾的 manual 归因，source 字段保留三档语义）
          └─ weakness_engine 对每个关联节点应用 wrong 事件（§16.3）
  → 弹 toast：「已沉淀 N 题。命中个人薄弱点：X / Y / Z」并提供 "查看薄弱图谱" 链接
```

**错因 UI（与 §6.4 做题页共享组件）**：

```
我错在...（多选）

[ 规则归因 · 自动 ]
  ☐ <kp 候选>      ☐ <pattern 候选>      ☐ <skill 候选>

[ 易错点候选 · OCR/规则推断 ]
  ☐ <pitfall 候选 1>   ☐ <pitfall 候选 2>

[ 我的常见错因 · 历史 Top-10 ]   ← 拉取该用户 personal_weaknesses Top-10
  ☐ <跨 kp/pattern/skill/pitfall 的高 strength 节点>

[ + 自定义错因 ]   ← 自由输入，落 custom_label

[ 复盘笔记（可选） ]  ← 落 mistakes.note_md
```

**批量场景**：多张图一次提交时，预览页变成卡片栈（左缩略图列表、右当前题表单）。每张卡片状态：`待确认` / `已确认` / `已跳过` / `解析失败`。默认"待确认"，强制用户至少扫一眼，避免 OCR 误识被一键污染薄弱图谱。

**默认交互决策（v1）**：

| # | 问题 | 默认 |
|---|---|---|
| D1 | "我的作答"是否必填 | 不必填；空则 `user_answer_md = NULL` 但仍写 attempts |
| D2 | 手写体 OCR 失败 | 留空 + 显示原图，用户可选"手打补全"或"跳过作答"，不卡流程 |
| D3 | 题库去重 | M1: `hash(stem_md)` 精确匹配；M3+: 增加 embedding 近似 (cosine > 0.92) |
| D4 | 对错判定默认值 | 默认勾"错"——该 sub-tab 语义即"我错了" |
| D5 | 无标准答案 | 允许为空；`is_correct=0` 由用户声明，不依赖答案对照判分 |
| D6 | 同一题反复拍 | 检测 mistakes 已存在 → 提示"第 N 次错"，仍写新 attempts，wrong_count++ |
| D7 | 错因区"历史 Top" | 取该用户 personal_weaknesses.strength 跨 kp/pattern/skill/pitfall Top-10 |

**审计与解释链**：

- `attempts.answer_image_path` 保留原图，作为推荐解释链中"原始证据"一环（§7.7 / M4）。
- `mistake_diagnoses.source` 字段在拍照流程中可取值 `rule` / `manual` / `llm`；不新增 `photo_intake` 值——"来源是拍照"由 `attempts.source='photo_intake'` 表达，避免与归因来源混淆。
- `attempts.attempted_at` 在拍照流程中由用户标注的做题日期决定（默认 today，可改），用于学情时间线准确性。

### 6.4 流程 D：做题与错题（M2）

```
进入做题页（单题模式 / 套题模式）
  → 计时开始
  → 用户作答（客观题选项 / 主观题 markdown 输入）
  → 提交
    ├─ 客观题：自动判对错
    └─ 主观题：用户自评 1-5（M3 后可选 LLM 判分）
  → 写 attempts
  → 若 is_correct = 0：
      ├─ upsert mistakes（wrong_count++，last_wrong_at=now，mastered_streak=0）
      └─ 生成/补充 mistake_diagnoses（每行只填 kp_id / pattern_id / skill_id / pitfall_id / custom_label 中的一个）
          ├─ 默认规则归因：题目关联的 kp / pattern / skill / pitfall 各生成一行
          ├─ 用户手动归因：选择”我错在...”或写复盘；不匹配现有节点时填 custom_label
          └─ M3 后可选 LLM 辅助归因，写入时携带 confidence 与 source='llm'
  → 若 is_correct = 1 且该题已有 mistakes 行：mastered_streak += 1
  → 更新 personal_weaknesses（按事件类型应用增减，详见 §16）
  → 更新 review_queue（SM-2 算法，M5）

另一条独立写入路径：用户主动标"已掌握"
  → PATCH /api/mistakes/{qid} { mastered: true }
    ├─ mastered_at = now, mastered_source = 'manual'
    ├─ 对该题每个关联节点应用 master 事件 delta（一次性，详见 §16）
    └─ 不写 attempts，不改 wrong_count / mastered_streak

取消已掌握：
  → PATCH /api/mistakes/{qid} { mastered: false }
    ├─ mastered_at = NULL, mastered_source = NULL
    └─ 不反向扣减 master_bonus（保留审计字段一致性；未来错/对会自然推回）
```

"已掌握"判定原则（v1）：

- mastered_at 是该题"是否仍在错题集"的唯一权威，**仅由用户手工写入**。
- 系统在 UI 上根据 mastered_streak 与 attempts 时间分布做"建议已掌握"提示
  （阈值见 §16），但不替用户落库。
- 这条边界来自项目北极星：用户对自己掌握度的判断比任何启发式都强；
  系统的职责是别让用户漏标，而不是替他决定。

个人归因优先级：

1. `manual` 用户手动标注最可信。
2. `llm` 基于错解/解析推断，需显示为可修改建议。
3. `rule` 基于题目关联图谱自动扩散，是兜底证据。

做错一题时，不能只把错误记到章节知识点；应按权重扩散到个人薄弱节点：

```
错题 → 知识点 +0.3
错题 → 题型   +0.5
错题 → 技巧   +0.6
错题 → 易错点 +0.8
```

连续做对、标记掌握或复习过期后重新答对，应降低对应 `personal_weaknesses.strength`，提升 `mastery`。

### 6.5 流程 E：自适应推荐（M5）

打分公式（首版，以个人薄弱图谱为核心）：
```
score(q) = 0.35 * personal_weakness(q)
         + 0.25 * due_review(q)
         + 0.20 * pattern_gap(q)
         + 0.10 * novelty(q)
         + 0.10 * difficulty_fit(q)
         - 0.20 * recent_seen_penalty(q)

personal_weakness(q) = max/weighted_mean strength over q's kp/pattern/skill/pitfall nodes
due_review(q)        = max(0, (now - review_queue.due_at).days) / 7
pattern_gap(q)       = weakness of linked question_patterns not recently practiced
novelty(q)           = 1 if never attempted else 0
difficulty_fit(q)    = match between current mastery and question difficulty
recent_seen_penalty  = 1 if attempted in last 24h else 0
```

每次"开始智能练习"取 Top-K（带轻微随机扰动），保证不会反复推同一题。推荐结果必须能解释：

- 命中了哪些个人薄弱点。
- 为什么现在复习它。
- 这道题覆盖的知识点/题型/技巧/易错点是什么。
- 做完后会如何更新个人薄弱图谱。

### 6.6 流程 F：学情仪表盘（M4）

- **个人薄弱 Top 10**：按 `personal_weaknesses.strength * evidence_count` 排序，覆盖知识点/题型/技巧/个人易错点。
- **知识点热力图**：章节树 + 每节涂色（绿/黄/红，基于个人薄弱图谱而不是单纯错误率）
- **题型雷达**：题型掌握度与近期练习覆盖率
- **个人易错模式**：反复出现的手动/规则/LLM 错因，如“忽略非零条件”“系数和为 1 的同起点条件”
- **错题趋势**：按周聚合 `mistakes.first_wrong_at`
- **一键针对训练**：选个人薄弱点 → 沿图谱扩散到相关题型/题目 → 抽 10 道题 → 进入做题流

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
GET    /api/questions                 # ?kp=...&pattern=...&skill=...&pitfall=...&difficulty=...&q=...&page=
GET    /api/questions/{id}
POST   /api/questions                 # 录入
PATCH  /api/questions/{id}            # 修改
DELETE /api/questions/{id}
GET    /api/questions/{id}/related    # 同知识点/题型/技巧/易错点的题
```

### 7.3 基础学习图谱
```
GET  /api/graph/kp/{id}               # 知识点邻接：题型/技巧/易错点/题目
GET  /api/graph/patterns              # 题型列表，可按 kp 筛选
GET  /api/graph/patterns/{id}         # 题型详情：关联知识点、技巧、易错点、典例
POST /api/graph/patterns              # 手动维护题型
POST /api/graph/edges                 # 手动/LLM 校正图谱边
```

`POST /api/graph/edges` 使用统一 payload，但后端只允许白名单组合，并落到具体关系表：

```json
{
  "from_type": "pattern",
  "from_id": 12,
  "to_type": "kp",
  "to_id": "k-qhiyx0",
  "relation": "tests",
  "weight": 0.9
}
```

v1 白名单：

| from_type | to_type | relation | 落表 |
|---|---|---|---|
| pattern | kp | tests / requires / extends | `pattern_kp` |
| pattern | skill | uses | `pattern_skills` |
| pattern | pitfall | has_pitfall | `pattern_pitfalls` |
| question | kp | tests | `question_kp` |
| question | pattern | belongs_to | `question_patterns_map` |
| question | skill | uses | `question_skills` |
| question | pitfall | has_pitfall | `question_pitfalls` |

非法组合返回 400，不写通用 `graph_edges` 表。这样保留统一 API，同时保持数据库 schema 可约束、可 join。

### 7.4 录题 / OCR
```
POST /api/intake/upload                 # multipart: pdf / image / docx；返回 upload_id + detected_kind
POST /api/intake/parse                  # { upload_id, schema: "question"|"mistake" } → 异步任务 id
GET  /api/intake/parse/{task_id}        # 拉取解析结果（ParsedQuestion[] 或 ParsedMistake[]）
POST /api/intake/import/docx            # DOCX 讲义结构化导入：upload_id → ParsedLearningMaterial 预览数据
POST /api/intake/questions/commit       # 新题入库（schema=question 走此处）
POST /api/intake/mistakes/commit        # 错题沉淀（schema=mistake 走此处）：
                                         #   body: ParsedMistake[]（含 question, user_answer_md?,
                                         #         answer_image_path?, is_correct, mistake_hints[],
                                         #         attempted_at）
                                         #   事务内：upsert questions → 写 attempts(source='photo_intake')
                                         #        → upsert mistakes → 写 mistake_diagnoses
                                         #        → 触发 weakness_engine wrong 事件
                                         #   响应：{ committed_n, matched_weaknesses: [{title, type, strength}] }
GET  /api/intake/capabilities           # 返回当前 OCR provider 能力（含 supports_handwriting: bool）
```

### 7.5 做题、错题与个人归因
```
POST  /api/attempts                    # 提交一次作答；is_correct=0 触发 wrong 事件链，=1 触发 correct 事件链
GET   /api/mistakes                    # 错题列表（默认仅未掌握；?include_mastered=1 翻出已掌握）
PATCH /api/mistakes/{qid}              # body: { note_md?, mastered?: boolean }
                                       #   mastered=true  → 写 mastered_at / mastered_source='manual'，触发 master 事件
                                       #   mastered=false → 清空 mastered_at / mastered_source，不反向扣减
                                       #   note_md        → 仅更新复盘笔记
GET   /api/attempts/{id}/diagnoses     # 本次错误归因
POST  /api/attempts/{id}/diagnoses     # 添加/修正个人错因
```

### 7.6 推荐 / 训练
```
POST /api/practice/next               # { mode: "smart"|"weakness"|"by_kp"|"by_pattern", target?, count }
POST /api/practice/session/start
POST /api/practice/session/{id}/end
```

### 7.7 学情 / 个人薄弱图谱
```
GET /api/stats/heatmap                # 基于个人薄弱图谱的知识点热力图
GET /api/stats/weak_top               # 个人薄弱 Top N，跨 kp/pattern/skill/pitfall
GET /api/stats/weaknesses/{id}        # 薄弱点详情、证据、建议训练
GET /api/stats/trend?period=week      # 错题/掌握度趋势
GET /api/stats/type_radar             # 题型掌握度
GET /api/stats/personal_pitfalls      # 个人反复易错模式
```

---

## 8. 前端改造

### 8.1 导航结构
顶部加 6 个 tab：
```
[知识点]  [题库]  [录题]  [练习/错题]  [图谱]  [学情]
```

### 8.2 视图职责

| 视图 | 文件 | 职责 |
|---|---|---|
| 知识点 | `views/kp.js` | **沿用现 app.js 90% 逻辑**，从 `/api/kp` 取数据 |
| 题库 | `views/questions.js` | 列表 + 多维筛选 + 详情抽屉 + 全文搜 |
| 录题 | `views/intake.js` | 顶部 sub-tab `新题入库` / `错题沉淀`。共享 OCR provider 与预览组件（左原图右结构化字段），但 commit 路径分流：前者走 `POST /api/intake/questions/commit`（仅进题库），后者走 `POST /api/intake/mistakes/commit`（同时构造 attempts + mistakes + 触发 weakness_engine，§6.3.3） |
| 练习 | `views/practice.js` | 错题列表 + 智能练习模式 + 单题作答 UI + 错因标注 |
| 图谱 | `views/graph.js` | 基础学习图谱局部邻接查看：知识点 ⇄ 题型 ⇄ 技巧/易错点 ⇄ 题目。v1 不做全量知识图谱总览，避免边过多导致不可读；全量概览作为最低优先级可选演进（见 §13） |
| 学情 | `views/dashboard.js` | 个人薄弱 Top10 + 题型掌握度 + 个人易错模式 + 训练入口 |

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
│   │   ├── graph.js
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
│   │   ├── graph.py
│   │   ├── intake.py
│   │   ├── practice.py
│   │   ├── stats.py
│   │   └── admin.py
│   ├── services/
│   │   ├── kp_sync.py          # md → DB
│   │   ├── graph_builder.py    # 知识点/题型/技巧/易错点关系维护
│   │   ├── weakness_engine.py  # attempts + diagnoses → personal_weaknesses
│   │   ├── importers/
│   │   │   ├── docx_handout.py # 结构化讲义 → 题型/技巧/易错点/典例
│   │   │   └── schemas.py      # ParsedLearningMaterial 等中间结构
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
└── PLAN.md                     # 本文件
```

**.gitignore 新增**：`data/`、`.venv/`、`__pycache__/`、`.runtime/`、`backend/.env`

---

## 10. 分阶段实施 (M0–M5)

每个 milestone 独立可用、可停。完成顺序严格按 M0 → M5。

### M0：后端骨架 + 知识点同步

**交付**
- `backend/` 目录与 venv
- FastAPI + SQLModel + SQLite 跑通
- `migrations/0001_initial.sql` 建 §5.2 全部表、索引、约束（M0 只实现其中一部分服务逻辑，但 schema 一次落稳，减少 M1/M2 迁移噪声）
- `services/kp_sync.py` 把 md 解析入 `knowledge_points`
- 基础图谱相关表在 `0001_initial.sql` 中一并创建；M0 的 API 可只返回空邻接
- 保留 POC 脚本作为验收工具：知识点 md 结构化 + docx 题型抽取 + Top-K 关联报告
- `GET /api/kp`、`GET /api/kp/tree` 通
- `GET /api/graph/kp/{id}` 返回知识点局部邻接（M0 可先为空边）
- `start.sh` 改造为并行拉前后端

**验证**
- `curl http://127.0.0.1:8001/api/kp/tree` 返回完整章节树
- 前端原页面不动，仍正常工作
- DB 中知识点数 == 旧前端解析出的条目数
- POC 报告仍能证明 md → `knowledge_points` 稳定，无重复 ID
- docx 讲义样本能抽出题型/典例，并生成可审的 Top-K 关联结果

**预计**：0.5 天

---

### M1：题库 + 手动录题

**交付**
- `routers/questions.py` + CRUD
- 前端 `views/questions.js`（列表 + 筛选 + 详情）
- 前端 `views/intake.js`（手输表单：题干/答案/解析 markdown + 知识点/题型/技巧/易错点候选 + 难度）
- 基础学习图谱维护能力：题型、技巧、通用易错点可被题目复用
- 将 `poc/docx_typical_questions.py` 的方法迁移为导入服务雏形：DOCX 讲义 → 中间 markdown/JSON → intake 预览
- `views/kp.js` 接入后端，沿用现 UI
- 顶部 nav 路由切换

**验证**
- 手动录 5–10 道真题
- 在题库页按知识点、题型、技巧、易错点筛选都能命中
- 知识点详情页能列出该知识点关联的题目
- 同一题可挂多个图谱节点，且主考点/主题型可标记
- 能对 POC docx 讲义重复抽取题型、技巧、易错点和典例/变式，结果进入可审预览

**预计**：1–2 天

---

### M2：做题 + 错题集

**交付**
- 单题做题页（客观题选项、主观题 markdown 输入）
- `POST /api/attempts` + 自动写 `mistakes`
- `mistake_diagnoses`：每次错误可归因到知识点/题型/技巧/易错点/自定义个人问题
- `personal_weaknesses`：由错因诊断增量更新个人薄弱图谱
- 错题列表页（按知识点/题型/个人薄弱点筛、按错次排）
- 错题详情：再次作答 + 复盘笔记 + "我错在..." + "已掌握"开关

**验证**
- 做错的题立刻进错题集
- 同一题再错，`wrong_count` 累加，`last_wrong_at` 更新
- 手动标注错因后，相关 `personal_weaknesses.strength` 上升
- 连续做对或标"已掌握"后，相关薄弱点强度下降、掌握度上升
- 标"已掌握"后从默认列表消失，但可在"已掌握"tab 翻出

**预计**：1–2 天

---

### M3：OCR 批量录题 + 错题拍照沉淀

**前置条件**
- 若有 `ANTHROPIC_API_KEY` → 启用 `services/ocr/claude.py`（支持手写体识别）
- 若无 → 使用 `manual.py`：仅做 PDF 拆页 + 缩略图预览，用户在前端**逐图手输**（仍比纯手输方便：图固定在旁边对照）
- 题库去重决策已落（§15 第 1 项 / M1 前置）：错题沉淀复用题目时使用 `hash(stem_md)` 精确匹配
- `attempts.answer_image_path` / `attempts.source` 字段已在 M2 落库（§5.2）

**交付**
- 上传 PDF/图片接口
- 拆页 + 缩略图
- OCR provider 接口（base.py 定义 `parse(image_bytes, context) -> list[ParsedQuestion] | list[ParsedMistake]`，按 `context.target` 分发）
- provider capabilities 暴露 `supports_handwriting` 能力位
- 前端 `[录题]` tab 拆 sub-tab `新题入库` / `错题沉淀`，左侧图、右侧结构化字段，可改可删可重排
- 错题沉淀 sub-tab 额外字段：我的作答 / 标准答案 / 对错判定（默认"错"）/ 题库匹配复用 / 错因区（含历史 Top-10）
- 解析结果包含 Top-K 候选：知识点、题型、技巧、通用易错点
- 一键事务入库：
  - 新题：`POST /api/intake/questions/commit` → questions + 图谱边
  - 错题：`POST /api/intake/mistakes/commit` → questions(复用/新建) + attempts(source='photo_intake') + mistakes + mistake_diagnoses + weakness_engine 事件
- 将 DOCX 讲义导入和 OCR 导入统一到同一套 `ParsedLearningMaterial` 预览/提交流程

**验证（有 key 情况）**
- 一份 1 页期中卷 30 秒内出解析结果
- 解析准确率主观评估 > 80%，Top3 图谱候选准确率 > 70%
- 错题拍照：单张含印刷题干 + 手写作答 → 题干 OCR 准确率 > 85%，作答区识别成功率 > 70%；commit 后 `personal_weaknesses` 命中预期节点
- 同题第二次拍照沉淀 → mistakes.wrong_count 累加，不重复建题
- 七项默认决策（D1–D7，§6.3.3）在 UI 上各跑通一遍

**验证（无 key 降级情况）**
- 至少能拆页、把图按题分块、左右对照手输
- 错题沉淀 sub-tab 在 `supports_handwriting=false` 时仍可走完：user_answer_md 留空，主流程不卡

**预计**：有 key 2–3 天（新题入库 + 错题沉淀双路径）；无 key 1 天（拆页 + 对照录入双路径骨架）

---

### M4：学情仪表盘

**交付**
- `routers/stats.py` 四个端点
- `views/dashboard.js` + Chart.js
  - 个人薄弱 Top10（跨知识点/题型/技巧/易错点）
  - 知识点热力图（按个人薄弱图谱聚合）
  - 题型掌握度雷达
  - 个人易错模式列表
  - 错题趋势折线
  - 薄弱点证据链 + "一键针对训练"按钮

**验证**
- 数据真实反映 attempts/mistakes/diagnoses/personal_weaknesses 状态
- 点击薄弱 Top10 中某项 → 看到证据错题、关联题型、建议训练
- 仪表盘文案优先回答“我现在最该补什么”，不是泛泛展示统计图

**预计**：1 天

---

### M5：自适应推荐

**交付**
- `services/recommender.py` 实现基于个人薄弱图谱的打分函数
- `POST /api/practice/next`
- 前端"智能练习"模式：自动连推 10 题，含进度条、跳过、即时统计
- 接入 SM-2 复习算法（基于 attempts 增量更新 `review_queue`）
- 每道推荐题提供解释：命中个人薄弱点、关联图谱节点、推荐原因

**验证**
- 推荐结果以个人薄弱点为主，而不是只按章节/通用题型
- 24 小时内见过的题被显著降权
- "智能练习"完成后给出本次正确率与覆盖知识点
- 练习完成后个人薄弱图谱发生可解释更新

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

| Provider | 依赖 | 输出 | 印刷体 | 手写体 | 体验 |
|---|---|---|---|---|---|
| `manual` | 仅 PyMuPDF | 切页图片 | — | — | 用户对照手输，**不依赖任何外部** |
| `claude` | anthropic SDK | 完整结构化题目（含 LaTeX、答案、解析、kp_ids、难度）+ 作答区识别 | ✅ | ✅（M3 前置） | 最优；30 秒/页 |
| `mathpix` | Mathpix API | LaTeX 文本，仍需后续规则切题 | ✅ | ⚠️ 仅印刷公式 | 公式准但缺业务理解；手写不达标 |

`OCRProvider.parse` 返回的 schema 由 `ParseContext.target` 决定：`question` → `ParsedQuestion[]`，`mistake` → `ParsedMistake[]`（详见 §6.3.2 / §6.3.3）。provider 必须在 capabilities 中声明 `supports_handwriting: bool`，前端据此在错题沉淀 sub-tab 决定是否允许自动识别"我的作答"区。

### 11.3 当前阶段建议
- M0–M2 完全不依赖 OCR，按计划推进
- M3 上来先把 `manual` 跑通（拆页 + 缩略图对照录入）
- 你拿到 ANTHROPIC_API_KEY 后再切 `OCR_PROVIDER=claude`，**无需改前端**
- 后端在 startup 检测 key 是否存在，前端拉 `/api/intake/capabilities` 决定是否显示"AI 自动识别"按钮，并据 `supports_handwriting` 决定错题沉淀页是否允许自动识别"我的作答"
- **手写体识别能力是 M3 前置项**：错题拍照沉淀（§6.3.3）的"我的作答"字段依赖手写体 OCR；若 provider 不支持手写（manual / mathpix），错题沉淀流程仍可走，但 `user_answer_md` 留空，由用户手打补全或跳过，不卡主流程

### 11.4 DOCX 讲义导入工具沉淀

DOCX 讲义不是 OCR 降级方案，而是另一条高价值导入路径。很多培优讲义天然包含：

- 知识点归纳
- 题型标题
- 解题技巧
- 易错点拨
- 典例 / 变式
- 答案 / 详解

POC 工具方法可复用：

| 步骤 | POC 实现 | 系统化落点 |
|---|---|---|
| 文本抽取 | 直接读取 `word/document.xml`，抽取 `w:t` 与 `m:t` | `backend/services/importers/docx_handout.py` |
| 结构识别 | 正则定位“题型一”“【典例】”“【变式】”“【答案】”“【详解】” | 可配置 parser rules |
| 范围控制 | 排除“期末基础通关练/重难突破练” | 导入预览中选择章节/范围 |
| 中间格式 | `source/stem/answer/solution/expected_kp` markdown | `ParsedLearningMaterial` JSON schema |
| 图谱关联 | 规则 Top-K 关联知识点 | Top-K 候选边 + 人工/LLM 校正 |
| 验证 | 输出 `poc_report.md` | 导入前生成可审报告 |

限制与处理：

- Word 公式对象可能在纯文本抽取中丢失向量箭头、上下标或特殊符号；导入结果必须经过预览校对。
- 不同资料的题型标记可能不一致；parser rules 应按来源可配置，不写死到核心业务逻辑。
- 讲义中的“知识点归纳”不应直接覆盖 md 权威知识点；可作为候选补充、题型说明或技巧/易错点来源。
- DOCX 导入优先沉淀“题型/技巧/易错点/典例”关系，因为这部分最能服务个人薄弱图谱和针对性训练。

---

## 12. 风险与权衡

| 风险 | 影响 | 缓解 |
|---|---|---|
| 后端进程崩溃用户不易发现 | 前端 fetch 失败黑屏 | `start.sh` 加健康检查；前端顶部加"后端状态"指示灯 |
| SQLite 单文件损坏 | 数据丢失 | 启动时自动备份近 7 份 `math.db.YYYYMMDD.bak`；md 是知识点权威源可重建 |
| 知识点 md 重排导致 slug 变化 | 旧链接、旧题目关联失效 | id 公式严格沿用 `slugify('book-chapter-title-index')`；变更时检测并提示 |
| OCR 准确率不可控 | 录题脏数据 | 强制经过"预览校对"步骤，禁止直跳入库 |
| 自适应推荐冷启动 | 数据少推不准 | <30 个 attempts 时退化为"按知识点轮询" |
| 把个人薄弱点误当成通用易错点 | 推荐变成通用复习清单，降低效率 | 区分 `common_pitfalls` 与 `personal_weaknesses`，推荐必须引用个人证据 |
| 图谱边过多、难以解释 | 用户不信任推荐 | 只展示 Top 相关边，保留 evidence/source/confidence，允许人工修正 |
| 题型/技巧粒度不稳定 | 统计和推荐噪声变大 | M1 先维护少量高价值题型，随真实错题逐步合并/拆分 |
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
- **全量知识图谱展示（最低优先级）**：在现有局部图谱页之外，增加全局概览层，用于查看全部知识点、题型、技巧、通用易错点与题目的关系。为避免变成不可读的大图，默认只展示章节/知识点群、题型群和薄弱热度等聚合节点；点击后再逐层展开到局部邻接，并可叠加个人薄弱强度、证据错题和推荐训练覆盖。该能力不影响 M0-M5 主线，排在自适应推荐闭环稳定之后。

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
| 产品北极星 | 个人薄弱点诊断与复习效率提升，不做通用学习辅助工具 | 2026-05-28 |
| 图谱形态 | 基础学习图谱 + 个人薄弱图谱，非单棵章节目录树 | 2026-05-28 |
| POC 结论 | md 可结构化；docx 题型/技巧/易错点可抽取；真实讲义 Top3 关联可行 | 2026-05-28 |
| Schema 迁移策略 | 手写 SQL migrations + ~30 行 runner，不引入 Alembic；migrations/*.sql 为权威源，models.py 仅运行时 ORM | 2026-05-28 |
| 多态目标外键 | `mistake_diagnoses` / `personal_weaknesses` 采用四列互斥可空 FK (kp_id/pattern_id/skill_id/pitfall_id) + custom_label + CHECK 约束，放弃 target_type/target_id 字符串方案 | 2026-05-28 |
| 已掌握判定 | 手工写入为唯一权威（mastered_at 仅由 PATCH /api/mistakes 写入），系统基于 mastered_streak ≥ 3 且跨 ≥ 24h 做 UI 建议，不替用户落库 | 2026-05-28 |
| 薄弱度更新公式 | 三类事件 wrong/correct/master 统一通过 NODE_WEIGHT + 固定 delta 应用，详见 §16；v1 不做时间衰减 | 2026-05-28 |
| 错题拍照沉淀 | 作为一等公民流程（§6.3.3），`[录题]` tab 内 sub-tab `错题沉淀` 与 `新题入库` 并列，共享 OCR provider 与预览组件，独立 commit 端点；attempts.source 区分 `practice` / `photo_intake`，错因仍走 §6.4 三档归因模型 | 2026-05-28 |
| 手写体 OCR | 列为 M3 前置项；provider 通过 `supports_handwriting` 能力位声明；不支持手写时 user_answer_md 留空，错题沉淀主流程不卡 | 2026-05-28 |
| 客观题判分 | `questions.answer_key_json` 存结构化答案，M2 自动判分只依赖该字段；`answer_md` 仍作为展示用标准答案 | 2026-05-28 |
| 题目形式命名 | 选择/填空/解答等命名为 `question_formats` / `format_id`；训练意义上的题型统一用 `question_patterns`，避免混淆 | 2026-05-28 |
| M0 schema 范围 | `0001_initial.sql` 建 §5.2 全部表、索引、约束；M0 只实现知识点同步和最小 API，后续 milestone 逐步启用表 | 2026-05-28 |
| 图谱边 API | `POST /api/graph/edges` 用统一 payload + 白名单组合，落到具体边表，不建立无约束通用 `graph_edges` 表 | 2026-05-28 |
| DOCX 导入 API | `/api/intake/upload` 支持 docx，`POST /api/intake/import/docx` 生成 `ParsedLearningMaterial` 预览数据 | 2026-05-28 |
| 全量知识图谱展示 | 当前 PLAN 仅实现局部邻接图谱；全量知识图谱总览作为最低优先级可选演进，不进入 M0-M5 主线，且必须采用聚合概览 + 局部展开 + 个人薄弱叠加，避免不可读的大图 | 2026-05-28 |

---

## 15. 待评审 / 待补充

- [ ] 题目入库去重策略：仅按 `hash(stem_md)` 还是要做近似查重？（**M1 前置**：错题拍照沉淀 §6.3.3 的"复用/新建题"判断依赖此决策；M1 默认 `hash(stem_md)` 精确匹配，M3+ 评估 embedding 近似）
- [ ] 是否需要"知识点笔记"功能（用户在知识点页加私人笔记）？
- [x] 错题"已掌握"判定：纯手工标 vs 自动判定（连续 N 次正确）？如何同步降低个人薄弱点强度？→ 已决：手工写入为唯一权威，UI 基于 streak ≥ 3 且跨 ≥ 24h 建议；薄弱度增减见 §16
- [ ] 个人错因标注交互：固定选项、自由输入、还是固定选项 + 自定义？
- [ ] 题型/技巧/易错点的合并策略：相近节点如何避免越积越碎？（删除/合并由 `ON DELETE CASCADE` 自动清理 `mistake_diagnoses`，但 `personal_weaknesses` 需要应用层显式合并 strength/mastery/evidence_count，不能简单依赖级联）
- [ ] 推荐解释粒度：展示“命中个人薄弱点”的证据到什么程度最合适？
- [ ] 是否要做"每日打卡"/"做题日历"等激励元素？
- [x] M3 OCR：是否需要处理手写体（如手写错题集图片）？→ 已决：列为 M3 前置项，错题拍照沉淀（§6.3.3）的"我的作答"字段依赖手写体 OCR；provider 通过 `supports_handwriting` 能力位声明，不支持时留空不卡流程（详见 §11.3）
- [ ] 数据备份策略：自动 vs 手动？是否要导出可读 JSON？

---

## 16. 薄弱度更新算法

本节定义 `weakness_engine` 的契约：任何 attempt 提交或"已掌握"操作都触发**一次事件**，事件按节点权重对 `personal_weaknesses.strength` / `mastery` / `evidence_count` 应用 delta，结果 clamp 到 [0, 1]。

### 16.1 节点权重 NODE_WEIGHT

| 目标类型 | 权重 w | 直觉 |
|---|---|---|
| kp      | 0.3 | 知识点最泛，单题证据弱 |
| pattern | 0.5 | 题型反映解题习惯，证据较强 |
| skill   | 0.6 | 具体技巧的掌握度，证据强 |
| pitfall | 0.8 | 易错点最具体，单次踩坑就该重置警报 |

`custom_label` 类型节点不参与自动 delta（用户自定义错因暂不进入推荐器打分），仅作为薄弱点列表的展示项。

### 16.2 事件类型

| 事件 | 触发条件 | 写入位置 |
|---|---|---|
| `wrong`   | attempts.is_correct = 0 | weakness_engine 在 attempts 写入后同事务执行 |
| `correct` | attempts.is_correct = 1 | 同上 |
| `master`  | PATCH /api/mistakes/{qid} {mastered: true} 且 mastered_at 从 NULL 转为非 NULL | 在该接口的事务中执行；幂等地只在 NULL→NOT NULL 转换时触发一次 |

### 16.3 Delta 公式

设节点 N 类型为 t，权重 w = NODE_WEIGHT[t]，事件对 N 的影响：

```
事件 wrong：
  strength(N) ← clamp(strength + 1.0 * w, 0, 1)
  mastery(N)  ← clamp(mastery  - 0.3 * w, 0, 1)
  evidence_count(N) += 1
  last_seen_at(N) = now

事件 correct：
  strength(N) ← clamp(strength - 0.5 * w, 0, 1)
  mastery(N)  ← clamp(mastery  + 0.2 * w, 0, 1)
  evidence_count(N) += 1
  last_seen_at(N) = now

事件 master（用户主动标记）：
  strength(N) ← clamp(strength - 0.8 * w, 0, 1)
  mastery(N)  ← clamp(mastery  + 0.4 * w, 0, 1)
  evidence_count(N) += 1
  last_seen_at(N) = now
```

注意：

- master 事件比 correct 扣得更狠（0.8 vs 0.5），因为用户**显式承诺**已掌握，证据强度高于一次自然做对。
- wrong 事件的 strength 增幅 (1.0 * w) 与 PLAN §6.4 原表述（错题→知识点 +0.3 / 题型 +0.5 / 技巧 +0.6 / 易错点 +0.8）数值完全等价，此处是同一公式的统一表达。

### 16.4 自动建议触发阈值

| 常量 | 默认值 | 含义 |
|---|---|---|
| `SUGGEST_MASTERED_MIN_STREAK`     | 3   | mistakes.mastered_streak ≥ 此值才触发 UI 建议 |
| `SUGGEST_MASTERED_MIN_SPAN_HOURS` | 24  | 最早与最近一次正确 attempt 时间跨度 ≥ 此值，防一坐下连点三次 |

判定式：

```
should_suggest_mastered(qid) :=
    mistakes.mastered_at IS NULL
  AND mistakes.mastered_streak >= SUGGEST_MASTERED_MIN_STREAK
  AND (
       SELECT MAX(attempted_at) - MIN(attempted_at)
       FROM (SELECT attempted_at FROM attempts
             WHERE question_id = qid AND is_correct = 1
             ORDER BY attempted_at DESC LIMIT SUGGEST_MASTERED_MIN_STREAK)
      ) >= SUGGEST_MASTERED_MIN_SPAN_HOURS
```

由 `GET /api/mistakes` 在响应中附 `suggest_mastered: bool` 字段，由前端决定提示样式。系统**不**根据该判定自动写入 mastered_at。

### 16.5 实现约定

- 所有常量集中放在 `backend/services/weakness_engine.py` 文件头部，避免散落。
- 三类事件统一通过 `apply_event(node, event_type)` 入口写入，便于审计与单测。
- 一次 attempt 涉及该题所有关联节点（kp / pattern / skill / pitfall 各表的 N:N 边），逐节点应用事件，事务内提交。
- master 事件的幂等保证：仅在 UPDATE mistakes SET mastered_at = now WHERE question_id = ? AND mastered_at IS NULL 的影响行数 = 1 时才触发 delta；否则视为重复点击，no-op。
- 取消已掌握（mastered=false）只清字段，**不**调用 weakness_engine；这是有意的简化，避免反向 delta 与 evidence_count 不一致。
- v1 不做被动衰减（mastery 随时间漂移），以减少 M2 调试面；M5 推荐器再决定是否引入 last_seen_at-based decay。

### 16.6 冷启动与异常

- attempts < 30 时，推荐器（M5）退化为"按知识点轮询"（已在 §12 风险表中标注）。weakness_engine 仍正常累计 strength / mastery，但推荐打分降权。
- 若一次 attempt 提交时找不到题目的任何关联节点，weakness_engine 跳过 delta（仅写 attempts / mistakes 基础字段），并在日志中告警，提示数据建模缺失。

---

> 评审通过后从 M0 开始执行；每个 milestone 完成后回到本文件勾选并记录实际工时。
