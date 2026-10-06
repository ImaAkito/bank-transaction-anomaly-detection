"""Служебные конечные точки: состояние, статистика, модель, метрики."""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import case, func, select, text
from sqlalchemy.orm import Session

import threading

from app.api.deps import can_read, is_admin
from app.db import get_db, session_factory
from app.models import Analysis, Client, ModelEvent, Transaction
from app.security import Principal
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
def stats(_: Principal = Depends(can_read), db: Session = Depends(get_db)):
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


def experiment_runs(settings) -> list[dict]:
    """Все результаты экспериментов: каталоги experiments/*/summary.json (синтетика, IBM и т. д.)."""
    runs = []
    base = Path(settings.experiments_dir)
    paths = sorted(base.glob("*/summary.json")) if base.is_dir() else []
    default = Path(settings.experiments_summary_path)
    if default.is_file() and default not in paths:
        paths.insert(0, default)
    for path in paths:
        try:
            summary = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        datasets = summary.get("datasets") or [{}]
        runs.append({
            "name": path.parent.name,
            "path": str(path),
            "rows": datasets[0].get("rows"),
            "anomaly_share": datasets[0].get("anomaly_share"),
            "summary": summary,
        })
    return runs


@router.get("/api/model")
def model_info(request: Request, _: Principal = Depends(can_read)):
    state = request.app.state
    if not state.model_store.loaded:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Модель не загружена")
    info = state.model_store.get().info()
    info["metrics"] = {k: v for k, v in info["metrics"].items() if k != "search"}
    runs = experiment_runs(state.settings)
    default = next((r for r in runs if Path(r["path"]) == Path(state.settings.experiments_summary_path)), None)
    return {
        "model": info,
        "experiments": (default or (runs[0] if runs else {})).get("summary"),
        "experiment_runs": [{k: v for k, v in r.items() if k != "path"} for r in runs],
    }


@router.post("/api/model/reload")
def reload_model(request: Request, _: Principal = Depends(is_admin)):
    """Перезагрузка артефакта модели после переобучения."""
    if not request.app.state.model_store.try_load():
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Не удалось загрузить модель")
    return {"version": request.app.state.model_store.get().version}


@router.get("/api/model/drift")
def model_drift(request: Request, _: Principal = Depends(can_read), db: Session = Depends(get_db)):
    """Дрейф данных: PSI признаков последних операций относительно обучающей выборки, сдвиг доли оповещений."""
    from app.ml.retrain import recent_drift

    state = request.app.state
    if not state.model_store.loaded:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Модель не загружена")
    drift = recent_drift(db, state.model_store.get(), state.settings)
    if drift.get("available"):
        from app.domain.features import FEATURE_LABELS_RU

        metrics.DRIFT_MAX_PSI.set(drift["max_psi"])
        for item in drift.get("features", []):
            item["label"] = FEATURE_LABELS_RU.get(item["feature"], item["feature"])
    return drift


@router.post("/api/model/retrain", status_code=status.HTTP_202_ACCEPTED)
def start_retrain(request: Request, principal: Principal = Depends(is_admin)):
    """Запускает переобучение в фоне; результат записывается в журнал модели (/api/model/events)."""
    from app.ml.retrain import retrain

    settings = request.app.state.settings
    store = request.app.state.model_store
    if getattr(request.app.state, "retrain_running", False):
        raise HTTPException(status.HTTP_409_CONFLICT, "Переобучение уже выполняется")

    def run() -> None:
        request.app.state.retrain_running = True
        db = session_factory()()
        try:
            result = retrain(settings, db, reason=f"manual:{principal.username}")
            if result.get("status") == "deployed":
                store.try_load()
        except Exception as exc:  # ошибка фиксируется в журнале модели
            db.rollback()
            db.add(ModelEvent(event_type="retrain_failed", model_version=None, details={"error": repr(exc)}))
            db.commit()
        finally:
            db.close()
            request.app.state.retrain_running = False

    threading.Thread(target=run, name="retrain", daemon=True).start()
    return {"status": "started"}


@router.get("/api/model/events")
def model_events(limit: int = 50, _: Principal = Depends(can_read), db: Session = Depends(get_db)):
    rows = db.scalars(select(ModelEvent).order_by(ModelEvent.id.desc()).limit(min(limit, 200)))
    return [
        {"id": e.id, "event_type": e.event_type, "model_version": e.model_version, "details": e.details,
         "created_at": e.created_at}
        for e in rows
    ]


@router.get("/metrics", include_in_schema=False)
def prometheus_metrics(request: Request):
    metrics.QUEUE_DEPTH.set(_safe_depth(request.app.state.queue) or 0)
    metrics.WS_CLIENTS.set(request.app.state.manager.count)
    return Response(generate_latest(metrics.REGISTRY), media_type=CONTENT_TYPE_LATEST)
