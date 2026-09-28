"""Ядро обработки: приём → предобработка → признаки → профиль → оценка → интерпретация → сохранение."""
import copy
import logging
import threading
import time
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import Settings
from app.domain.features import to_vector, compute_features
from app.domain.preprocessing import Tx, normalize
from app.domain.profile import new_profile, update_activity, update_behavior
from app.ml.explain import build_reasons, shap_factors, summarize
from app.ml.model import ModelBundle, load_bundle
from app.models import AlertHistory, Analysis, Client, Transaction
from app.schemas import TransactionIn
from app.services import metrics
from app.services.events import EventBus

log = logging.getLogger(__name__)

STATUS_NORMAL = "normal"
STATUS_REVIEW = "needs_review"


class ModelNotLoadedError(RuntimeError):
    pass


class TransactionNotFoundError(LookupError):
    pass


class ModelStore:
    """Хранит загруженную модель; позволяет перезагрузить артефакт без перезапуска сервиса."""

    def __init__(self, path: str) -> None:
        self.path = path
        self._bundle: ModelBundle | None = None
        self._lock = threading.Lock()

    def load(self) -> ModelBundle:
        with self._lock:
            self._bundle = load_bundle(self.path)
            log.info("Модель загружена: %s (%s)", self._bundle.version, self.path)
            return self._bundle

    def try_load(self) -> bool:
        try:
            self.load()
            return True
        except Exception:
            log.exception("Не удалось загрузить модель из %s", self.path)
            return False

    def get(self) -> ModelBundle:
        if self._bundle is None:
            raise ModelNotLoadedError("Модель не загружена")
        return self._bundle

    @property
    def loaded(self) -> bool:
        return self._bundle is not None


_LOCK_STRIPES = [threading.Lock() for _ in range(256)]


def client_lock(client_id: str) -> threading.Lock:
    """Транзакции одного клиента обновляют его профиль строго последовательно."""
    return _LOCK_STRIPES[hash(client_id) % len(_LOCK_STRIPES)]


def _tx_from_row(row: Transaction, rates: dict[str, float]) -> Tx:
    return normalize(
        {
            "transaction_id": row.transaction_id,
            "client_id": row.client_id,
            "timestamp": row.timestamp,
            "amount": row.amount,
            "currency": row.currency,
            "category": row.category,
            "channel": row.channel,
            "recipient_id": row.recipient_id,
            "recipient_category": row.recipient_category,
            "extra": row.extra,
        },
        rates,
    )


def serialize(tx: Transaction, analysis: Analysis) -> dict[str, Any]:
    return {
        "transaction_id": tx.transaction_id,
        "client_id": tx.client_id,
        "timestamp": tx.timestamp,
        "amount": tx.amount,
        "currency": tx.currency,
        "amount_base": tx.amount_base,
        "category": tx.category,
        "channel": tx.channel,
        "recipient_id": tx.recipient_id,
        "recipient_category": tx.recipient_category,
        "extra": tx.extra,
        "simulation_label": tx.simulation_label,
        "simulation_anomaly_type": tx.simulation_anomaly_type,
        "received_at": tx.received_at,
        "analysis": {
            "anomaly_score": analysis.anomaly_score,
            "risk_level": analysis.risk_level,
            "status": analysis.status,
            "summary": analysis.summary,
            "deviation_types": analysis.deviation_types,
            "reasons": analysis.reasons,
            "factors": analysis.factors,
            "features": analysis.features,
            "model_version": analysis.model_version,
            "model_kind": analysis.model_kind,
            "latency_ms": analysis.latency_ms,
            "profile_updated": analysis.profile_updated,
            "reviewed_by": analysis.reviewed_by,
            "reviewed_at": analysis.reviewed_at,
            "review_comment": analysis.review_comment,
            "created_at": analysis.created_at,
        },
    }


class AnalysisService:
    def __init__(self, settings: Settings, model_store: ModelStore, event_bus: EventBus) -> None:
        self.settings = settings
        self.model_store = model_store
        self.event_bus = event_bus

    # ------------------------------------------------------------------ приём и анализ
    def process(self, db: Session, payload: TransactionIn) -> tuple[dict[str, Any], bool]:
        """Анализирует транзакцию. Возвращает (результат, создана_ли_новая_запись).

        Повторная отправка той же транзакции (тот же transaction_id) возвращает ранее рассчитанный результат.
        """
        started = time.perf_counter()
        bundle = self.model_store.get()
        try:
            tx = normalize(payload.model_dump(), self.settings.currency_rates)
        except Exception:
            metrics.TX_ERRORS.labels(stage="preprocessing").inc()
            raise

        existing = self._find(db, tx.transaction_id)
        if existing:
            metrics.TX_DUPLICATES.inc()
            return serialize(*existing), False

        with client_lock(tx.client_id):
            existing = self._find(db, tx.transaction_id)
            if existing:
                metrics.TX_DUPLICATES.inc()
                return serialize(*existing), False
            try:
                result = self._analyze_locked(db, bundle, tx, payload, started)
            except IntegrityError:
                # Гонка между процессами (API и воркер): транзакция уже записана другим обработчиком.
                db.rollback()
                existing = self._find(db, tx.transaction_id)
                if existing:
                    metrics.TX_DUPLICATES.inc()
                    return serialize(*existing), False
                raise
            except Exception:
                db.rollback()
                metrics.TX_ERRORS.labels(stage="analysis").inc()
                raise

        self.event_bus.publish({"type": "transaction_analyzed", "data": result})
        return result, True

    @staticmethod
    def _find(db: Session, transaction_id: str) -> tuple[Transaction, Analysis] | None:
        tx_row = db.scalar(select(Transaction).where(Transaction.transaction_id == transaction_id))
        if tx_row is None:
            return None
        return tx_row, tx_row.analysis

    def _get_or_create_client(self, db: Session, client_id: str, ts: datetime) -> Client:
        client = db.scalar(select(Client).where(Client.id == client_id).with_for_update())
        if client is not None:
            return client
        client = Client(id=client_id, profile=new_profile(), first_seen=ts, last_seen=ts)
        db.add(client)
        try:
            db.flush()
        except IntegrityError:
            db.rollback()
            client = db.scalar(select(Client).where(Client.id == client_id).with_for_update())
            if client is None:
                raise
        return client

    def _analyze_locked(
        self, db: Session, bundle: ModelBundle, tx: Tx, payload: TransactionIn, started: float
    ) -> dict[str, Any]:
        settings = self.settings
        client = self._get_or_create_client(db, tx.client_id, tx.ts)
        profile = copy.deepcopy(client.profile)

        features, ctx = compute_features(profile, tx, settings.min_history_for_profile)
        x = to_vector(features, bundle.feature_names)
        score = float(bundle.score(x)[0])
        risk = bundle.risk_level(score, {"medium": settings.risk_medium, "high": settings.risk_high})

        reasons = build_reasons(features, ctx)
        if risk == "low":
            reasons = [r for r in reasons if r["severity"] >= 0.6]
        factors = shap_factors(bundle, features) if settings.explain_shap and risk != "low" else []
        deviation_types, summary = summarize(reasons, risk)

        # Операции высокого риска не искажают типичное поведение до решения специалиста.
        hold = risk == "high"
        update_activity(profile, tx.epoch)
        if not hold:
            update_behavior(profile, tx)
        client.profile = profile
        if client.last_seen is None or tx.ts > client.last_seen:
            client.last_seen = tx.ts

        tx_row = Transaction(
            transaction_id=tx.transaction_id,
            client_id=tx.client_id,
            timestamp=tx.ts,
            amount=tx.amount,
            currency=tx.currency,
            amount_base=tx.amount_base,
            category=tx.category,
            recipient_id=tx.recipient_id,
            recipient_category=tx.recipient_category,
            channel=tx.channel,
            extra=tx.extra or None,
            simulation_label=payload.simulation_label,
            simulation_anomaly_type=payload.simulation_anomaly_type,
        )
        latency_ms = (time.perf_counter() - started) * 1000.0
        status = STATUS_NORMAL if risk == "low" else STATUS_REVIEW
        analysis = Analysis(
            transaction=tx_row,
            anomaly_score=score,
            risk_level=risk,
            status=status,
            features=features,
            reasons=reasons,
            factors=factors,
            deviation_types=deviation_types,
            summary=summary,
            model_version=bundle.version,
            model_kind=bundle.kind,
            latency_ms=latency_ms,
            profile_updated=not hold,
        )
        db.add_all([tx_row, analysis])
        db.flush()
        if risk != "low":
            db.add(
                AlertHistory(
                    analysis_id=analysis.id,
                    client_id=tx.client_id,
                    transaction_id=tx.transaction_id,
                    event_type="triggered",
                    risk_level=risk,
                    anomaly_score=score,
                    status=status,
                )
            )
        db.commit()

        metrics.TX_PROCESSED.labels(risk_level=risk).inc()
        metrics.TX_LATENCY.observe(latency_ms / 1000.0)
        log.info(
            "Транзакция обработана",
            extra={
                "transaction_id": tx.transaction_id,
                "client_id": tx.client_id,
                "risk_level": risk,
                "anomaly_score": round(score, 4),
                "latency_ms": round(latency_ms, 2),
            },
        )
        return serialize(tx_row, analysis)

    # ------------------------------------------------------------------ решение специалиста
    def review(
        self, db: Session, transaction_id: str, status: str, reviewer: str, comment: str | None
    ) -> dict[str, Any]:
        found = self._find(db, transaction_id)
        if found is None:
            raise TransactionNotFoundError(transaction_id)
        tx_row, analysis = found

        with client_lock(tx_row.client_id):
            client = db.scalar(select(Client).where(Client.id == tx_row.client_id).with_for_update())
            if status == "reviewed_normal" and not analysis.profile_updated and client is not None:
                # Специалист подтвердил, что операция нормальна: она становится частью типичного поведения.
                profile = copy.deepcopy(client.profile)
                update_behavior(profile, _tx_from_row(tx_row, self.settings.currency_rates))
                client.profile = profile
                analysis.profile_updated = True
            analysis.status = status
            analysis.reviewed_by = reviewer
            analysis.reviewed_at = datetime.now(timezone.utc)
            analysis.review_comment = comment
            db.add(
                AlertHistory(
                    analysis_id=analysis.id,
                    client_id=tx_row.client_id,
                    transaction_id=tx_row.transaction_id,
                    event_type="status_changed",
                    risk_level=analysis.risk_level,
                    anomaly_score=analysis.anomaly_score,
                    status=status,
                    actor=reviewer,
                    comment=comment,
                )
            )
            db.commit()

        result = serialize(tx_row, analysis)
        self.event_bus.publish({"type": "transaction_reviewed", "data": result})
        return result
