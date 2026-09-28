"""Модуль формирования признаков.

Признаки строятся по транзакции и профилю клиента, накопленному ДО этой транзакции.
Одна и та же функция используется при обучении (последовательный проход по истории)
и при онлайн-оценке, поэтому расхождения между обучением и эксплуатацией исключены на уровне кода.
"""
import math
from typing import Any

import numpy as np

from app.domain.preprocessing import Tx

FEATURE_GROUPS: dict[str, list[str]] = {
    "amount": ["log_amount", "log_ratio_median", "amount_zscore", "amount_to_max"],
    "time": ["hour_sin", "hour_cos", "is_night", "hour_freq", "weekday_freq"],
    "velocity": ["log_secs_since_last", "tx_count_1h", "tx_count_24h", "rate_ratio"],
    "novelty": [
        "category_freq",
        "is_new_category",
        "channel_freq",
        "is_new_channel",
        "recipient_cat_freq",
        "is_new_recipient",
        "currency_freq",
        "is_new_currency",
    ],
    "history": ["log_history_len"],
}
FEATURE_NAMES: list[str] = [name for names in FEATURE_GROUPS.values() for name in names]
# Признаки, не зависящие от профиля клиента (контекстно-независимая базовая модель).
CONTEXT_FREE_FEATURES = ["log_amount", "hour_sin", "hour_cos", "is_night"]

FEATURE_LABELS_RU: dict[str, str] = {
    "log_amount": "Абсолютная сумма операции",
    "log_ratio_median": "Отношение суммы к медиане клиента",
    "amount_zscore": "Отклонение суммы от средней (z-оценка)",
    "amount_to_max": "Отношение суммы к максимуму клиента",
    "hour_sin": "Время суток (sin)",
    "hour_cos": "Время суток (cos)",
    "is_night": "Ночное время",
    "hour_freq": "Частота операций клиента в этот час",
    "weekday_freq": "Частота операций клиента в этот день недели",
    "log_secs_since_last": "Время с предыдущей операции",
    "tx_count_1h": "Число операций за последний час",
    "tx_count_24h": "Число операций за последние сутки",
    "rate_ratio": "Интенсивность относительно обычной",
    "category_freq": "Частота категории у клиента",
    "is_new_category": "Новая категория для клиента",
    "channel_freq": "Частота канала у клиента",
    "is_new_channel": "Новый канал для клиента",
    "recipient_cat_freq": "Частота категории получателя у клиента",
    "is_new_recipient": "Новый получатель",
    "currency_freq": "Частота валюты у клиента",
    "is_new_currency": "Новая валюта для клиента",
    "log_history_len": "Объём истории клиента",
}

# Априорные значения частот для клиентов с короткой историей (сглаживание Лапласа).
PRIORS = {
    "hour_freq": 0.2,
    "weekday_freq": 1 / 7,
    "category_freq": 0.2,
    "channel_freq": 0.4,
    "recipient_cat_freq": 0.25,
    "currency_freq": 0.9,
}
SMOOTHING = 10.0
MIN_STD = 0.3
MATURITY_K = 15.0  # признаки новизны и z-оценка ослабляются на коротких историях: n / (n + K)
MAX_SECS = 30 * 86400.0


def _smoothed(count: float, total: float, prior: float) -> float:
    return (count + SMOOTHING * prior) / (total + SMOOTHING)


def _median(values: list[float]) -> float:
    return float(np.median(values)) if values else 0.0


def compute_features(
    profile: dict[str, Any], tx: Tx, min_history: int = 5
) -> tuple[dict[str, float], dict[str, Any]]:
    """Возвращает (признаки, контекст). Контекст нужен модулю интерпретации, в модель не подаётся."""
    n = profile["n"]
    warm = n >= min_history
    maturity = n / (n + MATURITY_K) if MATURITY_K > 0 else 1.0
    hour = tx.ts.hour
    log_amount = math.log1p(tx.amount_base)

    median = _median(profile["amounts"])
    if warm and median > 0:
        ratio = tx.amount_base / median
        log_ratio = float(np.clip(math.log(max(ratio, 1e-6)), -6.0, 6.0))
    else:
        ratio, log_ratio = 1.0, 0.0
    if warm:
        std = max(math.sqrt(profile["log_m2"] / (n - 1)), MIN_STD)
        zscore = float(np.clip((log_amount - profile["log_mean"]) / std, -10.0, 10.0)) * maturity
        max_amount = profile["max_amount"]
        to_max = min(tx.amount_base / max_amount, 20.0) if max_amount > 0 else 1.0
    else:
        zscore, to_max = 0.0, 1.0

    hc = profile["hour_counts"]
    hour_count = hc[(hour - 1) % 24] + hc[hour] + hc[(hour + 1) % 24]
    hour_freq = _smoothed(hour_count, n, PRIORS["hour_freq"])
    weekday_freq = _smoothed(profile["weekday_counts"][tx.ts.weekday()], n, PRIORS["weekday_freq"])

    epoch = tx.epoch
    last_ts = profile["last_ts"]
    secs_since_last = MAX_SECS if last_ts is None else float(np.clip(epoch - last_ts, 0.0, MAX_SECS))
    recent = profile["recent_ts"]
    count_1h = sum(1 for t in recent if epoch - 3600.0 <= t <= epoch)
    count_24h = sum(1 for t in recent if epoch - 86400.0 <= t <= epoch)
    if profile["activity_n"] and profile["first_ts"] is not None:
        span_days = max((epoch - profile["first_ts"]) / 86400.0, 1.0)
        avg_daily = profile["activity_n"] / span_days
    else:
        avg_daily = 0.0
    rate_ratio = min((count_24h + 1.0) / (avg_daily + 1.0), 20.0)

    cat_count = profile["categories"].get(tx.category, 0)
    chan_count = profile["channels"].get(tx.channel, 0)
    curr_count = profile["currencies"].get(tx.currency, 0)
    rc_count = profile["recipient_categories"].get(tx.recipient_category, 0) if tx.recipient_category else 0
    rc_total = sum(profile["recipient_categories"].values())
    if tx.recipient_category:
        recipient_cat_freq = _smoothed(rc_count, rc_total, PRIORS["recipient_cat_freq"])
    else:
        recipient_cat_freq = PRIORS["recipient_cat_freq"]
    new_recipient = bool(tx.recipient_id) and tx.recipient_id not in profile["recipients"]

    features = {
        "log_amount": log_amount,
        "log_ratio_median": log_ratio,
        "amount_zscore": zscore,
        "amount_to_max": to_max,
        "hour_sin": math.sin(2 * math.pi * hour / 24),
        "hour_cos": math.cos(2 * math.pi * hour / 24),
        "is_night": 1.0 if hour < 6 else 0.0,
        "hour_freq": hour_freq,
        "weekday_freq": weekday_freq,
        "log_secs_since_last": math.log1p(secs_since_last),
        "tx_count_1h": float(count_1h),
        "tx_count_24h": float(count_24h),
        "rate_ratio": rate_ratio,
        "category_freq": _smoothed(cat_count, n, PRIORS["category_freq"]),
        "is_new_category": maturity if warm and cat_count == 0 else 0.0,
        "channel_freq": _smoothed(chan_count, n, PRIORS["channel_freq"]),
        "is_new_channel": maturity if warm and chan_count == 0 else 0.0,
        "recipient_cat_freq": recipient_cat_freq,
        "is_new_recipient": maturity if warm and new_recipient else 0.0,
        "currency_freq": _smoothed(curr_count, n, PRIORS["currency_freq"]),
        "is_new_currency": maturity if warm and curr_count == 0 else 0.0,
        "log_history_len": math.log1p(n),
    }
    context = {
        "warm": warm,
        "history_len": n,
        "median_amount": median if warm else None,
        "amount_ratio": ratio,
        "hour": hour,
        "hour_share": hour_count / n if n else 0.0,
        "secs_since_last": secs_since_last if last_ts is not None else None,
        "count_1h": count_1h,
        "count_24h": count_24h,
        "avg_daily": avg_daily,
        "category": tx.category,
        "channel": tx.channel,
        "currency": tx.currency,
        "recipient_id": tx.recipient_id,
        "known_categories": sorted(profile["categories"]),
        "known_channels": sorted(profile["channels"]),
    }
    return features, context


HOLD_RATIO = 5.0
HOLD_BURST_COUNT = 3


def should_hold(features: dict[str, float]) -> bool:
    """Правило удержания операции вне «типичного поведения» профиля.

    Удерживаются операции, способные исказить статистику профиля: выброс по сумме (не менее чем в 5 раз выше
    медианы) и всплеск частоты (3 и более операций за предыдущий час). Новизна категории, канала, получателя
    или времени не удерживается: легитимное изменение привычек должно попадать в профиль.
    Правило зависит только от признаков, поэтому одинаково применяется при обучении и в эксплуатации.
    Удержанная операция добавляется в профиль, если специалист подтвердит её как нормальную.
    """
    return features["log_ratio_median"] >= math.log(HOLD_RATIO) or features["tx_count_1h"] >= HOLD_BURST_COUNT


def to_vector(features: dict[str, float], names: list[str] | None = None) -> np.ndarray:
    names = names or FEATURE_NAMES
    return np.array([[features[name] for name in names]], dtype=float)
