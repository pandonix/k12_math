#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "data" / "math.db"
DEFAULT_OUTPUT = ROOT / "artifacts" / "kg-demo-20260530.html"
BATCH_TAG = "20260530索引"


def fetch_graph(db_path: Path) -> dict:
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        kp_rows = conn.execute(
            """
            SELECT kp.id,
                   kp.title,
                   kp.book,
                   kp.chapter,
                   COUNT(DISTINCT qk.question_id) AS question_count,
                   COUNT(DISTINCT pk.pattern_id) AS pattern_count
            FROM knowledge_points kp
            LEFT JOIN question_kp qk
              ON qk.kp_id = kp.id
             AND qk.question_id IN (
               SELECT question_id FROM question_tags WHERE tag = ?
             )
            LEFT JOIN pattern_kp pk ON pk.kp_id = kp.id
            GROUP BY kp.id
            HAVING question_count > 0 OR pattern_count > 0
            ORDER BY question_count DESC, pattern_count DESC, kp.order_index
            """,
            (BATCH_TAG,),
        ).fetchall()

        pattern_rows = conn.execute(
            """
            SELECT p.id,
                   p.name,
                   p.source,
                   COUNT(DISTINCT qpm.question_id) AS question_count
            FROM question_patterns p
            LEFT JOIN question_patterns_map qpm
              ON qpm.pattern_id = p.id
             AND qpm.question_id IN (
               SELECT question_id FROM question_tags WHERE tag = ?
             )
            WHERE p.source = '20260530'
               OR qpm.question_id IS NOT NULL
               OR EXISTS (SELECT 1 FROM pattern_kp pk WHERE pk.pattern_id = p.id)
               OR EXISTS (SELECT 1 FROM pattern_skills ps WHERE ps.pattern_id = p.id)
               OR EXISTS (SELECT 1 FROM pattern_pitfalls pp WHERE pp.pattern_id = p.id)
            GROUP BY p.id
            ORDER BY question_count DESC, p.id
            """,
            (BATCH_TAG,),
        ).fetchall()

        skill_rows = conn.execute(
            """
            SELECT s.id, s.name, COUNT(DISTINCT ps.pattern_id) AS pattern_count
            FROM skills s
            JOIN pattern_skills ps ON ps.skill_id = s.id
            GROUP BY s.id
            ORDER BY pattern_count DESC, s.id
            """
        ).fetchall()

        pitfall_rows = conn.execute(
            """
            SELECT p.id, p.name, COUNT(DISTINCT pp.pattern_id) AS pattern_count
            FROM common_pitfalls p
            JOIN pattern_pitfalls pp ON pp.pitfall_id = p.id
            GROUP BY p.id
            ORDER BY pattern_count DESC, p.id
            """
        ).fetchall()

        pattern_ids = {row["id"] for row in pattern_rows}
        pattern_id_placeholders = ",".join("?" for _ in pattern_ids) or "NULL"
        pattern_params = tuple(pattern_ids)

        edges = []
        if pattern_ids:
            for row in conn.execute(
                f"""
                SELECT pattern_id, kp_id, weight, relation
                FROM pattern_kp
                WHERE pattern_id IN ({pattern_id_placeholders})
                """,
                pattern_params,
            ):
                edges.append(
                    {
                        "source": f"pattern:{row['pattern_id']}",
                        "target": f"kp:{row['kp_id']}",
                        "type": row["relation"] or "tests",
                        "weight": row["weight"] or 1,
                    }
                )
            for row in conn.execute(
                f"""
                SELECT pattern_id, skill_id, weight
                FROM pattern_skills
                WHERE pattern_id IN ({pattern_id_placeholders})
                """,
                pattern_params,
            ):
                edges.append(
                    {
                        "source": f"pattern:{row['pattern_id']}",
                        "target": f"skill:{row['skill_id']}",
                        "type": "uses",
                        "weight": row["weight"] or 1,
                    }
                )
            for row in conn.execute(
                f"""
                SELECT pattern_id, pitfall_id, weight
                FROM pattern_pitfalls
                WHERE pattern_id IN ({pattern_id_placeholders})
                """,
                pattern_params,
            ):
                edges.append(
                    {
                        "source": f"pattern:{row['pattern_id']}",
                        "target": f"pitfall:{row['pitfall_id']}",
                        "type": "has_pitfall",
                        "weight": row["weight"] or 1,
                    }
                )

        question_rows = conn.execute(
            """
            SELECT q.id,
                   q.source,
                   q.stem_md,
                   GROUP_CONCAT(DISTINCT qk.kp_id) AS kp_ids,
                   GROUP_CONCAT(DISTINCT qpm.pattern_id) AS pattern_ids
            FROM questions q
            JOIN question_tags qt ON qt.question_id = q.id AND qt.tag = ?
            LEFT JOIN question_kp qk ON qk.question_id = q.id
            LEFT JOIN question_patterns_map qpm ON qpm.question_id = q.id
            GROUP BY q.id
            ORDER BY q.id
            """,
            (BATCH_TAG,),
        ).fetchall()

    nodes = []
    for row in kp_rows:
        nodes.append(
            {
                "id": f"kp:{row['id']}",
                "kind": "kp",
                "label": row["title"],
                "subtitle": row["chapter"] or row["book"],
                "questionCount": row["question_count"],
                "patternCount": row["pattern_count"],
            }
        )
    for row in pattern_rows:
        nodes.append(
            {
                "id": f"pattern:{row['id']}",
                "kind": "pattern",
                "label": row["name"],
                "subtitle": row["source"] or "manual",
                "questionCount": row["question_count"],
            }
        )
    for row in skill_rows:
        nodes.append(
            {
                "id": f"skill:{row['id']}",
                "kind": "skill",
                "label": row["name"],
                "subtitle": "技巧",
                "patternCount": row["pattern_count"],
            }
        )
    for row in pitfall_rows:
        nodes.append(
            {
                "id": f"pitfall:{row['id']}",
                "kind": "pitfall",
                "label": row["name"],
                "subtitle": "通用易错点",
                "patternCount": row["pattern_count"],
            }
        )

    questions = []
    for row in question_rows:
        questions.append(
            {
                "id": row["id"],
                "source": row["source"],
                "stem": row["stem_md"],
                "kpIds": [f"kp:{item}" for item in (row["kp_ids"] or "").split(",") if item],
                "patternIds": [f"pattern:{item}" for item in (row["pattern_ids"] or "").split(",") if item],
            }
        )

    return {
        "generatedFrom": str(db_path),
        "summary": {
            "nodes": len(nodes),
            "edges": len(edges),
            "knowledgePoints": len(kp_rows),
            "patterns": len(pattern_rows),
            "skills": len(skill_rows),
            "pitfalls": len(pitfall_rows),
            "indexedQuestions": len(questions),
        },
        "nodes": nodes,
        "edges": edges,
        "questions": questions,
    }


def build_html(data: dict) -> str:
    payload = json.dumps(data, ensure_ascii=False)
    payload = (
        payload.replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
    )
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>20260530 知识图谱 Demo</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f7f8fb;
      --panel: #ffffff;
      --text: #172033;
      --muted: #667085;
      --line: #d9dee8;
      --kp: #2563eb;
      --pattern: #0f766e;
      --skill: #7c3aed;
      --pitfall: #c2410c;
      --shadow: 0 18px 45px rgba(20, 30, 55, .12);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: var(--bg);
      color: var(--text);
      overflow: hidden;
    }}
    .shell {{
      height: 100vh;
      display: grid;
      grid-template-columns: 300px minmax(520px, 1fr) 380px;
      gap: 1px;
      background: var(--line);
    }}
    aside, main, .detail {{
      background: var(--panel);
      min-height: 0;
    }}
    aside, .detail {{
      display: flex;
      flex-direction: column;
    }}
    header {{
      padding: 18px 18px 14px;
      border-bottom: 1px solid var(--line);
    }}
    h1 {{
      margin: 0;
      font-size: 18px;
      line-height: 1.3;
      letter-spacing: 0;
    }}
    .sub {{
      margin-top: 6px;
      color: var(--muted);
      font-size: 12px;
      line-height: 1.5;
    }}
    .stats {{
      display: grid;
      grid-template-columns: repeat(2, 1fr);
      gap: 8px;
      padding: 14px;
      border-bottom: 1px solid var(--line);
    }}
    .stat {{
      padding: 10px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fbfcff;
    }}
    .stat strong {{
      display: block;
      font-size: 20px;
      margin-bottom: 3px;
    }}
    .stat span {{
      color: var(--muted);
      font-size: 12px;
    }}
    .controls {{
      padding: 14px;
      border-bottom: 1px solid var(--line);
    }}
    input, select {{
      width: 100%;
      height: 36px;
      border: 1px solid var(--line);
      border-radius: 7px;
      padding: 0 10px;
      font-size: 13px;
      background: white;
      color: var(--text);
      margin-bottom: 8px;
    }}
    .legend {{
      padding: 14px;
      display: grid;
      gap: 8px;
      font-size: 13px;
    }}
    .legend button {{
      height: 32px;
      border: 1px solid var(--line);
      background: white;
      border-radius: 7px;
      display: flex;
      align-items: center;
      gap: 8px;
      padding: 0 10px;
      cursor: pointer;
      color: var(--text);
    }}
    .dot {{
      width: 10px;
      height: 10px;
      border-radius: 50%;
      background: currentColor;
      flex: none;
    }}
    .scroll {{
      overflow: auto;
      padding: 12px 14px 16px;
    }}
    .list-item {{
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 10px;
      margin-bottom: 8px;
      cursor: pointer;
      background: white;
    }}
    .list-item:hover {{ border-color: #9aa8bd; }}
    .list-item strong {{
      display: block;
      font-size: 13px;
      line-height: 1.35;
      margin-bottom: 4px;
    }}
    .list-item span {{
      display: block;
      color: var(--muted);
      font-size: 12px;
      line-height: 1.4;
    }}
    main {{
      position: relative;
      overflow: hidden;
    }}
    .toolbar {{
      position: absolute;
      top: 14px;
      left: 14px;
      right: 14px;
      z-index: 3;
      display: flex;
      gap: 8px;
      align-items: center;
      pointer-events: none;
    }}
    .toolbar .pill {{
      pointer-events: auto;
      border: 1px solid var(--line);
      background: rgba(255,255,255,.92);
      border-radius: 999px;
      padding: 8px 12px;
      font-size: 12px;
      box-shadow: 0 8px 24px rgba(20,30,55,.08);
    }}
    svg {{
      width: 100%;
      height: 100%;
      display: block;
      background:
        linear-gradient(#eef2f7 1px, transparent 1px),
        linear-gradient(90deg, #eef2f7 1px, transparent 1px);
      background-size: 28px 28px;
    }}
    .edge {{
      stroke: #9aa8bd;
      stroke-opacity: .36;
      stroke-width: 1.2;
    }}
    .node circle {{
      stroke: white;
      stroke-width: 2.5;
      filter: drop-shadow(0 5px 10px rgba(15,23,42,.2));
    }}
    .node text {{
      font-size: 11px;
      fill: #172033;
      paint-order: stroke;
      stroke: white;
      stroke-width: 4px;
      stroke-linejoin: round;
      pointer-events: none;
    }}
    .node.selected circle {{
      stroke: #111827;
      stroke-width: 3;
    }}
    .detail .body {{
      overflow: auto;
      padding: 14px 16px 20px;
    }}
    .badge-row {{
      display: flex;
      gap: 6px;
      flex-wrap: wrap;
      margin: 8px 0 14px;
    }}
    .badge {{
      border-radius: 999px;
      padding: 4px 8px;
      background: #eef2f7;
      color: #475467;
      font-size: 12px;
    }}
    .question {{
      padding: 10px 0;
      border-top: 1px solid var(--line);
    }}
    .question strong {{
      display: block;
      font-size: 12px;
      line-height: 1.45;
      margin-bottom: 6px;
    }}
    .question pre {{
      margin: 0;
      white-space: pre-wrap;
      font: 12px/1.45 ui-monospace, SFMono-Regular, Menlo, monospace;
      color: #475467;
      background: #f8fafc;
      border: 1px solid #e6ebf2;
      border-radius: 7px;
      padding: 8px;
    }}
    @media (max-width: 1100px) {{
      .shell {{ grid-template-columns: 260px 1fr; }}
      .detail {{ display: none; }}
    }}
  </style>
</head>
<body>
  <div class="shell">
    <aside>
      <header>
        <h1>20260530 知识图谱 Demo</h1>
        <div class="sub">独立静态演示，不接入当前项目页面。知识点、题型/栏目、技巧、易错点与题目索引。</div>
      </header>
      <section class="stats" id="stats"></section>
      <section class="controls">
        <input id="search" placeholder="搜索知识点 / 题型 / 技巧 / 易错点" />
        <select id="kind">
          <option value="all">全部节点</option>
          <option value="kp">知识点</option>
          <option value="pattern">题型/栏目</option>
          <option value="skill">技巧</option>
          <option value="pitfall">易错点</option>
        </select>
      </section>
      <section class="legend">
        <button data-kind="kp"><span class="dot" style="color:var(--kp)"></span>知识点</button>
        <button data-kind="pattern"><span class="dot" style="color:var(--pattern)"></span>题型/栏目</button>
        <button data-kind="skill"><span class="dot" style="color:var(--skill)"></span>技巧/知识补充</button>
        <button data-kind="pitfall"><span class="dot" style="color:var(--pitfall)"></span>通用易错点</button>
      </section>
      <div class="scroll" id="nodeList"></div>
    </aside>
    <main>
      <div class="toolbar">
        <div class="pill" id="visibleCount"></div>
        <div class="pill">20260530 批次 · 题目索引模式</div>
      </div>
      <svg id="graph" role="img" aria-label="20260530 知识图谱"></svg>
    </main>
    <section class="detail">
      <header>
        <h1 id="detailTitle">图谱节点</h1>
        <div class="sub" id="detailSub">节点详情与索引题。</div>
      </header>
      <div class="body" id="detailBody"></div>
    </section>
  </div>
  <script id="kg-data" type="application/json">{payload}</script>
  <script>
    const data = JSON.parse(document.getElementById('kg-data').textContent);
    const colors = {{ kp: '#2563eb', pattern: '#0f766e', skill: '#7c3aed', pitfall: '#c2410c' }};
    const svg = document.getElementById('graph');
    const stats = document.getElementById('stats');
    const nodeList = document.getElementById('nodeList');
    const search = document.getElementById('search');
    const kind = document.getElementById('kind');
    const visibleCount = document.getElementById('visibleCount');
    const detailTitle = document.getElementById('detailTitle');
    const detailSub = document.getElementById('detailSub');
    const detailBody = document.getElementById('detailBody');

    stats.innerHTML = [
      ['知识点', data.summary.knowledgePoints],
      ['题型/栏目', data.summary.patterns],
      ['技巧', data.summary.skills],
      ['易错点', data.summary.pitfalls],
      ['索引题', data.summary.indexedQuestions],
      ['图谱边', data.summary.edges]
    ].map(([k,v]) => `<div class="stat"><strong>${{v}}</strong><span>${{k}}</span></div>`).join('');

    const byId = new Map(data.nodes.map(n => [n.id, {{...n}}]));
    const questionsByNode = new Map();
    for (const q of data.questions) {{
      for (const id of [...q.kpIds, ...q.patternIds]) {{
        if (!questionsByNode.has(id)) questionsByNode.set(id, []);
        questionsByNode.get(id).push(q);
      }}
    }}

    let selectedId = null;
    let graphNodes = [];
    let graphEdges = [];

    function nodeScore(n) {{
      return (n.questionCount || 0) * 3 + (n.patternCount || 0);
    }}

    function filteredNodes() {{
      const term = search.value.trim().toLowerCase();
      const k = kind.value;
      return data.nodes
        .filter(n => k === 'all' || n.kind === k)
        .filter(n => !term || (n.label + ' ' + (n.subtitle || '')).toLowerCase().includes(term))
        .sort((a,b) => nodeScore(b) - nodeScore(a))
        .slice(0, 260);
    }}

    function layout(nodes, edges) {{
      const rect = svg.getBoundingClientRect();
      const w = Math.max(rect.width, 640), h = Math.max(rect.height, 480);
      const bands = {{ kp: .18, pattern: .46, skill: .74, pitfall: .82 }};
      nodes.forEach((n, i) => {{
        n.x = n.x ?? w * (bands[n.kind] || .5) + (Math.random() - .5) * 80;
        n.y = n.y ?? 80 + (i * 47 % Math.max(160, h - 140));
        n.vx = n.vx || 0;
        n.vy = n.vy || 0;
      }});
      for (let tick = 0; tick < 210; tick++) {{
        for (const n of nodes) {{
          const targetX = w * (bands[n.kind] || .5);
          n.vx += (targetX - n.x) * 0.003;
          n.vy += (h / 2 - n.y) * 0.0006;
        }}
        for (let i = 0; i < nodes.length; i++) {{
          for (let j = i + 1; j < nodes.length; j++) {{
            const a = nodes[i], b = nodes[j];
            let dx = a.x - b.x, dy = a.y - b.y;
            let d2 = dx * dx + dy * dy || 1;
            if (d2 > 11000) continue;
            const f = 90 / d2;
            a.vx += dx * f; a.vy += dy * f;
            b.vx -= dx * f; b.vy -= dy * f;
          }}
        }}
        for (const e of edges) {{
          const a = byId.get(e.source), b = byId.get(e.target);
          if (!a || !b || !a.visible || !b.visible) continue;
          const dx = b.x - a.x, dy = b.y - a.y;
          const dist = Math.sqrt(dx * dx + dy * dy) || 1;
          const target = 145;
          const f = (dist - target) * 0.002;
          a.vx += dx / dist * f; a.vy += dy / dist * f;
          b.vx -= dx / dist * f; b.vy -= dy / dist * f;
        }}
        for (const n of nodes) {{
          n.vx *= .84; n.vy *= .84;
          n.x = Math.max(24, Math.min(w - 24, n.x + n.vx));
          n.y = Math.max(58, Math.min(h - 24, n.y + n.vy));
        }}
      }}
    }}

    function render() {{
      graphNodes = filteredNodes().map(n => byId.get(n.id));
      const allowed = new Set(graphNodes.map(n => n.id));
      for (const n of byId.values()) n.visible = allowed.has(n.id);
      graphEdges = data.edges.filter(e => allowed.has(e.source) && allowed.has(e.target));
      layout(graphNodes, graphEdges);
      visibleCount.textContent = `${{graphNodes.length}} 个节点 · ${{graphEdges.length}} 条边`;
      svg.innerHTML = `
        <g class="edges">${{graphEdges.map(e => {{
          const a = byId.get(e.source), b = byId.get(e.target);
          return `<line class="edge" x1="${{a.x.toFixed(1)}}" y1="${{a.y.toFixed(1)}}" x2="${{b.x.toFixed(1)}}" y2="${{b.y.toFixed(1)}}"></line>`;
        }}).join('')}}</g>
        <g class="nodes">${{graphNodes.map(n => {{
          const r = Math.max(7, Math.min(19, 7 + Math.sqrt(nodeScore(n) || 1) * .65));
          const label = escapeHtml(n.label.length > 18 ? n.label.slice(0, 18) + '…' : n.label);
          return `<g class="node ${{n.id === selectedId ? 'selected' : ''}}" data-id="${{n.id}}" transform="translate(${{n.x.toFixed(1)}},${{n.y.toFixed(1)}})">
            <circle r="${{r.toFixed(1)}}" fill="${{colors[n.kind]}}"></circle>
            <text x="${{r + 6}}" y="4">${{label}}</text>
          </g>`;
        }}).join('')}}</g>`;
      svg.querySelectorAll('.node').forEach(el => el.addEventListener('click', () => selectNode(el.dataset.id)));
      renderList();
    }}

    function renderList() {{
      nodeList.innerHTML = graphNodes
        .slice()
        .sort((a,b) => nodeScore(b) - nodeScore(a))
        .map(n => `<div class="list-item" data-id="${{n.id}}">
          <strong>${{escapeHtml(n.label)}}</strong>
          <span>${{kindName(n.kind)}} · ${{n.questionCount || 0}} 题 · ${{n.patternCount || 0}} 关联</span>
        </div>`)
        .join('');
      nodeList.querySelectorAll('.list-item').forEach(el => el.addEventListener('click', () => selectNode(el.dataset.id)));
    }}

    function selectNode(id) {{
      selectedId = id;
      const n = byId.get(id);
      if (!n) return;
      detailTitle.textContent = n.label;
      detailSub.textContent = `${{kindName(n.kind)}} · ${{n.subtitle || ''}}`;
      const qs = (questionsByNode.get(id) || []).slice(0, 80);
      detailBody.innerHTML = `
        <div class="badge-row">
          <span class="badge">${{kindName(n.kind)}}</span>
          <span class="badge">${{n.questionCount || qs.length}} 个索引题</span>
          <span class="badge">${{n.patternCount || 0}} 个关联栏目</span>
        </div>
        ${{qs.length ? qs.map(q => `<div class="question">
          <strong>${{escapeHtml(q.source)}}</strong>
          <pre>${{escapeHtml(q.stem)}}</pre>
        </div>`).join('') : '<p class="sub">这个节点目前没有直接索引题，可能只作为栏目或图谱中继节点。</p>'}}
      `;
      render();
    }}

    function escapeHtml(value) {{
      return String(value || '').replace(/[&<>"']/g, ch => ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[ch]));
    }}
    function kindName(value) {{
      return {{ kp: '知识点', pattern: '题型/栏目', skill: '技巧', pitfall: '易错点' }}[value] || value;
    }}

    search.addEventListener('input', render);
    kind.addEventListener('change', render);
    document.querySelectorAll('.legend button').forEach(btn => btn.addEventListener('click', () => {{
      kind.value = btn.dataset.kind;
      render();
    }}));
    window.addEventListener('resize', render);
    render();
  </script>
</body>
</html>
"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a standalone HTML demo for the imported 20260530 knowledge graph.")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    data = fetch_graph(args.db)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(build_html(data), encoding="utf-8")
    print(json.dumps({"output": str(args.output), "summary": data["summary"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
