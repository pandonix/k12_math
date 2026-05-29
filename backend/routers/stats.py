from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session

from backend.db import get_session
from backend.schemas import (
    StatsKpHeatmapItem,
    StatsTrendPoint,
    StatsTypeRadarItem,
    StatsWeaknessDetail,
    StatsWeaknessItem,
)
from backend.services.stats_store import heatmap, personal_pitfalls, trend, type_radar, weak_top, weakness_detail


router = APIRouter(prefix="/api/stats", tags=["stats"])


@router.get("/weak_top", response_model=list[StatsWeaknessItem])
def stats_weak_top(
    limit: int = Query(default=10, ge=1, le=50),
    session: Session = Depends(get_session),
) -> list[StatsWeaknessItem]:
    return weak_top(session, limit=limit)


@router.get("/weaknesses/{weakness_id}", response_model=StatsWeaknessDetail)
def stats_weakness_show(weakness_id: int, session: Session = Depends(get_session)) -> StatsWeaknessDetail:
    return weakness_detail(session, weakness_id)


@router.get("/heatmap", response_model=list[StatsKpHeatmapItem])
def stats_heatmap(session: Session = Depends(get_session)) -> list[StatsKpHeatmapItem]:
    return heatmap(session)


@router.get("/type_radar", response_model=list[StatsTypeRadarItem])
def stats_type_radar(
    limit: int = Query(default=12, ge=1, le=30),
    session: Session = Depends(get_session),
) -> list[StatsTypeRadarItem]:
    return type_radar(session, limit=limit)


@router.get("/personal_pitfalls", response_model=list[StatsWeaknessItem])
def stats_personal_pitfalls(
    limit: int = Query(default=10, ge=1, le=50),
    session: Session = Depends(get_session),
) -> list[StatsWeaknessItem]:
    return personal_pitfalls(session, limit=limit)


@router.get("/trend", response_model=list[StatsTrendPoint])
def stats_trend(
    period: str = Query(default="week", pattern="^(week|month|quarter|all)$"),
    session: Session = Depends(get_session),
) -> list[StatsTrendPoint]:
    return trend(session, period=period)
