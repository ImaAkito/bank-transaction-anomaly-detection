"""Загрузчик набора IBM «Credit Card Transactions» (TabFormer) в формат проекта.

Ожидаемые колонки файла (регистр, пробелы и знак «?» в названиях не важны):
User, Card, Year, Month, Day, Time, Amount, Use Chip, Merchant Name, Merchant City, Merchant State,
Zip, MCC, Errors, Is Fraud.

Отображение полей:
* client_id            ← User (профиль строится на пользователя, а не на карту);
* timestamp            ← Year, Month, Day, Time (трактуется как UTC);
* amount, currency     ← Amount без знака «$», валюта USD; операции с суммой ≤ 0 (возвраты) отбрасываются;
* category             ← группа по коду MCC (частые коды объединены, остальные получают имя mcc_<код>);
* channel              ← Use Chip: card_swipe / card_chip / online;
* recipient_id         ← Merchant Name (хэш мерчанта в исходных данных);
* recipient_category   ← штат мерчанта (online, если он не указан): новый штат служит сигналом географии;
* is_anomaly           ← Is Fraud == Yes, anomaly_type = fraud.

Файл читается частями; отбирается доля пользователей (детерминированно по seed) и период с from_year,
чтобы объём вычислений оставался разумным.
"""
import re
from pathlib import Path

import pandas as pd

from app.simulation.generator import COLUMNS

MCC_GROUPS: list[tuple[range, str]] = [
    (range(3000, 3300), "airlines"),
    (range(3500, 4000), "lodging"),
    (range(4011, 4100), "rail_freight"),
    (range(4111, 4132), "transport"),
    (range(4214, 4215), "freight"),
    (range(4411, 4412), "cruise"),
    (range(4511, 4512), "airlines"),
    (range(4784, 4785), "tolls"),
    (range(4814, 4815), "telecom"),
    (range(4899, 4900), "cable_tv"),
    (range(4900, 4901), "utilities"),
    (range(5200, 5300), "home_improvement"),
    (range(5300, 5400), "retail"),
    (range(5411, 5500), "groceries"),
    (range(5500, 5600), "fuel_auto"),
    (range(5600, 5700), "clothing"),
    (range(5712, 5732), "home_goods"),
    (range(5732, 5735), "electronics"),
    (range(5811, 5815), "restaurants"),
    (range(5912, 5913), "pharmacy"),
    (range(5921, 5999), "specialty_retail"),
    (range(5944, 5945), "jewelry"),
    (range(6011, 6012), "cash_withdrawal"),
    (range(4829, 4830), "money_transfer"),
    (range(6300, 6400), "insurance"),
    (range(7011, 7012), "lodging"),
    (range(7210, 7300), "personal_services"),
    (range(7800, 7999), "entertainment"),
    (range(7995, 7996), "gambling"),
    (range(8000, 8100), "health"),
    (range(8200, 8300), "education"),
    (range(9000, 9500), "government"),
]
CHANNELS = {"swipe": "card_swipe", "chip": "card_chip", "online": "online"}


def mcc_to_category(mcc) -> str:
    try:
        code = int(mcc)
    except (TypeError, ValueError):
        return "mcc_unknown"
    # Более узкие группы (жёстко заданные коды) имеют приоритет над широкими диапазонами.
    matches = [(len(r), name) for r, name in MCC_GROUPS if code in r]
    return min(matches)[1] if matches else f"mcc_{code}"


def _normalize_columns(frame: pd.DataFrame) -> pd.DataFrame:
    frame.columns = [re.sub(r"[^a-z0-9]+", "_", str(c).strip().lower()).strip("_") for c in frame.columns]
    return frame


def _channel(value: str) -> str:
    text = str(value).lower()
    for key, name in CHANNELS.items():
        if key in text:
            return name
    return "unknown"


def _select_users(users: pd.Series, fraction: float, seed: int) -> pd.Series:
    return ((users.astype("int64") * 2654435761 + seed * 40503) % 1000) < int(fraction * 1000)


def load_ibm(path: str | Path, user_fraction: float = 0.05, from_year: int = 2010, seed: int = 42,
             chunksize: int = 1_000_000) -> pd.DataFrame:
    parts: list[pd.DataFrame] = []
    dropped_refunds = 0
    for chunk in pd.read_csv(path, chunksize=chunksize, dtype=str, keep_default_na=False):
        chunk = _normalize_columns(chunk)
        required = {"user", "year", "month", "day", "time", "amount", "use_chip", "merchant_name", "mcc", "is_fraud"}
        missing = required - set(chunk.columns)
        if missing:
            raise ValueError(f"В файле нет колонок: {sorted(missing)}")
        chunk = chunk[_select_users(chunk["user"], user_fraction, seed) & (chunk["year"].astype(int) >= from_year)]
        if chunk.empty:
            continue
        amount = pd.to_numeric(chunk["amount"].str.replace(r"[$,\s]", "", regex=True), errors="coerce")
        keep = amount > 0
        dropped_refunds += int((~keep).sum())
        chunk, amount = chunk[keep], amount[keep]
        timestamp = pd.to_datetime(
            chunk["year"] + "-" + chunk["month"].str.zfill(2) + "-" + chunk["day"].str.zfill(2) + " " + chunk["time"],
            utc=True,
        )
        state = chunk["merchant_state"].str.strip().str.lower() if "merchant_state" in chunk else pd.Series("", index=chunk.index)
        parts.append(
            pd.DataFrame(
                {
                    "client_id": "U" + chunk["user"].str.zfill(5),
                    "timestamp": timestamp,
                    "amount": amount.round(2),
                    "currency": "USD",
                    "category": chunk["mcc"].map(mcc_to_category),
                    "recipient_id": "M" + chunk["merchant_name"],
                    "recipient_category": state.where(state != "", "online"),
                    "channel": chunk["use_chip"].map(_channel),
                    "is_anomaly": chunk["is_fraud"].str.strip().str.lower().eq("yes"),
                }
            )
        )
    if not parts:
        raise ValueError("После фильтрации не осталось транзакций: увеличьте долю пользователей или период")
    df = pd.concat(parts, ignore_index=True).sort_values(["timestamp", "client_id"], kind="stable").reset_index(drop=True)
    df["anomaly_type"] = df["is_anomaly"].map({True: "fraud", False: ""})
    df.insert(0, "transaction_id", [f"IBM{seed}-{i:09d}" for i in range(len(df))])
    df.attrs["dropped_refunds"] = dropped_refunds
    return df[COLUMNS]
