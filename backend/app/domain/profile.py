"""Динамический поведенческий профиль клиента.

Профиль хранится как JSON-словарь и обновляется инкрементально после каждой транзакции:
статистика логарифма суммы (алгоритм Велфорда), окно последних сумм для медианы,
гистограммы часов и дней недели, частоты категорий, каналов, валют, получателей.

Обновление разделено на две части:
* activity: моменты времени операций, нужны для признаков частоты (обновляется всегда);
* behavior: типичное поведение (суммы, категории, часы...). Операции высокого риска не попадают
  в типичное поведение, пока специалист не подтвердит их как нормальные.
"""
import math
from collections import Counter
from typing import Any

from app.domain.preprocessing import Tx

AMOUNT_WINDOW = 100
TS_WINDOW = 200
MAX_RECIPIENTS = 300


def new_profile() -> dict[str, Any]:
    return {
        "n": 0,
        "log_mean": 0.0,
        "log_m2": 0.0,
        "max_amount": 0.0,
        "amounts": [],
        "hour_counts": [0] * 24,
        "weekday_counts": [0] * 7,
        "categories": {},
        "channels": {},
        "recipient_categories": {},
        "currencies": {},
        "recipients": {},
        "activity_n": 0,
        "first_ts": None,
        "last_ts": None,
        "recent_ts": [],
    }


def update_activity(profile: dict[str, Any], epoch: float) -> None:
    profile["activity_n"] += 1
    if profile["first_ts"] is None or epoch < profile["first_ts"]:
        profile["first_ts"] = epoch
    if profile["last_ts"] is None or epoch > profile["last_ts"]:
        profile["last_ts"] = epoch
    recent = profile["recent_ts"]
    recent.append(epoch)
    recent.sort()
    if len(recent) > TS_WINDOW:
        del recent[: len(recent) - TS_WINDOW]


def update_behavior(profile: dict[str, Any], tx: Tx) -> None:
    profile["n"] += 1
    n = profile["n"]
    x = math.log1p(tx.amount_base)
    delta = x - profile["log_mean"]
    profile["log_mean"] += delta / n
    profile["log_m2"] += delta * (x - profile["log_mean"])
    profile["max_amount"] = max(profile["max_amount"], tx.amount_base)

    amounts = profile["amounts"]
    amounts.append(tx.amount_base)
    if len(amounts) > AMOUNT_WINDOW:
        del amounts[: len(amounts) - AMOUNT_WINDOW]

    profile["hour_counts"][tx.ts.hour] += 1
    profile["weekday_counts"][tx.ts.weekday()] += 1
    _inc(profile["categories"], tx.category)
    _inc(profile["channels"], tx.channel)
    _inc(profile["currencies"], tx.currency)
    if tx.recipient_category:
        _inc(profile["recipient_categories"], tx.recipient_category)
    if tx.recipient_id:
        recipients = profile["recipients"]
        _inc(recipients, tx.recipient_id)
        if len(recipients) > MAX_RECIPIENTS:
            for key, _ in sorted(recipients.items(), key=lambda kv: kv[1])[: len(recipients) - MAX_RECIPIENTS]:
                del recipients[key]


def _inc(counter: dict[str, int], key: str) -> None:
    counter[key] = counter.get(key, 0) + 1


def log_std(profile: dict[str, Any]) -> float:
    n = profile["n"]
    return math.sqrt(profile["log_m2"] / (n - 1)) if n > 1 else 0.0


def typical_hours(profile: dict[str, Any], coverage: float = 0.8) -> list[int]:
    """Наименьший набор часов, покрывающий заданную долю операций клиента."""
    counts = profile["hour_counts"]
    total = sum(counts)
    if total == 0:
        return []
    chosen, covered = [], 0
    for hour, count in sorted(enumerate(counts), key=lambda hc: -hc[1]):
        if count == 0 or covered >= coverage * total:
            break
        chosen.append(hour)
        covered += count
    return sorted(chosen)


def summarize(profile: dict[str, Any]) -> dict[str, Any]:
    """Компактное представление профиля для API и интерфейса."""
    amounts = sorted(profile["amounts"])
    count = len(amounts)
    if count:
        median = amounts[count // 2] if count % 2 else (amounts[count // 2 - 1] + amounts[count // 2]) / 2
        p90 = amounts[min(count - 1, int(0.9 * count))]
    else:
        median = p90 = None
    span_days = 0.0
    if profile["first_ts"] is not None and profile["last_ts"] is not None:
        span_days = (profile["last_ts"] - profile["first_ts"]) / 86400.0
    return {
        "transactions_in_profile": profile["n"],
        "transactions_seen": profile["activity_n"],
        "median_amount": median,
        "p90_amount": p90,
        "mean_amount_geometric": math.expm1(profile["log_mean"]) if profile["n"] else None,
        "max_amount": profile["max_amount"] or None,
        "typical_hours": typical_hours(profile),
        "hour_counts": profile["hour_counts"],
        "weekday_counts": profile["weekday_counts"],
        "categories": dict(Counter(profile["categories"]).most_common()),
        "channels": dict(Counter(profile["channels"]).most_common()),
        "currencies": dict(Counter(profile["currencies"]).most_common()),
        "recipient_categories": dict(Counter(profile["recipient_categories"]).most_common()),
        "known_recipients": len(profile["recipients"]),
        "avg_transactions_per_day": (profile["activity_n"] / max(span_days, 1.0)) if profile["activity_n"] else 0.0,
    }
