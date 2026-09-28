"""Метрики качества обнаружения аномалий."""
import numpy as np
from sklearn.metrics import average_precision_score, f1_score, precision_score, recall_score, roc_auc_score


def evaluate(y_true: np.ndarray, scores: np.ndarray, threshold: float) -> dict[str, float]:
    y_true = np.asarray(y_true).astype(int)
    pred = (np.asarray(scores) >= threshold).astype(int)
    return {
        "precision": float(precision_score(y_true, pred, zero_division=0)),
        "recall": float(recall_score(y_true, pred, zero_division=0)),
        "f1": float(f1_score(y_true, pred, zero_division=0)),
        "roc_auc": float(roc_auc_score(y_true, scores)),
        "pr_auc": float(average_precision_score(y_true, scores)),
        "flagged_share": float(pred.mean()),
    }


def best_f1_threshold(y_true: np.ndarray, scores: np.ndarray) -> float:
    """Порог, максимизирующий F1 (подбирается только на валидационной выборке)."""
    order = np.argsort(-scores)
    y = np.asarray(y_true).astype(int)[order]
    s = np.asarray(scores)[order]
    tp = np.cumsum(y)
    fp = np.cumsum(1 - y)
    total_pos = y.sum()
    if total_pos == 0:
        return float(s[0])
    precision = tp / (tp + fp)
    recall = tp / total_pos
    denominator = precision + recall
    f1 = np.divide(2 * precision * recall, denominator, out=np.zeros_like(denominator), where=denominator > 0)
    return float(s[int(np.argmax(f1))])
