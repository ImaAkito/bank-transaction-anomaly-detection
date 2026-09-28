"""Клиенты: профиль поведения и история активности."""
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session, joinedload

from app.db import get_db
from app.domain.profile import summarize
from app.models import Analysis, Client, Transaction
from app.schemas import ClientDetail, ClientRow
from app.services.pipeline import serialize

router = APIRouter(prefix="/api/clients", tags=["clients"])


@router.get("", response_model=list[ClientRow])
def list_clients(
    search: str | None = None,
    only_flagged: bool = False,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    flagged = func.sum(case((Analysis.risk_level != "low", 1), else_=0))
    query = (
        select(
            Transaction.client_id,
            func.count(Transaction.id),
            flagged,
            func.max(Transaction.timestamp),
            func.max(Analysis.anomaly_score),
        )
        .join(Analysis, Analysis.transaction_pk == Transaction.id)
        .group_by(Transaction.client_id)
    )
    if search:
        query = query.where(Transaction.client_id.ilike(f"%{search.strip()}%"))
    if only_flagged:
        query = query.having(flagged > 0)
    rows = db.execute(query.order_by(flagged.desc(), Transaction.client_id).limit(limit).offset(offset)).all()
    return [
        ClientRow(
            client_id=r[0],
            transactions=r[1],
            flagged=int(r[2] or 0),
            last_seen=r[3],
            max_score=float(r[4] or 0.0),
        )
        for r in rows
    ]


@router.get("/{client_id}", response_model=ClientDetail)
def client_detail(client_id: str, limit: int = Query(default=200, ge=1, le=1000), db: Session = Depends(get_db)):
    client = db.get(Client, client_id)
    if client is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Клиент не найден")
    rows = db.scalars(
        select(Transaction)
        .where(Transaction.client_id == client_id)
        .options(joinedload(Transaction.analysis))
        .order_by(Transaction.timestamp.desc(), Transaction.id.desc())
        .limit(limit)
    ).all()
    return {
        "client_id": client.id,
        "first_seen": client.first_seen,
        "last_seen": client.last_seen,
        "profile": summarize(client.profile),
        "recent": [serialize(t, t.analysis) for t in rows],
    }
