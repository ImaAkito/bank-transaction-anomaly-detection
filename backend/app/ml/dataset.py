"""Построение матрицы признаков по историческим транзакциям.

Транзакции обрабатываются в хронологическом порядке тем же кодом, что и онлайн:
признаки считаются по профилю ДО текущей операции, затем профиль обновляется.
Политика удержания (hold_policy): «rule» — детерминированное правило should_hold по признакам (как в эксплуатации),
«labels» — вне профиля остаются истинные аномалии (только для сравнения), «none» — профиль обновляется всегда.
Во всех случаях операция учитывается в признаках частоты (activity).
"""
import numpy as np
import pandas as pd

from app.config import DEFAULT_CURRENCY_RATES
from app.domain.features import FEATURE_NAMES, compute_features, should_hold
from app.domain.preprocessing import normalize
from app.domain.profile import new_profile, update_activity, update_behavior

META_COLUMNS = ["transaction_id", "client_id", "timestamp", "is_anomaly", "anomaly_type"]


def build_feature_frame(
    df: pd.DataFrame,
    rates: dict[str, float] | None = None,
    min_history: int = 5,
    hold_policy: str = "rule",
    population: dict | None = None,
    population_mode: str = "fixed",
) -> pd.DataFrame:
    """population_mode: «fixed» — популяционные частоты из обучающего периода (как в эксплуатации, хранятся
    в артефакте модели); «causal» — частоты по всем операциям строго до текущей (без заглядывания в будущее,
    одинаково для обучающих и тестовых строк)."""
    rates = rates or DEFAULT_CURRENCY_RATES
    running = None
    if population_mode == "causal":
        running = {"n": 0, "categories": {}, "channels": {}, "recipient_categories": {}, "recipient_categories_n": 0}
        population = running
    profiles: dict[str, dict] = {}
    has_labels = "is_anomaly" in df.columns
    ordered = df.sort_values("timestamp", kind="stable").reset_index(drop=True)
    n = len(ordered)
    # Признаки пишутся сразу в массив: список словарей на строку занимал бы в разы больше памяти.
    values = np.empty((n, len(FEATURE_NAMES)), dtype=np.float64)
    stamps = pd.to_datetime(ordered["timestamp"], utc=True)
    labels = ordered["is_anomaly"].astype(bool).to_numpy() if has_labels else np.zeros(n, dtype=bool)

    def column(name: str):
        return ordered[name].tolist() if name in ordered.columns else [None] * n

    cols = {name: column(name) for name in (
        "transaction_id", "client_id", "amount", "currency", "category", "channel",
        "recipient_id", "recipient_category", "timezone")}
    py_stamps = stamps.dt.to_pydatetime() if hasattr(stamps.dt, "to_pydatetime") else list(stamps)

    for i in range(n):
        tx = normalize(
            {
                "transaction_id": cols["transaction_id"][i],
                "client_id": cols["client_id"][i],
                "timestamp": py_stamps[i],
                "amount": cols["amount"][i],
                "currency": cols["currency"][i],
                "category": cols["category"][i],
                "channel": cols["channel"][i],
                "recipient_id": cols["recipient_id"][i],
                "recipient_category": cols["recipient_category"][i],
                "timezone": cols["timezone"][i],
            },
            rates,
        )
        profile = profiles.setdefault(tx.client_id, new_profile())
        features, _ = compute_features(profile, tx, min_history, population)
        if running is not None:
            running["n"] += 1
            running["categories"][tx.category] = running["categories"].get(tx.category, 0) + 1
            running["channels"][tx.channel] = running["channels"].get(tx.channel, 0) + 1
            if tx.recipient_category:
                running["recipient_categories_n"] += 1
                rc = running["recipient_categories"]
                rc[tx.recipient_category] = rc.get(tx.recipient_category, 0) + 1
        values[i] = [features[name] for name in FEATURE_NAMES]
        update_activity(profile, tx.epoch)
        if hold_policy == "rule":
            hold = should_hold(features)
        elif hold_policy == "labels":
            hold = bool(labels[i])
        else:
            hold = False
        if not hold:
            update_behavior(profile, tx)

    frame = pd.DataFrame(values, columns=FEATURE_NAMES)
    frame.insert(0, "transaction_id", ordered["transaction_id"].astype(str).str.strip().to_numpy())
    frame.insert(1, "client_id", ordered["client_id"].astype(str).str.strip().to_numpy())
    frame.insert(2, "timestamp", stamps.to_numpy())
    frame.insert(3, "is_anomaly", labels)
    anomaly_type = ordered["anomaly_type"].fillna("").astype(str) if has_labels and "anomaly_type" in ordered else pd.Series("", index=ordered.index)
    frame.insert(4, "anomaly_type", anomaly_type.to_numpy())
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
    return frame


def fit_population_on_train(df: pd.DataFrame, train_frac: float = 0.65) -> dict:
    """Популяционные частоты по обучающему периоду (тому же, что даёт time_split), без меток."""
    from app.domain.features import fit_population

    ordered = df.sort_values("timestamp", kind="stable")
    cutoff = int(len(ordered) * train_frac)
    return fit_population(ordered.iloc[:cutoff])


def time_split(frame: pd.DataFrame, train_frac: float = 0.65, val_frac: float = 0.15):
    """Хронологическое разбиение: обучение, валидация (подбор параметров), тест."""
    ordered = frame.sort_values("timestamp", kind="stable").reset_index(drop=True)
    n = len(ordered)
    i, j = int(n * train_frac), int(n * (train_frac + val_frac))
    return ordered.iloc[:i].copy(), ordered.iloc[i:j].copy(), ordered.iloc[j:].copy()
