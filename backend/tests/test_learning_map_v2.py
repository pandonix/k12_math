from __future__ import annotations

from pathlib import Path

from sqlmodel import Session, create_engine, text

from backend.db import run_migrations
from backend.schemas import AttemptCreate, NamedNodeInput, QuestionCreate, WeightedKpInput
from backend.services.kp_sync import sync_knowledge_points
from backend.services.learning_map import (
    learning_map_node_detail,
    learning_map_summary,
    list_learning_map_nodes,
)
from backend.services.practice_store import create_attempt
from backend.services.question_store import create_question, list_questions


def _session(tmp_path: Path) -> Session:
    db_path = tmp_path / "math.db"
    run_migrations(db_path=db_path)
    engine = create_engine(f"sqlite:///{db_path}")
    session = Session(engine)
    sync_knowledge_points(session)
    return session


def _first_kp_id(session: Session) -> str:
    return session.exec(
        text("SELECT id FROM knowledge_points ORDER BY order_index LIMIT 1")
    ).one().id


def test_question_entry_materializes_pattern_skill_and_pitfall_edges(tmp_path: Path) -> None:
    with _session(tmp_path) as session:
        kp_id = _first_kp_id(session)
        created = create_question(
            session,
            QuestionCreate(
                source="学习地图 v2 样题",
                stem_md="已知集合 A，判断元素与集合的关系。",
                kp_ids=[WeightedKpInput(id=kp_id, is_primary=True)],
                patterns=[NamedNodeInput(name="题型01 集合元素关系判定", is_primary=True)],
                skills=[NamedNodeInput(name="方法技巧01 符号翻译")],
                pitfalls=[NamedNodeInput(name="易混易错01 属于号和包含号混淆")],
            ),
        )
        pattern_id = created.patterns[0].id

        skill_edge_count = session.exec(
            text("SELECT COUNT(*) AS count FROM pattern_skills WHERE pattern_id = :pattern_id"),
            params={"pattern_id": pattern_id},
        ).one().count
        pitfall_edge_count = session.exec(
            text("SELECT COUNT(*) AS count FROM pattern_pitfalls WHERE pattern_id = :pattern_id"),
            params={"pattern_id": pattern_id},
        ).one().count
        detail = learning_map_node_detail(session, "pattern", str(pattern_id))

    assert skill_edge_count == 1
    assert pitfall_edge_count == 1
    assert detail["node"]["display_name"] == "集合元素关系判定"
    assert detail["related"]["skills"][0]["display_name"] == "符号翻译"
    assert detail["related"]["pitfalls"][0]["display_name"] == "属于号和包含号混淆"
    assert detail["questions"][0]["id"] == created.id


def test_learning_map_lists_all_node_types_and_cold_start_default(tmp_path: Path) -> None:
    with _session(tmp_path) as session:
        kp_id = _first_kp_id(session)
        create_question(
            session,
            QuestionCreate(
                stem_md="学习地图冷启动样题",
                kp_ids=[WeightedKpInput(id=kp_id, is_primary=True)],
                patterns=[NamedNodeInput(name="题型02 冷启动题型")],
                skills=[NamedNodeInput(name="方法技巧02 冷启动技巧")],
                pitfalls=[NamedNodeInput(name="易混易错02 冷启动易错")],
            ),
        )

        summary = learning_map_summary(session)
        kps = list_learning_map_nodes(session, "kp")
        patterns = list_learning_map_nodes(session, "pattern")
        skills = list_learning_map_nodes(session, "skill")
        pitfalls = list_learning_map_nodes(session, "pitfall")

    assert summary["readiness"]["has_enough_personal_data"] is False
    assert summary["readiness"]["default_entry"] == "kp"
    assert kps
    assert patterns[0]["display_name"] == "冷启动题型"
    assert skills[0]["display_name"] == "冷启动技巧"
    assert pitfalls[0]["display_name"] == "冷启动易错"


def test_personal_readiness_switches_to_weakness_after_enough_evidence(tmp_path: Path) -> None:
    with _session(tmp_path) as session:
        kp_id = _first_kp_id(session)
        questions = [
            create_question(
                session,
                QuestionCreate(
                    stem_md=f"足够证据样题 {index}",
                    kp_ids=[WeightedKpInput(id=kp_id, is_primary=True)],
                    patterns=[NamedNodeInput(name="证据题型")],
                    skills=[NamedNodeInput(name="证据技巧")],
                    pitfalls=[NamedNodeInput(name="证据易错")],
                ),
            )
            for index in range(3)
        ]
        for question in questions:
            create_attempt(session, AttemptCreate(question_id=question.id, is_correct=False))
        for _ in range(2):
            create_attempt(session, AttemptCreate(question_id=questions[0].id, is_correct=True))

        summary = learning_map_summary(session)
        weaknesses = list_learning_map_nodes(session, "weakness")

    assert summary["readiness"]["has_enough_personal_data"] is True
    assert summary["readiness"]["default_entry"] == "weakness"
    assert len(weaknesses) >= 2


def test_question_list_filters_by_learning_map_dimensions(tmp_path: Path) -> None:
    with _session(tmp_path) as session:
        kp_id = _first_kp_id(session)
        question = create_question(
            session,
            QuestionCreate(
                stem_md="题库筛选样题",
                kp_ids=[WeightedKpInput(id=kp_id, is_primary=True)],
                patterns=[NamedNodeInput(name="筛选题型")],
                skills=[NamedNodeInput(name="筛选技巧")],
                pitfalls=[NamedNodeInput(name="筛选易错")],
            ),
        )

        by_pattern = list_questions(session, pattern=question.patterns[0].id)
        by_skill = list_questions(session, skill=question.skills[0].id)
        by_pitfall = list_questions(session, pitfall=question.pitfalls[0].id)

    assert by_pattern.items[0].id == question.id
    assert by_skill.items[0].id == question.id
    assert by_pitfall.items[0].id == question.id
