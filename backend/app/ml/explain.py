"""Модуль интерпретации: причины срабатывания в виде текста и вклад признаков (SHAP)."""
import logging
import math
from typing import Any

import numpy as np

from app.domain.features import FEATURE_LABELS_RU
from app.ml.model import ModelBundle

log = logging.getLogger(__name__)

MIN_HISTORY_FOR_TIME = 15
RARE_REGION_SURPRISAL = 4.0  # частота значения среди всех клиентов не выше ~1,8%

TYPE_LABELS_RU = {
    "amount": "сумма",
    "time": "время",
    "category": "категория",
    "channel": "канал",
    "recipient": "получатель",
    "currency": "валюта",
    "velocity": "частота операций",
}


def _num(value: float, digits: int = 1) -> str:
    """Число с десятичной запятой и пробелом как разделителем тысяч."""
    text = f"{value:,.{digits}f}".replace(",", " ").replace(".", ",")
    return text


def _severity_from_ratio(ratio: float, ceiling: float) -> float:
    return float(min(1.0, max(0.0, math.log(max(ratio, 1.0)) / math.log(ceiling))))


def build_reasons(features: dict[str, float], ctx: dict[str, Any]) -> list[dict[str, Any]]:
    """Правила интерпретации по значениям признаков. Возвращает причины, упорядоченные по значимости."""
    reasons: list[dict[str, Any]] = []
    warm = ctx["warm"]

    if not warm:
        reasons.append(
            {
                "code": "short_history",
                "type": "history",
                "severity": 0.0,
                "value": ctx["history_len"],
                "text": f"История клиента короткая ({ctx['history_len']} оп.), поведенческий профиль ещё не сформирован",
            }
        )
        return reasons

    ratio = ctx["amount_ratio"]
    if ratio >= 3.0 and ctx["median_amount"]:
        reasons.append(
            {
                "code": "amount_over_median",
                "type": "amount",
                "severity": _severity_from_ratio(ratio, 20.0),
                "value": ratio,
                "text": f"Сумма операции в {_num(ratio)} раза превышает медианную сумму операций клиента "
                f"({_num(ctx['median_amount'], 0)} в базовой валюте)",
            }
        )
    elif features["amount_zscore"] >= 3.0:
        reasons.append(
            {
                "code": "amount_high_zscore",
                "type": "amount",
                "severity": min(1.0, features["amount_zscore"] / 8.0),
                "value": features["amount_zscore"],
                "text": f"Сумма операции существенно выше обычной для клиента (z-оценка {_num(features['amount_zscore'])})",
            }
        )

    # Нетипичное время: по «сырой» доле операций клиента в этот час; на коротких историях вывод ненадёжен.
    if ctx["history_len"] >= MIN_HISTORY_FOR_TIME and ctx["hour_share"] < 0.03:
        share = ctx["hour_share"]
        reasons.append(
            {
                "code": "unusual_time",
                "type": "time",
                "severity": 0.9 if features["is_night"] else 0.7,
                "value": ctx["hour"],
                "text": f"Операция выполнена в нетипичное для клиента время ({ctx['hour']:02d}:00; "
                f"в этот час приходилось {_num(share * 100, 1)}% его операций)",
            }
        )

    if features["is_new_category"] > 0:
        reasons.append(
            {
                "code": "new_category",
                "type": "category",
                "severity": 0.8 * features["is_new_category"],
                "value": ctx["category"],
                "text": f"Данная категория операции («{ctx['category']}») ранее не использовалась клиентом",
            }
        )
    if features["is_new_channel"] > 0:
        reasons.append(
            {
                "code": "new_channel",
                "type": "channel",
                "severity": 0.6 * features["is_new_channel"],
                "value": ctx["channel"],
                "text": f"Канал проведения операции («{ctx['channel']}») ранее не использовался клиентом",
            }
        )
    if features["is_new_currency"] > 0:
        reasons.append(
            {
                "code": "new_currency",
                "type": "currency",
                "severity": 0.6 * features["is_new_currency"],
                "value": ctx["currency"],
                "text": f"Валюта операции ({ctx['currency']}) ранее не использовалась клиентом",
            }
        )
    if features.get("novel_rare_region", 0.0) >= RARE_REGION_SURPRISAL:
        reasons.append(
            {
                "code": "rare_recipient_region",
                "type": "recipient",
                "severity": min(1.0, features["novel_rare_region"] / 8.0),
                "value": features["novel_rare_region"],
                "text": "Регион получателя новый для клиента и редко встречается среди всех клиентов",
            }
        )
    if features.get("novel_rare_category", 0.0) >= RARE_REGION_SURPRISAL:
        reasons.append(
            {
                "code": "rare_category",
                "type": "category",
                "severity": min(1.0, features["novel_rare_category"] / 8.0),
                "value": features["novel_rare_category"],
                "text": f"Категория «{ctx['category']}» новая для клиента и редко встречается среди всех клиентов",
            }
        )
    if features["is_new_recipient"] > 0:
        reasons.append(
            {
                "code": "new_recipient",
                "type": "recipient",
                "severity": 0.3 * features["is_new_recipient"],
                "value": ctx["recipient_id"],
                "text": "Получатель платежа ранее не встречался в истории клиента",
            }
        )

    if ctx["count_1h"] >= 3 or features["rate_ratio"] >= 4.0:
        count = ctx["count_1h"]
        reasons.append(
            {
                "code": "high_frequency",
                "type": "velocity",
                "severity": min(1.0, 0.4 + 0.1 * count),
                "value": count,
                "text": f"За последний час клиент совершил {count} операций (за сутки {ctx['count_24h']}), "
                f"при обычной интенсивности около {_num(ctx['avg_daily'])} в сутки",
            }
        )

    reasons.sort(key=lambda r: -r["severity"])
    return reasons


def summarize(reasons: list[dict[str, Any]], risk_level: str) -> tuple[list[str], str]:
    """Характер отклонения: типы отклонений и краткая сводка."""
    significant = [r for r in reasons if r["severity"] > 0]
    types: list[str] = []
    for reason in significant:
        if reason["type"] not in types:
            types.append(reason["type"])
    if risk_level == "low":
        return types, "Существенных отклонений от типичного поведения клиента не выявлено"
    if types:
        names = ", ".join(TYPE_LABELS_RU[t] for t in types)
        return types, f"Операция отличается от типичного поведения клиента: {names}"
    return types, "Отклонение выявлено моделью по совокупности признаков без выраженного единичного фактора"


def shap_factors(
    bundle: ModelBundle, features: dict[str, float], top_k: int = 6
) -> list[dict[str, Any]]:
    """Признаки с наибольшим вкладом в оценку. Положительный вклад повышает степень аномальности."""
    try:
        x = np.array([[features[name] for name in bundle.feature_names]], dtype=float)
        contributions = bundle.shap_values(x)[0]
    except Exception:  # SHAP не должен ломать обработку транзакции
        log.exception("Не удалось рассчитать SHAP-вклады")
        return []
    order = np.argsort(-np.abs(contributions))[:top_k]
    factors = []
    for idx in order:
        name = bundle.feature_names[idx]
        value = float(contributions[idx])
        if abs(value) < 1e-9:
            continue
        factors.append(
            {
                "feature": name,
                "label": FEATURE_LABELS_RU.get(name, name),
                "value": float(features[name]),
                "contribution": value,
                "direction": "increases" if value > 0 else "decreases",
            }
        )
    return factors
