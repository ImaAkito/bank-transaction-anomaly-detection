"""Градиентный бустинг с подбором по скользящим хронологическим окнам и гибрид с Isolation Forest.

Одна маленькая валидационная выборка при сверхредком классе и дрейфе даёт нестабильный выбор числа деревьев
и порога. Здесь параметры выбираются по нескольким последовательным окнам (обучение на прошлом, проверка на
следующем окне), а пороги риска задаются бюджетом оповещений, а не максимумом F1 на валидации.
"""
import logging
from typing import Any

import numpy as np
from sklearn.metrics import average_precision_score

log = logging.getLogger(__name__)

TREE_GRID = (50, 100, 200, 400)
DEPTH_GRID = (3, 5)
MIN_POSITIVES_PER_FOLD = 3


def time_folds(timestamps, n_chunks: int = 5, min_train_chunks: int = 2) -> list[tuple[np.ndarray, np.ndarray]]:
    """Расширяющееся окно: обучение на всех чанках до i, проверка на чанке i (по числу операций)."""
    order = np.argsort(np.asarray(timestamps), kind="stable")
    chunks = np.array_split(order, n_chunks)
    folds = []
    for i in range(min_train_chunks, n_chunks):
        folds.append((np.concatenate(chunks[:i]), chunks[i]))
    return folds


def _lgbm(seed: int, depth: int, n_estimators: int, pos_weight: float):
    import lightgbm as lgb

    return lgb.LGBMClassifier(
        n_estimators=n_estimators,
        learning_rate=0.05,
        max_depth=depth,
        num_leaves=2**depth,
        min_child_samples=100,
        reg_lambda=5.0,
        subsample=0.8,
        subsample_freq=1,
        colsample_bytree=0.8,
        scale_pos_weight=pos_weight,
        random_state=seed,
        verbose=-1,
        n_jobs=-1,
    )


def positive_weight(y: np.ndarray) -> float:
    """Вес положительного класса: корень из отношения классов (полный вес усиливает шум при сверхредком классе)."""
    pos = max(int(np.sum(y)), 1)
    return float(max(((len(y) - pos) / pos) ** 0.5, 1.0))


def select_and_fit_lgbm(X: np.ndarray, y: np.ndarray, timestamps, seed: int) -> tuple[Any, dict[str, Any]]:
    """Подбор глубины и числа деревьев по среднему PR-AUC на хронологических окнах, затем обучение на всех данных."""
    y = np.asarray(y).astype(int)
    folds = [
        (tr, va) for tr, va in time_folds(timestamps)
        if y[va].sum() >= MIN_POSITIVES_PER_FOLD and y[tr].sum() >= MIN_POSITIVES_PER_FOLD
    ]
    report: dict[str, Any] = {"folds": len(folds), "grid": []}
    best = (-1.0, DEPTH_GRID[0], TREE_GRID[1])
    if folds:
        for depth in DEPTH_GRID:
            scores = {n: [] for n in TREE_GRID}
            for tr, va in folds:
                model = _lgbm(seed, depth, max(TREE_GRID), positive_weight(y[tr])).fit(X[tr], y[tr])
                for n in TREE_GRID:
                    proba = model.predict_proba(X[va], num_iteration=n)[:, 1]
                    scores[n].append(average_precision_score(y[va], proba))
            for n, values in scores.items():
                mean = float(np.mean(values))
                report["grid"].append({"depth": depth, "n_estimators": n, "pr_auc_mean": mean, "pr_auc_folds": values})
                if mean > best[0]:
                    best = (mean, depth, n)
    else:
        log.warning("Недостаточно положительных примеров для хронологической проверки, берутся параметры по умолчанию")
    _, depth, n_estimators = best
    report.update({"depth": depth, "n_estimators": n_estimators, "cv_pr_auc": best[0] if folds else None})
    model = _lgbm(seed, depth, n_estimators, positive_weight(y)).fit(X, y)
    return model, report


def hybrid_matrix(X: np.ndarray, forest_scores: np.ndarray) -> np.ndarray:
    """Признаки бустинга: исходные признаки и оценка Isolation Forest (необычность по всем признакам сразу)."""
    return np.hstack([X, np.asarray(forest_scores).reshape(-1, 1)])
