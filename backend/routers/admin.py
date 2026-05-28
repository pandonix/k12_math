from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from backend.db import get_session
from backend.schemas import SyncResponse
from backend.services.kp_sync import sync_knowledge_points


router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.post("/sync-kp", response_model=SyncResponse)
def sync_kp(session: Session = Depends(get_session)) -> SyncResponse:
    result = sync_knowledge_points(session)
    if result.duplicate_ids:
        raise HTTPException(
            status_code=409,
            detail={"message": "Duplicate knowledge point ids", "ids": result.duplicate_ids},
        )
    return SyncResponse(**result.__dict__)
