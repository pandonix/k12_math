from __future__ import annotations

import os
import shutil
import uuid
from pathlib import Path

from fastapi import HTTPException, UploadFile
from sqlmodel import Session

from backend.db import PROJECT_ROOT
from backend.schemas import (
    AttemptCreate,
    IntakeCapabilities,
    IntakeCommitResponse,
    IntakeParseRequest,
    ManualParseResult,
    ParsedMistakeInput,
    QuestionCreate,
    UploadResponse,
)
from backend.services.practice_store import create_attempt
from backend.services.question_store import create_question, get_or_create_question


UPLOAD_ROOT = PROJECT_ROOT / "data" / "uploads"


def capabilities() -> IntakeCapabilities:
    provider = os.environ.get("OCR_PROVIDER", "manual")
    return IntakeCapabilities(
        provider=provider,
        supports_handwriting=provider == "claude" and bool(os.environ.get("ANTHROPIC_API_KEY")),
        supports_pdf=True,
        supports_images=True,
        supports_docx=True,
    )


def save_upload(file: UploadFile) -> UploadResponse:
    upload_id = uuid.uuid4().hex
    original_name = Path(file.filename or "upload.bin").name
    kind = _detect_kind(original_name, file.content_type)
    upload_dir = UPLOAD_ROOT / upload_id
    upload_dir.mkdir(parents=True, exist_ok=True)
    original_path = upload_dir / original_name
    with original_path.open("wb") as out:
        shutil.copyfileobj(file.file, out)

    files = [_display_path(original_path)]
    if kind == "pdf":
        files.extend(_render_pdf_pages(original_path, upload_dir))
    return UploadResponse(upload_id=upload_id, detected_kind=kind, filename=original_name, files=files)


def parse_upload(payload: IntakeParseRequest) -> ManualParseResult:
    upload_dir = _upload_dir(payload.upload_id)
    pages = sorted(
        _display_path(path)
        for path in upload_dir.glob("page-*.png")
    )
    if not pages:
        pages = [
            _display_path(path)
            for path in upload_dir.iterdir()
            if path.is_file()
        ]
    return ManualParseResult(
        task_id=payload.upload_id,
        upload_id=payload.upload_id,
        schema_name=payload.schema_name,
        provider="manual",
        pages=pages,
        questions=[],
        mistakes=[],
    )


def commit_questions(session: Session, questions: list[QuestionCreate]) -> IntakeCommitResponse:
    ids: list[int] = []
    for question in questions:
        created = create_question(session, question)
        ids.append(created.id)
    return IntakeCommitResponse(committed_n=len(ids), question_ids=ids)


def commit_mistakes(session: Session, mistakes: list[ParsedMistakeInput]) -> IntakeCommitResponse:
    question_ids: list[int] = []
    attempt_ids: list[int] = []
    matched = []
    for mistake in mistakes:
        question = get_or_create_question(session, mistake.question)
        question_ids.append(question.id)
        attempt = create_attempt(
            session,
            AttemptCreate(
                question_id=question.id,
                is_correct=mistake.is_correct,
                user_answer_md=mistake.user_answer_md,
                answer_image_path=mistake.answer_image_path,
                source="photo_intake",
                attempted_at=mistake.attempted_at,
                diagnoses=mistake.mistake_hints,
            ),
        )
        attempt_ids.append(attempt.id)
        # create_attempt commits; read the latest mistake response through the API
        # service is intentionally avoided here to keep this return lightweight.
    return IntakeCommitResponse(
        committed_n=len(question_ids),
        question_ids=question_ids,
        attempt_ids=attempt_ids,
        matched_weaknesses=matched,
    )


def _detect_kind(filename: str, content_type: str | None) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix == ".pdf" or content_type == "application/pdf":
        return "pdf"
    if suffix == ".docx":
        return "docx"
    if suffix in {".png", ".jpg", ".jpeg", ".webp"} or (content_type or "").startswith("image/"):
        return "image"
    return "file"


def _render_pdf_pages(pdf_path: Path, upload_dir: Path) -> list[str]:
    try:
        import fitz
    except ImportError as exc:
        raise HTTPException(status_code=500, detail="PyMuPDF is required for PDF preview") from exc

    rendered: list[str] = []
    doc = fitz.open(pdf_path)
    try:
        for index, page in enumerate(doc):
            pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
            out_path = upload_dir / f"page-{index + 1}.png"
            pix.save(out_path)
            rendered.append(_display_path(out_path))
    finally:
        doc.close()
    return rendered


def _upload_dir(upload_id: str) -> Path:
    upload_dir = UPLOAD_ROOT / upload_id
    if not upload_dir.exists() or not upload_dir.is_dir():
        raise HTTPException(status_code=404, detail="Upload not found")
    return upload_dir


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)
