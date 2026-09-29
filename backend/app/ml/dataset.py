"""Построение матрицы признаков по историческим транзакциям.

Транзакции обрабатываются в хронологическом порядке тем же кодом, что и онлайн:
признаки считаются по профилю ДО текущей операции, затем профиль обновляется.
Политика удержания (hold_policy): «rule» — детерминированное правило should_hold по признакам (как в эксплуатации),
«labels» — вне профиля остаются истинные аномалии (только для сравнения), «none» — профиль обновляется всегда.
Во всех случаях операция учитывается в признаках частоты (activity).
"""
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
) -> pd.DataFrame:
    rates = rates or DEFAULT_CURRENCY_RATES
    profiles: dict[str, dict] = {}
    records: list[dict] = []
    has_labels = "is_anomaly" in df.columns

    for row in df.sort_values("timestamp", kind="stable").to_dict("records"):
        tx = normalize(
            {
                "transaction_id": row["transaction_id"],
                "client_id": row["client_id"],
                "timestamp": pd.Timestamp(row["timestamp"]).to_pydatetime(),
                "amount": row["amount"],
                "currency": row["currency"],
                "category": row["category"],
                "channel": row["channel"],
                "recipient_id": row.get("recipient_id"),
                "recipient_category": row.get("recipient_category"),
            },
            rates,
        )
        profile = profiles.setdefault(tx.client_id, new_profile())
        features, _ = compute_features(profile, tx, min_history, population)
        is_anomaly = bool(row["is_anomaly"]) if has_labels else False
        records.append(
            {
                "transaction_id": tx.transaction_id,
                "client_id": tx.client_id,
                "timestamp": tx.ts,
                "is_anomaly": is_anomaly,
                "anomaly_type": row.get("anomaly_type", "") if has_labels else "",
                **features,
            }
        )
        update_activity(profile, tx.epoch)
        if hold_policy == "rule":
            hold = should_hold(features)
        elif hold_policy == "labels":
            hold = is_anomaly
        else:
            hold = False
        if not hold:
            update_behavior(profile, tx)

    frame = pd.DataFrame.from_records(records, columns=META_COLUMNS + FEATURE_NAMES)
    frame["is_anomaly"] = frame["is_anomaly"].astype(bool)
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
