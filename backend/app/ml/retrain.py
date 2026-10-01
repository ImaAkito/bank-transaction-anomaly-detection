"""Автоматическое переобучение рабочей модели по накопленным в БД транзакциям.

Запуск разово: python -m app.ml.retrain
Периодически: python -m app.ml.retrain --loop (переобучение по расписанию или при дрейфе)

Порядок:
1. последние N транзакций из БД приводятся к формату обучения, профили клиентов строятся заново
   последовательным проходом (как в эксплуатации);
2. Isolation Forest обучается с параметрами текущей модели (метки не нужны);
3. проверка качества: если специалисты разметили операции (reviewed_suspicious / reviewed_normal),
   новая модель не должна быть хуже текущей по PR-AUC на размеченных операциях; без разметки проверяется,
   что доля оповещений не изменилась более чем вдвое;
4. текущий артефакт сохраняется в архив, новый записывается атомарно; API и воркеры перечитывают его сами.
"""
import argparse
import logging
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.metrics import average_precision_score
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import init_db, session_factory
from app.domain.features import FEATURE_GROUPS
from app.ml.dataset import build_feature_frame, fit_population_on_train
from app.ml.drift import build_reference, compute_drift
from app.ml.model import ModelBundle, load_bundle, save_bundle, sigmoid_calibration
from app.models import Analysis, ModelEvent, Transaction

log = logging.getLogger("retrain")

LABELED_STATUSES = {"reviewed_suspicious": True, "reviewed_normal": False}
MIN_LABELED_POSITIVES = 10


def load_history(db: Session, limit: int) -> pd.DataFrame:
    rows = db.execute(
        select(Transaction, Analysis.status)
        .join(Analysis, Analysis.transaction_pk == Transaction.id)
        .order_by(desc(Transaction.timestamp))
        .limit(limit)
    ).all()
    records = [
        {
            "transaction_id": t.transaction_id,
            "client_id": t.client_id,
            "timestamp": t.timestamp,
            "amount": t.amount,
            "currency": t.currency,
            "category": t.category,
            "recipient_id": t.recipient_id,
            "recipient_category": t.recipient_category,
            "channel": t.channel,
            "timezone": t.timezone,
            "is_anomaly": LABELED_STATUSES.get(status, False),
            "labeled": status in LABELED_STATUSES,
            "anomaly_type": "reviewed" if status == "reviewed_suspicious" else "",
        }
        for t, status in rows
    ]
    return pd.DataFrame.from_records(records).sort_values("timestamp", kind="stable").reset_index(drop=True)


def recent_drift(db: Session, bundle: ModelBundle, settings: Settings) -> dict[str, Any]:
    if not bundle.reference:
        return {"available": False, "reason": "В артефакте модели нет опорных распределений; переобучите модель"}
    rows = db.execute(
        select(Analysis.features, Analysis.anomaly_score).order_by(desc(Analysis.id)).limit(settings.drift_window)
    ).all()
    return compute_drift(
        bundle.reference,
        [r[0] for r in rows],
        [r[1] for r in rows],
        settings.risk_medium or bundle.thresholds["medium"],
        settings.drift_psi_warning,
        settings.drift_psi_alert,
    )


def _log_event(db: Session, event_type: str, version: str | None, details: dict[str, Any]) -> None:
    db.add(ModelEvent(event_type=event_type, model_version=version, details=details))
    db.commit()


def retrain(settings: Settings, db: Session, reason: str = "manual") -> dict[str, Any]:
    current = load_bundle(settings.model_path)
    if current.kind != "isolation_forest":
        result = {"status": "skipped", "reason": f"Автоматическое переобучение поддерживается для isolation_forest, текущая модель: {current.kind}"}
        _log_event(db, "retrain_skipped", current.version, result)
        return result
    df = load_history(db, settings.retrain_max_transactions)
    if len(df) < settings.retrain_min_transactions:
        result = {"status": "skipped", "reason": f"Недостаточно транзакций: {len(df)} < {settings.retrain_min_transactions}"}
        _log_event(db, "retrain_skipped", current.version, result)
        return result

    features = list(current.feature_names)
    uses_population = any(name in FEATURE_GROUPS["population"] for name in features)
    population = fit_population_on_train(df, train_frac=1.0) if uses_population else {}
    frame = build_feature_frame(df, population=population or None, hold_policy="rule")
    frame["labeled"] = df.set_index("transaction_id").loc[frame["transaction_id"], "labeled"].values
    X = frame[features].values

    params = {k: current.params[k] for k in ("n_estimators", "max_samples", "max_features") if k in current.params}
    model = IsolationForest(random_state=0, n_jobs=-1, **params).fit(X)
    raw = -model.score_samples(X)
    now = datetime.now(timezone.utc)
    candidate = ModelBundle(
        kind="isolation_forest",
        model=model,
        feature_names=features,
        calibration=sigmoid_calibration(raw),
        thresholds=dict(current.thresholds),
        version=f"isolation_forest-{now:%Y%m%d%H%M%S}-auto",
        trained_at=now.isoformat(timespec="seconds"),
        params=params,
        population=population,
    )
    new_scores = candidate.score(X)
    candidate.reference = build_reference({n: frame[n].values for n in features}, new_scores, candidate.thresholds["medium"])

    checks: dict[str, Any] = {"rows": len(frame), "reason": reason}
    labeled = frame[frame["labeled"]]
    positives = int(labeled["is_anomaly"].sum())
    if positives >= MIN_LABELED_POSITIVES and positives < len(labeled):
        old_pr = float(average_precision_score(labeled["is_anomaly"], current.score(labeled[features].values)))
        new_pr = float(average_precision_score(labeled["is_anomaly"], candidate.score(labeled[features].values)))
        checks.update({"labeled": len(labeled), "pr_auc_current": old_pr, "pr_auc_candidate": new_pr})
        accepted = new_pr >= old_pr - 0.02
    else:
        flagged_old = float(np.mean(current.score(X) >= current.thresholds["medium"]))
        flagged_new = float(np.mean(new_scores >= candidate.thresholds["medium"]))
        checks.update({"flagged_share_current": flagged_old, "flagged_share_candidate": flagged_new})
        accepted = flagged_new > 0 and (flagged_old == 0 or 0.5 <= flagged_new / flagged_old <= 2.0)

    if not accepted:
        result = {"status": "rejected", "checks": checks}
        _log_event(db, "retrain_rejected", candidate.version, result)
        return result

    model_path = Path(settings.model_path)
    archive = model_path.parent / "archive"
    archive.mkdir(parents=True, exist_ok=True)
    shutil.copy2(model_path, archive / f"{current.version}.joblib")
    candidate.metrics = {"retrain": checks}
    save_bundle(candidate, model_path)
    result = {"status": "deployed", "version": candidate.version, "previous": current.version, "checks": checks}
    _log_event(db, "retrained", candidate.version, result)
    log.info("Модель переобучена: %s", result)
    return result


def should_retrain(db: Session, settings: Settings) -> str | None:
    """Причина для переобучения или None: прошёл интервал с последнего переобучения либо дрейф достиг порога."""
    last = db.scalar(select(ModelEvent).where(ModelEvent.event_type == "retrained").order_by(desc(ModelEvent.id)).limit(1))
    bundle = load_bundle(settings.model_path)
    reference_time = last.created_at if last else datetime.fromisoformat(bundle.trained_at) if bundle.trained_at else None
    if reference_time is not None:
        hours = (datetime.now(timezone.utc) - reference_time).total_seconds() / 3600
        if hours >= settings.retrain_interval_hours:
            return f"interval:{hours:.1f}h"
    drift = recent_drift(db, bundle, settings)
    if drift.get("available") and drift["status"] == "alert":
        return f"drift:max_psi={drift['max_psi']:.3f}"
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--loop", action="store_true", help="проверять необходимость переобучения периодически")
    parser.add_argument("--check-minutes", type=float, default=60.0)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    settings = get_settings()
    init_db()
    while True:
        db = session_factory()()
        try:
            reason = should_retrain(db, settings) if args.loop else "manual"
            if reason:
                log.info("Переобучение, причина: %s", reason)
                log.info("%s", retrain(settings, db, reason))
        except Exception:
            log.exception("Ошибка переобучения")
        finally:
            db.close()
        if not args.loop:
            break
        time.sleep(args.check_minutes * 60)


if __name__ == "__main__":
    main()
