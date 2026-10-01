"""Мониторинг дрейфа данных: PSI (population stability index) по признакам и сдвиг доли оповещений.

Сравниваются только операции клиентов со зрелой историей (не меньше min_history операций в профиле):
у новых клиентов признаки профиля закономерно отличаются (короткая история, априорные частоты), и без
фильтра запуск системы с новыми клиентами выглядел бы как дрейф.

Опорное распределение каждого признака (границы децилей и доли значений) сохраняется в артефакте модели
при обучении. Текущее распределение берётся по последним проанализированным операциям.
"""
from typing import Any

import numpy as np

EPS = 1e-4
MIN_HISTORY = 20
# Длина истории растёт естественно по мере работы системы, её сдвиг не говорит об изменении поведения.
EXCLUDED = {"log_history_len"}


def _mature_threshold(min_history: int) -> float:
    return float(np.log1p(min_history))


def build_reference(values: dict[str, np.ndarray], scores: np.ndarray, medium_threshold: float,
                    min_history: int = MIN_HISTORY) -> dict[str, Any]:
    scores = np.asarray(scores)
    if "log_history_len" in values:
        mask = np.asarray(values["log_history_len"], dtype=float) >= _mature_threshold(min_history)
        if mask.sum() >= 100:  # на очень малых выборках фильтр не применяется
            values = {name: np.asarray(column)[mask] for name, column in values.items()}
            scores = scores[mask]
    features = {}
    for name, column in values.items():
        column = np.asarray(column, dtype=float)
        edges = np.unique(np.quantile(column, np.linspace(0.1, 0.9, 9)))
        features[name] = {"edges": edges.tolist(), "proportions": _proportions(column, edges).tolist()}
    return {
        "features": features,
        "flagged_share": float(np.mean(np.asarray(scores) >= medium_threshold)),
        "rows": int(len(scores)),
        "min_history": min_history,
    }


def _proportions(values: np.ndarray, edges: np.ndarray) -> np.ndarray:
    bins = np.searchsorted(edges, values, side="right")
    counts = np.bincount(bins, minlength=len(edges) + 1).astype(float)
    return counts / max(counts.sum(), 1.0)


def psi(expected: np.ndarray, actual: np.ndarray) -> float:
    expected = np.clip(np.asarray(expected, dtype=float), EPS, None)
    actual = np.clip(np.asarray(actual, dtype=float), EPS, None)
    return float(np.sum((actual - expected) * np.log(actual / expected)))


def level(value: float, warning: float, alert: float) -> str:
    if value >= alert:
        return "alert"
    if value >= warning:
        return "warning"
    return "ok"


def compute_drift(
    reference: dict[str, Any],
    rows: list[dict[str, float]],
    scores: list[float],
    medium_threshold: float,
    warning: float = 0.1,
    alert: float = 0.25,
) -> dict[str, Any]:
    min_history = reference.get("min_history", 0)
    if min_history:
        threshold = _mature_threshold(min_history)
        pairs = [(row, score) for row, score in zip(rows, scores) if row.get("log_history_len", np.inf) >= threshold]
        rows, scores = [p[0] for p in pairs], [p[1] for p in pairs]
    if not rows:
        return {"available": False,
                "reason": f"Нет операций клиентов с историей от {min_history} операций — сравнивать пока не с чем"}
    per_feature = []
    for name, ref in reference["features"].items():
        if name in EXCLUDED:
            continue
        values = np.array([row.get(name, np.nan) for row in rows], dtype=float)
        values = values[np.isfinite(values)]
        if len(values) == 0:
            continue
        value = psi(np.array(ref["proportions"]), _proportions(values, np.array(ref["edges"])))
        per_feature.append({"feature": name, "psi": value, "level": level(value, warning, alert)})
    per_feature.sort(key=lambda item: -item["psi"])
    flagged = float(np.mean(np.asarray(scores) >= medium_threshold)) if scores else 0.0
    expected = reference.get("flagged_share", 0.0)
    max_psi = per_feature[0]["psi"] if per_feature else 0.0
    status = level(max_psi, warning, alert)
    # Доля оповещений выросла или упала более чем вдвое относительно обучения — тоже признак дрейфа.
    if expected > 0 and (flagged > 2 * expected or flagged < expected / 2) and status == "ok":
        status = "warning"
    return {
        "available": True,
        "status": status,
        "window": len(rows),
        "min_history": min_history,
        "max_psi": max_psi,
        "flagged_share": flagged,
        "expected_flagged_share": expected,
        "features": per_feature,
        "thresholds": {"warning": warning, "alert": alert},
    }
