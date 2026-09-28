"""Обучение рабочей модели и сохранение артефакта.

Запуск: python -m app.ml.train --kind isolation_forest --out models/model.joblib
"""
import argparse
import itertools
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from sklearn.ensemble import IsolationForest

from app.domain.features import FEATURE_NAMES
from app.ml.dataset import build_feature_frame, time_split
from app.ml.metrics import best_f1_threshold, evaluate
from app.ml.model import ModelBundle, save_bundle, sigmoid_calibration
from app.simulation.generator import generate_transactions

log = logging.getLogger("train")

IF_GRID = {
    "n_estimators": [100, 200, 400],
    "max_samples": [256, 512, 1024],
    "max_features": [0.6, 1.0],
}
OPERATIONAL_QUANTILE = 0.98


def fit_isolation_forest(X: np.ndarray, seed: int, **params) -> IsolationForest:
    return IsolationForest(random_state=seed, n_jobs=-1, **params).fit(X)


def tune_isolation_forest(train, val, seed: int) -> tuple[dict, list[dict]]:
    """Перебор параметров по PR-AUC на валидационной выборке (обучение на train без меток)."""
    Xtr, Xva, yva = train[FEATURE_NAMES].values, val[FEATURE_NAMES].values, val["is_anomaly"].values
    results = []
    keys = list(IF_GRID)
    for combo in itertools.product(*(IF_GRID[k] for k in keys)):
        params = dict(zip(keys, combo))
        model = fit_isolation_forest(Xtr, seed, **params)
        scores = -model.score_samples(Xva)
        m = evaluate(yva, scores, np.quantile(-model.score_samples(Xtr), OPERATIONAL_QUANTILE))
        results.append({"params": params, **m})
        log.info("IF %s -> PR-AUC %.3f ROC-AUC %.3f", params, m["pr_auc"], m["roc_auc"])
    best = max(results, key=lambda r: r["pr_auc"])
    return best["params"], results


def train_isolation_forest(train, val, test, seed: int, tune: bool) -> ModelBundle:
    params = {"n_estimators": 200, "max_samples": 512, "max_features": 0.6}
    search = []
    if tune:
        params, search = tune_isolation_forest(train, val, seed)
    import pandas as pd

    fit_frame = pd.concat([train, val], ignore_index=True)
    model = fit_isolation_forest(fit_frame[FEATURE_NAMES].values, seed, **params)
    raw_fit = -model.score_samples(fit_frame[FEATURE_NAMES].values)
    calibration = sigmoid_calibration(raw_fit)
    bundle = ModelBundle(
        kind="isolation_forest",
        model=model,
        feature_names=list(FEATURE_NAMES),
        calibration=calibration,
    )
    scores = bundle.score(test[FEATURE_NAMES].values)
    metrics = evaluate(test["is_anomaly"].values, scores, bundle.thresholds["medium"])
    bundle.params = params
    bundle.metrics = {"test": metrics, "search": search, "train_rows": len(fit_frame), "test_rows": len(test)}
    return bundle


def train_lightgbm(train, val, test, seed: int) -> ModelBundle:
    import lightgbm as lgb

    pos = max(int(train["is_anomaly"].sum()), 1)
    params = {
        "n_estimators": 400,
        "learning_rate": 0.05,
        "num_leaves": 31,
        "scale_pos_weight": (len(train) - pos) / pos,
        "subsample": 0.8,
        "subsample_freq": 1,
        "colsample_bytree": 0.8,
        "random_state": seed,
        "verbose": -1,
    }
    model = lgb.LGBMClassifier(**params)
    model.fit(
        train[FEATURE_NAMES].values,
        train["is_anomaly"].values.astype(int),
        eval_set=[(val[FEATURE_NAMES].values, val["is_anomaly"].values.astype(int))],
        callbacks=[lgb.early_stopping(30, verbose=False)],
    )
    bundle = ModelBundle(
        kind="lightgbm",
        model=model,
        feature_names=list(FEATURE_NAMES),
        calibration={"type": "probability"},
    )
    val_scores = bundle.score(val[FEATURE_NAMES].values)
    medium = best_f1_threshold(val["is_anomaly"].values, val_scores)
    high = max(medium, min(0.95, (1.0 + medium) / 2))
    bundle.thresholds = {"medium": float(medium), "high": float(high)}
    metrics = evaluate(test["is_anomaly"].values, bundle.score(test[FEATURE_NAMES].values), medium)
    bundle.params = {k: v for k, v in params.items() if k != "verbose"}
    bundle.metrics = {"test": metrics, "train_rows": len(train), "test_rows": len(test)}
    return bundle


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kind", choices=["isolation_forest", "lightgbm"], default="isolation_forest")
    parser.add_argument("--out", default="models/model.joblib")
    parser.add_argument("--clients", type=int, default=300)
    parser.add_argument("--days", type=int, default=60)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--no-tune", action="store_true", help="пропустить подбор параметров")
    parser.add_argument("--dataset", choices=["synthetic", "ibm"], default="synthetic")
    parser.add_argument("--ibm-path", help="CSV-файл IBM Credit Card Transactions")
    parser.add_argument("--ibm-user-fraction", type=float, default=0.05)
    parser.add_argument("--ibm-from-year", type=int, default=2010)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")

    if args.dataset == "ibm":
        if not args.ibm_path:
            parser.error("для --dataset ibm нужен --ibm-path")
        from app.ml.ibm_loader import load_ibm

        log.info("Загрузка IBM: %s (доля пользователей %s, с %s года)", args.ibm_path, args.ibm_user_fraction, args.ibm_from_year)
        df = load_ibm(args.ibm_path, args.ibm_user_fraction, args.ibm_from_year, args.seed)
    else:
        log.info("Генерация данных: clients=%s days=%s seed=%s", args.clients, args.days, args.seed)
        df = generate_transactions(args.clients, args.days, args.seed)
    log.info("Транзакций: %s, доля аномалий: %.3f", len(df), df["is_anomaly"].mean())
    frame = build_feature_frame(df)
    train, val, test = time_split(frame)

    if args.kind == "isolation_forest":
        bundle = train_isolation_forest(train, val, test, args.seed, tune=not args.no_tune)
    else:
        bundle = train_lightgbm(train, val, test, args.seed)

    now = datetime.now(timezone.utc)
    bundle.trained_at = now.isoformat(timespec="seconds")
    bundle.version = f"{args.kind}-{now:%Y%m%d%H%M%S}"
    save_bundle(bundle, args.out)
    meta_path = Path(args.out).with_suffix(".json")
    meta_path.write_text(json.dumps(bundle.info(), ensure_ascii=False, indent=2, default=float), encoding="utf-8")
    log.info("Модель сохранена: %s; метрики на тесте: %s", args.out, bundle.metrics["test"])


if __name__ == "__main__":
    main()
