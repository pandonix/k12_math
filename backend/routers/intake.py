from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, File, UploadFile
from sqlmodel import Session

from backend.db import get_session
from backend.schemas import DocxImportRequest, ParsedLearningMaterial
from backend.schemas import IntakeCapabilities, IntakeCommitResponse, IntakeParseRequest, ManualParseResult, ParsedMistakeInput, QuestionCreate, UploadResponse
from backend.services.importers.docx_handout import DEFAULT_DOCX, import_docx_handout
from backend.services.intake_store import capabilities, commit_mistakes, commit_questions, parse_upload, save_upload


router = APIRouter(prefix="/api/intake", tags=["intake"])


@router.get("/capabilities", response_model=IntakeCapabilities)
def get_capabilities() -> IntakeCapabilities:
    return capabilities()


@router.post("/upload", response_model=UploadResponse)
def upload_file(file: UploadFile = File(...)) -> UploadResponse:
    return save_upload(file)


@router.post("/parse", response_model=ManualParseResult)
def parse_file(payload: IntakeParseRequest) -> ManualParseResult:
    return parse_upload(payload)


@router.get("/parse/{task_id}", response_model=ManualParseResult)
def get_parse_result(task_id: str) -> ManualParseResult:
    return parse_upload(IntakeParseRequest(upload_id=task_id))


@router.post("/import/docx", response_model=ParsedLearningMaterial)
def import_docx(payload: DocxImportRequest | None = None) -> ParsedLearningMaterial:
    docx_path = Path(payload.path).expanduser() if payload and payload.path else DEFAULT_DOCX
    return import_docx_handout(docx_path)


@router.post("/questions/commit", response_model=IntakeCommitResponse)
def commit_question_intake(
    payload: list[QuestionCreate],
    session: Session = Depends(get_session),
) -> IntakeCommitResponse:
    return commit_questions(session, payload)


@router.post("/mistakes/commit", response_model=IntakeCommitResponse)
def commit_mistake_intake(
    payload: list[ParsedMistakeInput],
    session: Session = Depends(get_session),
) -> IntakeCommitResponse:
    return commit_mistakes(session, payload)
