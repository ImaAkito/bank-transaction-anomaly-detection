"""Приём транзакций и работа с результатами анализа."""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, joinedload

from app.api.deps import can_ingest, can_read, can_review, get_service
from app.security import Principal
from app.db import get_db
from app.domain.preprocessing import PreprocessingError
from app.models import AlertHistory, Analysis, Transaction
from app.schemas import (
    AlertHistoryOut,
    QueuedOut,
    ReviewIn,
    TransactionIn,
    TransactionOut,
    TransactionPage,
)
from app.services.pipeline import (
    AnalysisService,
    ModelNotLoadedError,
    TransactionNotFoundError,
    serialize,
)

router = APIRouter(prefix="/api", tags=["transactions"])

SORT_COLUMNS = {
    "timestamp": Transaction.timestamp,
    "score": Analysis.anomaly_score,
    "received": Transaction.received_at,
}


@router.post("/transactions", response_model=TransactionOut)
def analyze_transaction(
    payload: TransactionIn,
    response: Response,
    _: Principal = Depends(can_ingest),
    service: AnalysisService = Depends(get_service),
    db: Session = Depends(get_db),
):
    """Синхронная обработка: результат анализа возвращается в ответе.

    Повторная отправка транзакции с тем же transaction_id возвращает ранее рассчитанный результат (200),
    для новой транзакции возвращается 201.
    """
    try:
        result, created = service.process(db, payload)
    except PreprocessingError as exc:
        raise HTTPException(422, str(exc)) from exc
    except ModelNotLoadedError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    return result


@router.post("/transactions/enqueue", response_model=QueuedOut, status_code=status.HTTP_202_ACCEPTED)
def enqueue_transaction(payload: TransactionIn, request: Request, _: Principal = Depends(can_ingest)):
    """Асинхронный приём: транзакция ставится в очередь, результат приходит по WebSocket и доступен в списке."""
    request.app.state.queue.enqueue(payload.model_dump(mode="json"))
    return QueuedOut(transaction_id=payload.transaction_id, queue_depth=request.app.state.queue.depth())


def _filtered_query(
    risk: list[str] | None,
    status_values: list[str] | None,
    client_id: str | None,
    min_score: float | None,
    category: str | None,
    channel: str | None,
    date_from: datetime | None,
    date_to: datetime | None,
    only_flagged: bool,
    search: str | None,
):
    conditions = []
    if risk:
        conditions.append(Analysis.risk_level.in_(risk))
    if status_values:
        conditions.append(Analysis.status.in_(status_values))
    if client_id:
        conditions.append(Transaction.client_id == client_id)
    if min_score is not None:
        conditions.append(Analysis.anomaly_score >= min_score)
    if category:
        conditions.append(Transaction.category == category.lower())
    if channel:
        conditions.append(Transaction.channel == channel.lower())
    if date_from:
        conditions.append(Transaction.timestamp >= date_from)
    if date_to:
        conditions.append(Transaction.timestamp <= date_to)
    if only_flagged:
        conditions.append(Analysis.risk_level != "low")
    if search:
        like = f"%{search.strip()}%"
        conditions.append(or_(Transaction.transaction_id.ilike(like), Transaction.client_id.ilike(like)))
    return conditions


@router.get("/transactions", response_model=TransactionPage)
def list_transactions(
    risk: list[str] | None = Query(default=None, description="low, medium, high (можно несколько)"),
    status_values: list[str] | None = Query(default=None, alias="status"),
    client_id: str | None = None,
    min_score: float | None = Query(default=None, ge=0, le=1),
    category: str | None = None,
    channel: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    only_flagged: bool = False,
    search: str | None = None,
    sort: str = Query(default="received", pattern="^(timestamp|score|received)$"),
    order: str = Query(default="desc", pattern="^(asc|desc)$"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    _: Principal = Depends(can_read),
    db: Session = Depends(get_db),
):
    conditions = _filtered_query(
        risk, status_values, client_id, min_score, category, channel, date_from, date_to, only_flagged, search
    )
    base = select(Transaction).join(Analysis, Analysis.transaction_pk == Transaction.id)
    total = db.scalar(
        select(func.count()).select_from(Transaction).join(Analysis, Analysis.transaction_pk == Transaction.id).where(*conditions)
    )
    column = SORT_COLUMNS[sort]
    ordering = column.desc() if order == "desc" else column.asc()
    rows = db.scalars(
        base.where(*conditions)
        .options(joinedload(Transaction.analysis))
        .order_by(ordering, Transaction.id.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    return {"items": [serialize(t, t.analysis) for t in rows], "total": total or 0, "limit": limit, "offset": offset}


@router.get("/transactions/{transaction_id}", response_model=TransactionOut)
def get_transaction(transaction_id: str, _: Principal = Depends(can_read), db: Session = Depends(get_db)):
    row = db.scalar(
        select(Transaction)
        .where(Transaction.transaction_id == transaction_id)
        .options(joinedload(Transaction.analysis))
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Транзакция не найдена")
    return serialize(row, row.analysis)


@router.patch("/transactions/{transaction_id}/review", response_model=TransactionOut)
def review_transaction(
    transaction_id: str,
    body: ReviewIn,
    request: Request,
    principal: Principal = Depends(can_review),
    service: AnalysisService = Depends(get_service),
    db: Session = Depends(get_db),
):
    """Решение специалиста. Оценка модели остаётся аналитической и не означает установленного мошенничества."""
    try:
        # При включённой аутентификации автор решения — вошедший пользователь, а не значение из запроса.
        reviewer = principal.username if request.app.state.settings.auth_enabled else (body.reviewer or "analyst")
        return service.review(db, transaction_id, body.status, reviewer, body.comment)
    except TransactionNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Транзакция не найдена") from exc


@router.get("/alerts/history", response_model=list[AlertHistoryOut])
def alert_history(
    client_id: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    _: Principal = Depends(can_read),
    db: Session = Depends(get_db),
):
    query = select(AlertHistory).order_by(AlertHistory.id.desc()).limit(limit)
    if client_id:
        query = query.where(AlertHistory.client_id == client_id)
    return list(db.scalars(query))
