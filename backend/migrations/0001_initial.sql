CREATE TABLE knowledge_points (
  id                TEXT PRIMARY KEY,
  book              TEXT NOT NULL,
  chapter           TEXT,
  section           TEXT,
  title             TEXT NOT NULL,
  level             INTEGER NOT NULL,
  parent_id         TEXT REFERENCES knowledge_points(id),
  content_md        TEXT NOT NULL,
  tags_json         TEXT,
  facets_json       TEXT,
  order_index       INTEGER NOT NULL,
  content_md5       TEXT NOT NULL,
  legacy_id_formula TEXT NOT NULL,
  updated_at        DATETIME NOT NULL
);

CREATE INDEX idx_kp_book_chapter ON knowledge_points(book, chapter, section);
CREATE INDEX idx_kp_order ON knowledge_points(order_index);

CREATE TABLE question_formats (
  id   INTEGER PRIMARY KEY,
  name TEXT NOT NULL UNIQUE
);

INSERT INTO question_formats(id, name)
VALUES (1, '选择'), (2, '填空'), (3, '解答'), (4, '证明'), (5, '作图');

CREATE TABLE questions (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  source          TEXT,
  format_id       INTEGER REFERENCES question_formats(id),
  difficulty      INTEGER,
  stem_md         TEXT NOT NULL,
  options_json    TEXT,
  answer_key_json TEXT,
  answer_md       TEXT,
  solution_md     TEXT,
  image_path      TEXT,
  hash            TEXT UNIQUE,
  created_at      DATETIME NOT NULL,
  updated_at      DATETIME NOT NULL
);

CREATE TABLE question_kp (
  question_id INTEGER REFERENCES questions(id) ON DELETE CASCADE,
  kp_id       TEXT REFERENCES knowledge_points(id),
  weight      REAL DEFAULT 1.0,
  is_primary  INTEGER DEFAULT 0,
  PRIMARY KEY (question_id, kp_id)
);

CREATE INDEX idx_qkp_kp ON question_kp(kp_id);

CREATE TABLE question_patterns (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  name        TEXT NOT NULL,
  strategy_md TEXT,
  source      TEXT,
  order_index INTEGER,
  created_at  DATETIME NOT NULL,
  updated_at  DATETIME NOT NULL
);

CREATE TABLE skills (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  name       TEXT NOT NULL UNIQUE,
  content_md TEXT,
  created_at DATETIME NOT NULL,
  updated_at DATETIME NOT NULL
);

CREATE TABLE common_pitfalls (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  name       TEXT NOT NULL UNIQUE,
  content_md TEXT,
  created_at DATETIME NOT NULL,
  updated_at DATETIME NOT NULL
);

CREATE TABLE pattern_kp (
  pattern_id INTEGER REFERENCES question_patterns(id) ON DELETE CASCADE,
  kp_id      TEXT REFERENCES knowledge_points(id),
  weight     REAL DEFAULT 1.0,
  relation   TEXT DEFAULT 'tests',
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

CREATE TABLE question_tags (
  question_id INTEGER REFERENCES questions(id) ON DELETE CASCADE,
  tag         TEXT NOT NULL,
  PRIMARY KEY (question_id, tag)
);

CREATE TABLE attempts (
  id                INTEGER PRIMARY KEY AUTOINCREMENT,
  question_id       INTEGER REFERENCES questions(id),
  is_correct        INTEGER NOT NULL,
  self_rating       INTEGER,
  time_spent_sec    INTEGER,
  user_answer_md    TEXT,
  answer_image_path TEXT,
  source            TEXT NOT NULL DEFAULT 'practice',
  attempted_at      DATETIME NOT NULL
);

CREATE INDEX idx_attempts_qid_time ON attempts(question_id, attempted_at);

CREATE TABLE mistake_diagnoses (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  attempt_id   INTEGER NOT NULL REFERENCES attempts(id) ON DELETE CASCADE,
  kp_id        TEXT REFERENCES knowledge_points(id) ON DELETE CASCADE,
  pattern_id   INTEGER REFERENCES question_patterns(id) ON DELETE CASCADE,
  skill_id     INTEGER REFERENCES skills(id) ON DELETE CASCADE,
  pitfall_id   INTEGER REFERENCES common_pitfalls(id) ON DELETE CASCADE,
  custom_label TEXT,
  note_md      TEXT,
  confidence   REAL DEFAULT 1.0,
  source       TEXT NOT NULL,
  created_at   DATETIME NOT NULL,
  CHECK (
    (kp_id IS NOT NULL) +
    (pattern_id IS NOT NULL) +
    (skill_id IS NOT NULL) +
    (pitfall_id IS NOT NULL) +
    (custom_label IS NOT NULL) = 1
  )
);

CREATE INDEX idx_diag_attempt ON mistake_diagnoses(attempt_id);
CREATE INDEX idx_diag_kp      ON mistake_diagnoses(kp_id)      WHERE kp_id      IS NOT NULL;
CREATE INDEX idx_diag_pattern ON mistake_diagnoses(pattern_id) WHERE pattern_id IS NOT NULL;
CREATE INDEX idx_diag_skill   ON mistake_diagnoses(skill_id)   WHERE skill_id   IS NOT NULL;
CREATE INDEX idx_diag_pitfall ON mistake_diagnoses(pitfall_id) WHERE pitfall_id IS NOT NULL;

CREATE TABLE mistakes (
  question_id      INTEGER PRIMARY KEY REFERENCES questions(id) ON DELETE CASCADE,
  first_wrong_at   DATETIME NOT NULL,
  last_wrong_at    DATETIME NOT NULL,
  wrong_count      INTEGER NOT NULL DEFAULT 1,
  last_attempt_id  INTEGER REFERENCES attempts(id),
  note_md          TEXT,
  mastered_at      DATETIME,
  mastered_source  TEXT,
  mastered_streak  INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE personal_weaknesses (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  kp_id          TEXT REFERENCES knowledge_points(id) ON DELETE CASCADE,
  pattern_id     INTEGER REFERENCES question_patterns(id) ON DELETE CASCADE,
  skill_id       INTEGER REFERENCES skills(id) ON DELETE CASCADE,
  pitfall_id     INTEGER REFERENCES common_pitfalls(id) ON DELETE CASCADE,
  custom_label   TEXT,
  title          TEXT NOT NULL,
  strength       REAL NOT NULL DEFAULT 0,
  mastery        REAL NOT NULL DEFAULT 0,
  evidence_count INTEGER NOT NULL DEFAULT 0,
  last_seen_at   DATETIME,
  updated_at     DATETIME NOT NULL,
  CHECK (
    (kp_id IS NOT NULL) +
    (pattern_id IS NOT NULL) +
    (skill_id IS NOT NULL) +
    (pitfall_id IS NOT NULL) +
    (custom_label IS NOT NULL) = 1
  )
);

CREATE UNIQUE INDEX uq_pw_kp      ON personal_weaknesses(kp_id)        WHERE kp_id        IS NOT NULL;
CREATE UNIQUE INDEX uq_pw_pattern ON personal_weaknesses(pattern_id)   WHERE pattern_id   IS NOT NULL;
CREATE UNIQUE INDEX uq_pw_skill   ON personal_weaknesses(skill_id)     WHERE skill_id     IS NOT NULL;
CREATE UNIQUE INDEX uq_pw_pitfall ON personal_weaknesses(pitfall_id)   WHERE pitfall_id   IS NOT NULL;
CREATE UNIQUE INDEX uq_pw_custom  ON personal_weaknesses(custom_label) WHERE custom_label IS NOT NULL;
CREATE INDEX idx_weakness_strength ON personal_weaknesses(strength DESC, last_seen_at DESC);

CREATE TABLE review_queue (
  question_id    INTEGER PRIMARY KEY REFERENCES questions(id) ON DELETE CASCADE,
  due_at         DATETIME NOT NULL,
  ease_factor    REAL NOT NULL DEFAULT 2.5,
  interval_days  REAL NOT NULL DEFAULT 1.0,
  repetitions    INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX idx_review_due ON review_queue(due_at);

CREATE VIRTUAL TABLE questions_fts USING fts5(
  stem_md,
  solution_md,
  source,
  content='questions',
  content_rowid='id',
  tokenize='unicode61'
);

CREATE TRIGGER questions_ai AFTER INSERT ON questions BEGIN
  INSERT INTO questions_fts(rowid, stem_md, solution_md, source)
  VALUES (new.id, new.stem_md, new.solution_md, new.source);
END;

CREATE TRIGGER questions_ad AFTER DELETE ON questions BEGIN
  INSERT INTO questions_fts(questions_fts, rowid, stem_md, solution_md, source)
  VALUES ('delete', old.id, old.stem_md, old.solution_md, old.source);
END;

CREATE TRIGGER questions_au AFTER UPDATE ON questions BEGIN
  INSERT INTO questions_fts(questions_fts, rowid, stem_md, solution_md, source)
  VALUES ('delete', old.id, old.stem_md, old.solution_md, old.source);
  INSERT INTO questions_fts(rowid, stem_md, solution_md, source)
  VALUES (new.id, new.stem_md, new.solution_md, new.source);
END;

CREATE VIRTUAL TABLE kp_fts USING fts5(
  title,
  content_md,
  content='knowledge_points',
  content_rowid='rowid',
  tokenize='unicode61'
);

CREATE TRIGGER knowledge_points_ai AFTER INSERT ON knowledge_points BEGIN
  INSERT INTO kp_fts(rowid, title, content_md)
  VALUES (new.rowid, new.title, new.content_md);
END;

CREATE TRIGGER knowledge_points_ad AFTER DELETE ON knowledge_points BEGIN
  INSERT INTO kp_fts(kp_fts, rowid, title, content_md)
  VALUES ('delete', old.rowid, old.title, old.content_md);
END;

CREATE TRIGGER knowledge_points_au AFTER UPDATE ON knowledge_points BEGIN
  INSERT INTO kp_fts(kp_fts, rowid, title, content_md)
  VALUES ('delete', old.rowid, old.title, old.content_md);
  INSERT INTO kp_fts(rowid, title, content_md)
  VALUES (new.rowid, new.title, new.content_md);
END;
