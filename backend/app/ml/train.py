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

from app.domain.features import DEFAULT_FEATURE_NAMES, select_features
from app.ml.dataset import build_feature_frame, fit_population_on_train, time_split
from app.ml.gbm import hybrid_matrix, select_and_fit_lgbm
from app.ml.metrics import budget_metrics, evaluate
from app.ml.model import ModelBundle, save_bundle, sigmoid_calibration
from app.simulation.generator import generate_transactions

log = logging.getLogger("train")

IF_GRID = {
    "n_estimators": [100, 200, 400],
    "max_samples": [256, 512, 1024],
    "max_features": [0.6, 1.0],
}
OPERATIONAL_QUANTILE = 0.98
FEATURES: list[str] = list(DEFAULT_FEATURE_NAMES)  # активный набор признаков; main() может сузить его по группам


def fit_isolation_forest(X: np.ndarray, seed: int, **params) -> IsolationForest:
    return IsolationForest(random_state=seed, n_jobs=-1, **params).fit(X)


def tune_isolation_forest(train, val, seed: int) -> tuple[dict, list[dict]]:
    """Перебор параметров по PR-AUC на валидационной выборке (обучение на train без меток)."""
    Xtr, Xva, yva = train[FEATURES].values, val[FEATURES].values, val["is_anomaly"].values
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
    model = fit_isolation_forest(fit_frame[FEATURES].values, seed, **params)
    raw_fit = -model.score_samples(fit_frame[FEATURES].values)
    calibration = sigmoid_calibration(raw_fit)
    bundle = ModelBundle(
        kind="isolation_forest",
        model=model,
        feature_names=list(FEATURES),
        calibration=calibration,
    )
    scores = bundle.score(test[FEATURES].values)
    metrics = evaluate(test["is_anomaly"].values, scores, bundle.thresholds["medium"])
    bundle.params = params
    bundle.metrics = {"test": metrics, "search": search, "train_rows": len(fit_frame), "test_rows": len(test)}
    return bundle


ALERT_BUDGET_MEDIUM = 0.01   # доля операций со средним и высоким риском
ALERT_BUDGET_HIGH = 0.002    # доля операций с высоким риском


def _budget_thresholds(val_scores: np.ndarray) -> dict[str, float]:
    """Пороги риска по бюджету оповещений: квантили оценок на валидации, метки не используются."""
    medium = float(np.quantile(val_scores, 1.0 - ALERT_BUDGET_MEDIUM))
    high = float(np.quantile(val_scores, 1.0 - ALERT_BUDGET_HIGH))
    return {"medium": medium, "high": max(high, medium)}


def _finish_supervised(bundle: ModelBundle, X_val: np.ndarray, test, train_rows: int, report: dict) -> ModelBundle:
    bundle.thresholds = _budget_thresholds(bundle.score(X_val))
    test_scores = bundle.score(test[FEATURES].values)
    bundle.metrics = {
        "test": evaluate(test["is_anomaly"].values, test_scores, bundle.thresholds["medium"]),
        "budget": budget_metrics(test["is_anomaly"].values, test_scores),
        "selection": report,
        "train_rows": train_rows,
        "test_rows": len(test),
    }
    return bundle


def train_lightgbm(train, val, test, seed: int) -> ModelBundle:
    """LightGBM: глубина и число деревьев по хронологическим окнам, пороги по бюджету оповещений."""
    model, report = select_and_fit_lgbm(
        train[FEATURES].values, train["is_anomaly"].values.astype(int), train["timestamp"].values, seed
    )
    bundle = ModelBundle(kind="lightgbm", model=model, feature_names=list(FEATURES), calibration={"type": "probability"})
    bundle.params = {"max_depth": report["depth"], "n_estimators": report["n_estimators"]}
    return _finish_supervised(bundle, val[FEATURES].values, test, len(train), report)


def train_hybrid(train, val, test, seed: int, tune: bool) -> ModelBundle:
    """Гибрид: оценка Isolation Forest (обучен без меток) подаётся в LightGBM как дополнительный признак."""
    params = {"n_estimators": 200, "max_samples": 512, "max_features": 0.6}
    if tune:
        params, _ = tune_isolation_forest(train, val, seed)
    forest = fit_isolation_forest(train[FEATURES].values, seed, **params)
    X_train = hybrid_matrix(train[FEATURES].values, -forest.score_samples(train[FEATURES].values))
    gbm, report = select_and_fit_lgbm(X_train, train["is_anomaly"].values.astype(int), train["timestamp"].values, seed)
    bundle = ModelBundle(
        kind="hybrid", model={"forest": forest, "gbm": gbm}, feature_names=list(FEATURES),
        calibration={"type": "probability"},
    )
    bundle.params = {"forest": params, "max_depth": report["depth"], "n_estimators": report["n_estimators"]}
    return _finish_supervised(bundle, val[FEATURES].values, test, len(train), report)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kind", choices=["isolation_forest", "lightgbm", "hybrid"], default="isolation_forest")
    parser.add_argument("--out", default="models/model.joblib")
    parser.add_argument("--clients", type=int, default=300)
    parser.add_argument("--days", type=int, default=60)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--no-tune", action="store_true", help="пропустить подбор параметров")
    parser.add_argument("--feature-groups", help="группы признаков через запятую: amount,time,velocity,novelty,history,population (по умолчанию все, кроме population)")
    parser.add_argument("--dataset", choices=["synthetic", "ibm"], default="synthetic")
    parser.add_argument("--ibm-path", help="CSV-файл IBM Credit Card Transactions")
    parser.add_argument("--ibm-user-fraction", type=float, default=0.05)
    parser.add_argument("--ibm-from-year", type=int, default=2010)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    FEATURES[:] = select_features(args.feature_groups)
    log.info("Признаков: %s (%s)", len(FEATURES), args.feature_groups or "все группы")

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
    population = fit_population_on_train(df)
    frame = build_feature_frame(df, population=population)
    train, val, test = time_split(frame)

    if args.kind == "isolation_forest":
        bundle = train_isolation_forest(train, val, test, args.seed, tune=not args.no_tune)
    elif args.kind == "hybrid":
        bundle = train_hybrid(train, val, test, args.seed, tune=not args.no_tune)
    else:
        bundle = train_lightgbm(train, val, test, args.seed)

    bundle.population = population
    now = datetime.now(timezone.utc)
    bundle.trained_at = now.isoformat(timespec="seconds")
    bundle.version = f"{args.kind}-{now:%Y%m%d%H%M%S}"
    save_bundle(bundle, args.out)
    meta_path = Path(args.out).with_suffix(".json")
    meta_path.write_text(json.dumps(bundle.info(), ensure_ascii=False, indent=2, default=float), encoding="utf-8")
    log.info("Модель сохранена: %s; метрики на тесте: %s", args.out, bundle.metrics["test"])


if __name__ == "__main__":
    main()
