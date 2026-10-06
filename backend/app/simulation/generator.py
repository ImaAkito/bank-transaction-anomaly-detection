"""Генератор синтетических банковских транзакций с размеченными аномалиями.

У каждого клиента своя «персона»: набор регулярных категорий и каналов, типичная сумма и разброс,
типичные часы активности, интенсивность операций, пул постоянных получателей. Нормальное поведение
содержит естественный шум (крупные разовые покупки, редкие ночные и новые категории), поэтому задача
не сводится к пороговому правилу. Аномалии внедряются после warm-up периода клиента и размечаются типом.

Суммы задаются в белорусских рублях (BYN) и ориентированы на типичные цены в Беларуси; медианы категорий
приблизительные. Клиент совершает в среднем 1–4 операции в сутки.
"""
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

# Медианы сумм в BYN.
CATEGORIES: dict[str, dict] = {
    "groceries": {"median": 35, "recipient": "merchant", "risky": False, "pool": (6, 15), "channel": "card_pos"},
    "restaurants": {"median": 40, "recipient": "merchant", "risky": False, "pool": (5, 12), "channel": "card_pos"},
    "transport": {"median": 8, "recipient": "merchant", "risky": False, "pool": (2, 5), "channel": "card_pos"},
    "utilities": {"median": 120, "recipient": "utility", "risky": False, "pool": (2, 4), "channel": "mobile_app"},
    "entertainment": {"median": 35, "recipient": "merchant", "risky": False, "pool": (3, 8), "channel": "web"},
    "health": {"median": 30, "recipient": "merchant", "risky": False, "pool": (2, 5), "channel": "card_pos"},
    "clothing": {"median": 120, "recipient": "merchant", "risky": False, "pool": (3, 8), "channel": "card_pos"},
    "p2p_transfer": {"median": 100, "recipient": "person", "risky": False, "pool": (3, 8), "channel": "mobile_app"},
    "online_shopping": {"median": 70, "recipient": "merchant", "risky": False, "pool": (4, 10), "channel": "web"},
    "travel": {"median": 450, "recipient": "merchant", "risky": False, "pool": (2, 6), "channel": "web"},
    "education": {"median": 250, "recipient": "merchant", "risky": False, "pool": (1, 3), "channel": "web"},
    "cash_withdrawal": {"median": 150, "recipient": "atm", "risky": False, "pool": (3, 8), "channel": "atm"},
    "electronics": {"median": 900, "recipient": "merchant", "risky": True, "pool": (2, 5), "channel": "web"},
    "jewelry": {"median": 1200, "recipient": "merchant", "risky": True, "pool": (1, 3), "channel": "card_pos"},
    "crypto_exchange": {"median": 1000, "recipient": "exchange", "risky": True, "pool": (1, 3), "channel": "web"},
    "gambling": {"median": 200, "recipient": "gambling", "risky": True, "pool": (1, 3), "channel": "web"},
}
REGULAR_CATEGORIES = [c for c, v in CATEGORIES.items() if not v["risky"]]
RISKY_CATEGORIES = [c for c, v in CATEGORIES.items() if v["risky"]]
CHANNELS = ["card_pos", "mobile_app", "web", "atm"]
BASE_CURRENCY = "BYN"
# Курсы к BYN (совпадают с DEFAULT_CURRENCY_RATES в app.config).
FOREIGN_CURRENCIES = {"USD": 3.0, "EUR": 3.4, "RUB": 0.037, "PLN": 0.8}

ANOMALY_TYPES = ["amount_spike", "night_activity", "new_category_high", "burst", "foreign_channel", "mild_combo"]
ANOMALY_WEIGHTS = [0.27, 0.22, 0.22, 0.05, 0.16, 0.08]

COLUMNS = [
    "transaction_id",
    "client_id",
    "timestamp",
    "amount",
    "currency",
    "category",
    "recipient_id",
    "recipient_category",
    "channel",
    "is_anomaly",
    "anomaly_type",
]


@dataclass
class ClientPersona:
    client_id: str
    categories: list[str]
    weights: np.ndarray
    scale: float
    sigma: float
    hour_mu: float
    hour_sd: float
    rate: float
    weekend_factor: float
    channels: list[str]
    secondary_currency: str | None
    secondary_prob: float
    pools: dict[str, list[str]] = field(default_factory=dict)
    new_recipient_counter: int = 0


def _make_persona(idx: int, rng: np.random.Generator) -> ClientPersona:
    client_id = f"C{idx:05d}"
    k = int(rng.integers(4, 8))
    categories = list(rng.choice(REGULAR_CATEGORIES, size=k, replace=False))
    weights = rng.dirichlet(np.ones(k) * 1.5)
    channels = sorted({CATEGORIES[c]["channel"] for c in categories})
    if len(channels) >= 4:
        channels = channels[:3]
    if len(channels) < 2:
        channels = sorted(set(channels) | {"mobile_app" if "mobile_app" not in channels else "web"})
    pools: dict[str, list[str]] = {}
    for c in categories:
        low, high = CATEGORIES[c]["pool"]
        size = int(rng.integers(low, high + 1))
        pools[c] = [f"{CATEGORIES[c]['recipient'][:3].upper()}-{client_id}-{c[:4]}-{j}" for j in range(size)]
    secondary = None
    if rng.random() < 0.25:
        secondary = str(rng.choice(list(FOREIGN_CURRENCIES)))
    return ClientPersona(
        client_id=client_id,
        categories=categories,
        weights=weights,
        scale=float(rng.lognormal(0.0, 0.45)),
        sigma=float(rng.uniform(0.35, 0.7)),
        hour_mu=float(rng.choice([10.0, 13.0, 15.0, 18.0, 20.0])),
        hour_sd=float(rng.uniform(2.0, 3.5)),
        rate=float(rng.uniform(1.0, 4.0)),
        weekend_factor=float(rng.uniform(0.6, 1.4)),
        channels=channels,
        secondary_currency=secondary,
        secondary_prob=float(rng.uniform(0.01, 0.05)) if secondary else 0.0,
        pools=pools,
    )


def _channel_for(persona: ClientPersona, category: str, rng: np.random.Generator) -> str:
    primary = CATEGORIES[category]["channel"]
    if primary in persona.channels and rng.random() < 0.9:
        return primary
    return str(rng.choice(persona.channels))


def _recipient_category(category: str) -> str:
    return CATEGORIES[category]["recipient"]


def _new_recipient(persona: ClientPersona, category: str) -> str:
    persona.new_recipient_counter += 1
    return f"NEW-{persona.client_id}-{persona.new_recipient_counter}"


def _row(persona: ClientPersona, ts: datetime, amount_base: float, category: str, channel: str,
         recipient: str, currency: str = BASE_CURRENCY, label: bool = False, kind: str = "") -> dict:
    rate = 1.0 if currency == BASE_CURRENCY else FOREIGN_CURRENCIES[currency]
    return {
        "client_id": persona.client_id,
        "timestamp": ts,
        "amount": round(max(amount_base / rate, 0.5), 2),
        "currency": currency,
        "category": category,
        "recipient_id": recipient,
        "recipient_category": _recipient_category(category),
        "channel": channel,
        "is_anomaly": label,
        "anomaly_type": kind,
    }


def _base_amount(persona: ClientPersona, category: str, rng: np.random.Generator) -> float:
    return CATEGORIES[category]["median"] * persona.scale * float(rng.lognormal(0.0, persona.sigma))


def _normal_hour(persona: ClientPersona, rng: np.random.Generator) -> int:
    if rng.random() < 0.015:
        return int(rng.integers(0, 6))
    return int(round(rng.normal(persona.hour_mu, persona.hour_sd))) % 24


def _normal_tx(persona: ClientPersona, day: datetime, rng: np.random.Generator) -> dict:
    hour = _normal_hour(persona, rng)
    ts = day + timedelta(hours=hour, minutes=int(rng.integers(0, 60)), seconds=int(rng.integers(0, 60)))
    if rng.random() < 0.015:
        category = str(rng.choice(REGULAR_CATEGORIES))
    else:
        category = str(rng.choice(persona.categories, p=persona.weights))
    amount = _base_amount(persona, category, rng)
    if rng.random() < 0.01:
        amount *= float(rng.uniform(2.5, 4.0))
    pool = persona.pools.get(category)
    if pool and rng.random() < 0.92:
        recipient = str(rng.choice(pool))
    else:
        recipient = _new_recipient(persona, category)
    currency = BASE_CURRENCY
    if persona.secondary_currency and rng.random() < persona.secondary_prob:
        currency = persona.secondary_currency
    return _row(persona, ts, amount, category, _channel_for(persona, category, rng), recipient, currency)


def _anomaly_rows(persona: ClientPersona, kind: str, day: datetime, rng: np.random.Generator) -> list[dict]:
    minute, second = int(rng.integers(0, 60)), int(rng.integers(0, 60))
    typical_hour = int(round(persona.hour_mu)) % 24
    category = str(rng.choice(persona.categories, p=persona.weights))
    base = _base_amount(persona, category, rng)
    channel = _channel_for(persona, category, rng)
    recipient = str(rng.choice(persona.pools[category]))

    def at(hour: int) -> datetime:
        return day + timedelta(hours=hour, minutes=minute, seconds=second)

    if kind == "amount_spike":
        hour = _normal_hour(persona, rng)
        return [_row(persona, at(hour), base * rng.uniform(6, 25), category, channel, recipient, label=True, kind=kind)]
    if kind == "night_activity":
        return [_row(persona, at(int(rng.integers(1, 5))), base * rng.uniform(1.5, 5), category, channel,
                     _new_recipient(persona, category), label=True, kind=kind)]
    if kind == "new_category_high":
        new_category = str(rng.choice([c for c in RISKY_CATEGORIES if c not in persona.categories]))
        hour = _normal_hour(persona, rng)
        amount = CATEGORIES[new_category]["median"] * persona.scale * rng.uniform(3, 10)
        return [_row(persona, at(hour), amount, new_category, _channel_for(persona, category, rng),
                     _new_recipient(persona, new_category), label=True, kind=kind)]
    if kind == "burst":
        count = int(rng.integers(4, 9))
        start = at(_normal_hour(persona, rng))
        rows, ts = [], start
        for _ in range(count):
            rows.append(_row(persona, ts, base * rng.uniform(1, 3), category, channel,
                             _new_recipient(persona, category) if rng.random() < 0.7 else recipient,
                             label=True, kind=kind))
            ts = ts + timedelta(seconds=int(rng.integers(20, 120)))
        return rows
    if kind == "foreign_channel":
        unused = [c for c in CHANNELS if c not in persona.channels] or ["web"]
        currency = str(rng.choice(list(FOREIGN_CURRENCIES)))
        return [_row(persona, at(_normal_hour(persona, rng)), base * rng.uniform(2, 8), category,
                     str(rng.choice(unused)), _new_recipient(persona, category), currency, True, kind)]
    # mild_combo: умеренное превышение суммы в нетипичный час у нового получателя
    shift = int(rng.choice([-1, 1])) * int(rng.integers(6, 9))
    hour = (typical_hour + shift) % 24
    return [_row(persona, at(hour), base * rng.uniform(2.5, 4), category, channel,
                 _new_recipient(persona, category), label=True, kind=kind)]


def generate_transactions(
    n_clients: int = 300,
    days: int = 60,
    seed: int = 42,
    start: datetime | None = None,
    anomaly_rate: float = 0.012,
    anomaly_start_day: int = 7,
    id_prefix: str = "T",
    client_offset: int = 0,
) -> pd.DataFrame:
    """Возвращает DataFrame транзакций, упорядоченный по времени, с колонками is_anomaly и anomaly_type."""
    rng = np.random.default_rng(seed)
    start = start or datetime(2025, 1, 1, tzinfo=timezone.utc)
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    start = start.replace(hour=0, minute=0, second=0, microsecond=0)

    personas = [_make_persona(client_offset + i, rng) for i in range(n_clients)]
    rows: list[dict] = []
    for persona in personas:
        for d in range(days):
            day = start + timedelta(days=d)
            rate = persona.rate * (persona.weekend_factor if day.weekday() >= 5 else 1.0)
            for _ in range(int(rng.poisson(rate))):
                if d >= anomaly_start_day and rng.random() < anomaly_rate:
                    kind = str(rng.choice(ANOMALY_TYPES, p=ANOMALY_WEIGHTS))
                    rows.extend(_anomaly_rows(persona, kind, day, rng))
                else:
                    rows.append(_normal_tx(persona, day, rng))

    df = pd.DataFrame(rows)
    df = df.sort_values(["timestamp", "client_id"], kind="stable").reset_index(drop=True)
    df.insert(0, "transaction_id", [f"{id_prefix}{seed}-{i:08d}" for i in range(len(df))])
    return df[COLUMNS]
