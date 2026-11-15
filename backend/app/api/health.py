from __future__ import annotations

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.database import get_db

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: str
    service: str = "callos-ai"
    version: str = "0.1.0"
    environment: str
    database: str
    integration_mode: str


@router.get("/health", response_model=HealthResponse, summary="Liveness and database check")
@router.get("/api/health", response_model=HealthResponse, include_in_schema=False)
def health(response: Response, db: Session = Depends(get_db),
           settings: Settings = Depends(get_settings)) -> HealthResponse:
    try:
        db.execute(text("SELECT 1"))
        database = "ok"
    except Exception:  # noqa: BLE001
        database = "unavailable"
        response.status_code = 503
    return HealthResponse(status="ok" if database == "ok" else "degraded", environment=settings.env,
                          database=database, integration_mode=settings.integration_mode)
