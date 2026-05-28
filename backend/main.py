from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlmodel import Session

from backend.db import engine, get_db_path, run_migrations
from backend.routers import admin, graph, kp
from backend.services.kp_sync import sync_knowledge_points


@asynccontextmanager
async def lifespan(app: FastAPI):
    run_migrations()
    with Session(engine) as session:
        result = sync_knowledge_points(session)
        if result.duplicate_ids:
            raise RuntimeError(
                "Knowledge point sync produced duplicate ids: "
                f"{result.duplicate_ids}. Refusing to start — investigate "
                "the markdown source before any question or attempt is written."
            )
    yield


app = FastAPI(
    title="Math Weakness Graph",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:8000",
        "http://localhost:8000",
    ],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(kp.router)
app.include_router(graph.router)
app.include_router(admin.router)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "db": str(get_db_path())}
