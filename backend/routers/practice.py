from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session

from backend.db import get_session
from backend.schemas import (
    AttemptCreate,
    AttemptRead,
    DiagnosisInput,
    DiagnosisRead,
    MistakeListResponse,
    MistakePatch,
    MistakeRead,
)
from backend.services.practice_store import (
    add_diagnosis,
    create_attempt,
    get_attempt,
    list_diagnoses,
    list_mistakes,
    patch_mistake,
)


router = APIRouter(prefix="/api", tags=["practice"])


@router.post("/attempts", response_model=AttemptRead, status_code=201)
def attempts_create(payload: AttemptCreate, session: Session = Depends(get_session)) -> AttemptRead:
    return create_attempt(session, payload)


@router.get("/attempts/{attempt_id}", response_model=AttemptRead)
def attempts_show(attempt_id: int, session: Session = Depends(get_session)) -> AttemptRead:
    return get_attempt(session, attempt_id)


@router.get("/attempts/{attempt_id}/diagnoses", response_model=list[DiagnosisRead])
def diagnoses_index(attempt_id: int, session: Session = Depends(get_session)) -> list[DiagnosisRead]:
    return list_diagnoses(session, attempt_id)


@router.post("/attempts/{attempt_id}/diagnoses", response_model=DiagnosisRead, status_code=201)
def diagnoses_create(
    attempt_id: int,
    payload: DiagnosisInput,
    session: Session = Depends(get_session),
) -> DiagnosisRead:
    return add_diagnosis(session, attempt_id, payload)


@router.get("/mistakes", response_model=MistakeListResponse)
def mistakes_index(
    include_mastered: bool = Query(default=False),
    session: Session = Depends(get_session),
) -> MistakeListResponse:
    return list_mistakes(session, include_mastered=include_mastered)


@router.patch("/mistakes/{question_id}", response_model=MistakeRead)
def mistakes_update(
    question_id: int,
    payload: MistakePatch,
    session: Session = Depends(get_session),
) -> MistakeRead:
    return patch_mistake(session, question_id, payload)
