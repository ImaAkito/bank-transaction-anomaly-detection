"""Служебные конечные точки: состояние, статистика, модель, метрики."""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import case, func, select, text
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Analysis, Client, Transaction
from app.services import metrics

router = APIRouter(tags=["system"])


@router.get("/api/health")
def health(request: Request, db: Session = Depends(get_db)):
    state = request.app.state
    db_ok = True
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        db_ok = False
    body = {
        "status": "ok" if db_ok and state.model_store.loaded else "degraded",
        "database": db_ok,
        "model_loaded": state.model_store.loaded,
        "queue_backend": state.settings.queue_backend,
        "queue_depth": _safe_depth(state.queue),
        "websocket_clients": state.manager.count,
    }
    return body


def _safe_depth(queue) -> int | None:
    try:
        return queue.depth()
    except Exception:
        return None


@router.get("/api/stats")
def stats(db: Session = Depends(get_db)):
    total = db.scalar(select(func.count(Analysis.id))) or 0
    by_risk = {"low": 0, "medium": 0, "high": 0}
    for level, count in db.execute(select(Analysis.risk_level, func.count()).group_by(Analysis.risk_level)):
        by_risk[level] = count
    by_status = dict(db.execute(select(Analysis.status, func.count()).group_by(Analysis.status)).all())
    since = datetime.now(timezone.utc) - timedelta(minutes=1)
    last_minute = db.scalar(select(func.count(Transaction.id)).where(Transaction.received_at >= since)) or 0
    avg_latency = db.scalar(select(func.avg(Analysis.latency_ms))) or 0.0
    clients = db.scalar(select(func.count(Client.id))) or 0

    # Сравнение с метками симулятора (только для демонстрации): «помечено» означает риск выше низкого.
    flagged = Analysis.risk_level != "low"
    tp, fp, fn, tn = db.execute(
        select(
            func.sum(case((flagged & (Transaction.simulation_label.is_(True)), 1), else_=0)),
            func.sum(case((flagged & (Transaction.simulation_label.is_(False)), 1), else_=0)),
            func.sum(case((~flagged & (Transaction.simulation_label.is_(True)), 1), else_=0)),
            func.sum(case((~flagged & (Transaction.simulation_label.is_(False)), 1), else_=0)),
        )
        .select_from(Transaction)
        .join(Analysis, Analysis.transaction_pk == Transaction.id)
    ).one()
    tp, fp, fn, tn = (int(v or 0) for v in (tp, fp, fn, tn))
    simulation = None
    if tp + fp + fn + tn:
        simulation = {
            "labeled": tp + fp + fn + tn,
            "true_positive": tp,
            "false_positive": fp,
            "false_negative": fn,
            "true_negative": tn,
            "precision": tp / (tp + fp) if tp + fp else None,
            "recall": tp / (tp + fn) if tp + fn else None,
        }
    return {
        "total_transactions": total,
        "clients": clients,
        "by_risk": by_risk,
        "by_status": by_status,
        "flagged_share": (by_risk["medium"] + by_risk["high"]) / total if total else 0.0,
        "transactions_last_minute": last_minute,
        "avg_latency_ms": float(avg_latency),
        "simulation_check": simulation,
    }


@router.get("/api/model")
def model_info(request: Request):
    state = request.app.state
    if not state.model_store.loaded:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Модель не загружена")
    info = state.model_store.get().info()
    info["metrics"] = {k: v for k, v in info["metrics"].items() if k != "search"}
    experiments = None
    path = Path(state.settings.experiments_summary_path)
    if path.is_file():
        experiments = json.loads(path.read_text(encoding="utf-8"))
    return {"model": info, "experiments": experiments}


@router.post("/api/model/reload")
def reload_model(request: Request):
    """Перезагрузка артефакта модели после переобучения."""
    if not request.app.state.model_store.try_load():
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Не удалось загрузить модель")
    return {"version": request.app.state.model_store.get().version}


@router.get("/metrics", include_in_schema=False)
def prometheus_metrics(request: Request):
    metrics.QUEUE_DEPTH.set(_safe_depth(request.app.state.queue) or 0)
    metrics.WS_CLIENTS.set(request.app.state.manager.count)
    return Response(generate_latest(metrics.REGISTRY), media_type=CONTENT_TYPE_LATEST)
