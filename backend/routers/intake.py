from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter

from backend.schemas import DocxImportRequest, ParsedLearningMaterial
from backend.services.importers.docx_handout import DEFAULT_DOCX, import_docx_handout


router = APIRouter(prefix="/api/intake", tags=["intake"])


@router.post("/import/docx", response_model=ParsedLearningMaterial)
def import_docx(payload: DocxImportRequest | None = None) -> ParsedLearningMaterial:
    docx_path = Path(payload.path).expanduser() if payload and payload.path else DEFAULT_DOCX
    return import_docx_handout(docx_path)
