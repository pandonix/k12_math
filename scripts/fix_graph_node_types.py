#!/usr/bin/env python3
"""One-off corrective migration for the base learning graph.

Both importers (`import_uploaded_docx_questions.py` and
`import_20260530_knowledge_graph.py`) materialised every source section as a
`question_patterns` (题型) row, even when the section was really a 技巧 (skill),
通用易错点 (pitfall) or 知识补充. PLAN §3.1/§5.1 model these as distinct,
mutually exclusive node types, so the duplicated 题型 rows are wrong.

For every such pseudo-pattern a same-name twin already exists in `skills` /
`common_pitfalls`, and every question under it already carries the matching
`question_skills` / `question_pitfalls` edge (verified before running). Question
↔ knowledge-point linkage survives via `question_kp`. So the fix is simply to
drop the pseudo-pattern rows and their pattern-side edges; nothing is orphaned.
"""
from __future__ import annotations

import argparse
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB_PATH = ROOT / "data" / "math.db"

# question_patterns rows whose names start with these prefixes are not real
# 题型 — they are skills / pitfalls / supplementary knowledge dumped into the
# pattern table by the importers.
PSEUDO_PREFIXES = ("方法技巧", "妙招", "易混易错", "避坑", "知识点", "速查")


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def backup_db(db_path: Path) -> Path:
    backup_path = db_path.with_name(f"{db_path.name}.before-graph-typefix.{utc_stamp()}.bak")
    shutil.copy2(db_path, backup_path)
    return backup_path


def pseudo_pattern_ids(conn: sqlite3.Connection) -> list[int]:
    clause = " OR ".join("name LIKE ?" for _ in PSEUDO_PREFIXES)
    params = [f"{prefix}%" for prefix in PSEUDO_PREFIXES]
    rows = conn.execute(f"SELECT id FROM question_patterns WHERE {clause}", params).fetchall()
    return [int(row[0]) for row in rows]


def safety_check(conn: sqlite3.Connection, ids: list[int]) -> None:
    """Refuse to delete any pseudo-pattern whose questions would lose their
    skill/pitfall linkage (i.e. no same-name twin edge already present)."""
    placeholders = ",".join("?" for _ in ids)
    orphan = conn.execute(
        f"""
        SELECT COUNT(*)
        FROM question_patterns_map qpm
        JOIN question_patterns p ON p.id = qpm.pattern_id
        WHERE qpm.pattern_id IN ({placeholders})
          AND NOT EXISTS (
              SELECT 1 FROM question_skills qs JOIN skills s ON s.id = qs.skill_id
              WHERE qs.question_id = qpm.question_id AND s.name = p.name
          )
          AND NOT EXISTS (
              SELECT 1 FROM question_pitfalls qp JOIN common_pitfalls c ON c.id = qp.pitfall_id
              WHERE qp.question_id = qpm.question_id AND c.name = p.name
          )
        """,
        ids,
    ).fetchone()[0]
    if orphan:
        raise SystemExit(
            f"Aborting: {orphan} question(s) would lose their skill/pitfall edge. "
            "Create the twin edges first."
        )


def delete_pseudo_patterns(conn: sqlite3.Connection, ids: list[int]) -> dict[str, int]:
    placeholders = ",".join("?" for _ in ids)
    deleted = {}
    for table in ("pattern_kp", "pattern_skills", "pattern_pitfalls", "question_patterns_map"):
        cur = conn.execute(f"DELETE FROM {table} WHERE pattern_id IN ({placeholders})", ids)
        deleted[table] = cur.rowcount
    cur = conn.execute(f"DELETE FROM question_patterns WHERE id IN ({placeholders})", ids)
    deleted["question_patterns"] = cur.rowcount
    return deleted


def pattern_breakdown(conn: sqlite3.Connection) -> dict[str, int]:
    return {
        "total": conn.execute("SELECT COUNT(*) FROM question_patterns").fetchone()[0],
        "skills": conn.execute("SELECT COUNT(*) FROM skills").fetchone()[0],
        "common_pitfalls": conn.execute("SELECT COUNT(*) FROM common_pitfalls").fetchone()[0],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--apply", action="store_true", help="Write changes. Without it, dry-run only.")
    args = parser.parse_args()

    if not args.db.exists():
        raise SystemExit(f"database not found: {args.db}")

    conn = sqlite3.connect(args.db)
    conn.execute("PRAGMA foreign_keys = ON")
    ids = pseudo_pattern_ids(conn)
    before = pattern_breakdown(conn)
    print(f"pseudo-patterns to remove: {len(ids)}")
    print(f"before: {before}")

    if not ids:
        print("nothing to do")
        return

    safety_check(conn, ids)

    if not args.apply:
        print("dry-run (pass --apply to write)")
        conn.close()
        return

    conn.close()
    backup = backup_db(args.db)
    print(f"backup: {backup}")

    conn = sqlite3.connect(args.db)
    conn.execute("PRAGMA foreign_keys = ON")
    deleted = delete_pseudo_patterns(conn, ids)
    conn.commit()
    after = pattern_breakdown(conn)
    conn.close()

    print(f"deleted: {deleted}")
    print(f"after: {after}")


if __name__ == "__main__":
    main()
