from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Response, status
from sqlmodel import Session

from backend.db import get_session
from backend.schemas import QuestionCreate, QuestionListResponse, QuestionRead, QuestionUpdate
from backend.services.question_store import (
    create_question,
    delete_question,
    get_question,
    list_questions,
    update_question,
)


router = APIRouter(prefix="/api/questions", tags=["questions"])


@router.get("", response_model=QuestionListResponse)
def questions_index(
    kp: str | None = None,
    pattern: int | None = None,
    skill: int | None = None,
    pitfall: int | None = None,
    difficulty: int | None = None,
    q: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=30, ge=1, le=100),
    session: Session = Depends(get_session),
) -> QuestionListResponse:
    return list_questions(
        session,
        kp=kp,
        pattern=pattern,
        skill=skill,
        pitfall=pitfall,
        difficulty=difficulty,
        q=q,
        page=page,
        page_size=page_size,
    )


@router.post("", response_model=QuestionRead, status_code=status.HTTP_201_CREATED)
def questions_create(
    payload: QuestionCreate,
    session: Session = Depends(get_session),
) -> QuestionRead:
    return create_question(session, payload)


@router.get("/{question_id}", response_model=QuestionRead)
def questions_show(question_id: int, session: Session = Depends(get_session)) -> QuestionRead:
    return get_question(session, question_id)


@router.patch("/{question_id}", response_model=QuestionRead)
def questions_update(
    question_id: int,
    payload: QuestionUpdate,
    session: Session = Depends(get_session),
) -> QuestionRead:
    return update_question(session, question_id, payload)


@router.delete("/{question_id}", status_code=status.HTTP_204_NO_CONTENT)
def questions_delete(question_id: int, session: Session = Depends(get_session)) -> Response:
    delete_question(session, question_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{question_id}/related", response_model=QuestionListResponse)
def questions_related(
    question_id: int,
    session: Session = Depends(get_session),
) -> QuestionListResponse:
    question = get_question(session, question_id)
    if question.knowledge_points:
        return list_questions(session, kp=question.knowledge_points[0].id, page_size=12)
    if question.patterns:
        return list_questions(session, pattern=question.patterns[0].id, page_size=12)
    return QuestionListResponse(total=0, page=1, page_size=12, items=[])
