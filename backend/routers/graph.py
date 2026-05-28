from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from backend.db import get_session
from backend.models import KnowledgePoint
from backend.routers.kp import _detail
from backend.schemas import GraphKpResponse


router = APIRouter(prefix="/api/graph", tags=["graph"])


@router.get("/kp/{kp_id}", response_model=GraphKpResponse)
def get_kp_graph(kp_id: str, session: Session = Depends(get_session)) -> GraphKpResponse:
    kp = session.get(KnowledgePoint, kp_id)
    if not kp:
        raise HTTPException(status_code=404, detail="Knowledge point not found")

    return GraphKpResponse(
        kp=_detail(kp),
        patterns=[],
        skills=[],
        pitfalls=[],
        questions=[],
        edges=[],
    )
