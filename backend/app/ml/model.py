"""Артефакт модели: обученная модель, калибровка оценки в диапазон [0, 1], пороги риска."""
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import joblib
import numpy as np

RISK_LEVELS = ("low", "medium", "high")
DEFAULT_THRESHOLDS = {"medium": 0.6, "high": 0.85}


@dataclass
class ModelBundle:
    kind: str  # isolation_forest | lightgbm
    model: Any
    feature_names: list[str]
    calibration: dict[str, Any]
    thresholds: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_THRESHOLDS))
    version: str = "0"
    trained_at: str = ""
    params: dict[str, Any] = field(default_factory=dict)
    metrics: dict[str, Any] = field(default_factory=dict)
    population: dict[str, Any] = field(default_factory=dict)
    _explainer: Any = field(default=None, repr=False, compare=False)

    def raw_score(self, X: np.ndarray) -> np.ndarray:
        """Необработанная оценка, большее значение означает более аномальную операцию."""
        if self.kind == "isolation_forest":
            return -self.model.score_samples(X)
        if self.kind == "lightgbm":
            return self.model.predict_proba(X)[:, 1]
        raise ValueError(f"Неизвестный тип модели: {self.kind}")

    def score(self, X: np.ndarray) -> np.ndarray:
        """Степень аномальности в диапазоне [0, 1]."""
        raw = self.raw_score(X)
        if self.calibration["type"] == "sigmoid":
            z = np.clip((raw - self.calibration["center"]) / self.calibration["scale"], -50, 50)
            return 1.0 / (1.0 + np.exp(-z))
        return np.clip(raw, 0.0, 1.0)

    def risk_level(self, score: float, overrides: dict[str, float | None] | None = None) -> str:
        medium = (overrides or {}).get("medium") or self.thresholds["medium"]
        high = (overrides or {}).get("high") or self.thresholds["high"]
        if score >= high:
            return "high"
        if score >= medium:
            return "medium"
        return "low"

    def explainer(self):
        """Ленивое создание SHAP TreeExplainer (тяжёлый импорт)."""
        if self._explainer is None:
            import shap

            self._explainer = shap.TreeExplainer(self.model)
        return self._explainer

    def shap_values(self, X: np.ndarray) -> np.ndarray:
        """SHAP-значения в терминах «вклад в аномальность»: положительное значение повышает оценку."""
        values = self.explainer().shap_values(X)
        if isinstance(values, list):  # старые версии shap возвращают список по классам
            values = values[-1]
        values = np.asarray(values)
        if values.ndim == 3:
            values = values[:, :, -1]
        return -values if self.kind == "isolation_forest" else values

    def info(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "version": self.version,
            "trained_at": self.trained_at,
            "feature_names": self.feature_names,
            "thresholds": self.thresholds,
            "calibration": self.calibration,
            "params": self.params,
            "metrics": self.metrics,
        }


def sigmoid_calibration(train_raw: np.ndarray, q_center: float = 0.98, q_high: float = 0.995) -> dict[str, Any]:
    """Калибровка: оценка 0,5 у квантиля q_center обучающих оценок, 0,9 у квантиля q_high."""
    center = float(np.quantile(train_raw, q_center))
    upper = float(np.quantile(train_raw, q_high))
    scale = (upper - center) / math.log(9.0)
    if scale <= 1e-9:
        scale = max(float(np.std(train_raw)) * 0.1, 1e-6)
    return {"type": "sigmoid", "center": center, "scale": scale, "q_center": q_center, "q_high": q_high}


def save_bundle(bundle: ModelBundle, path: str | Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    bundle._explainer = None
    joblib.dump(bundle, path)


def load_bundle(path: str | Path) -> ModelBundle:
    bundle = joblib.load(path)
    if not isinstance(bundle, ModelBundle):
        raise TypeError("Файл не содержит артефакт модели")
    return bundle
