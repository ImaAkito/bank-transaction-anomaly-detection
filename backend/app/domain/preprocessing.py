"""Модуль предварительной обработки: валидация и нормализация входной транзакции."""
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


class PreprocessingError(ValueError):
    """Транзакция не может быть обработана (некорректные или неподдерживаемые данные)."""


@dataclass(frozen=True)
class Tx:
    transaction_id: str
    client_id: str
    ts: datetime
    amount: float
    currency: str
    amount_base: float
    category: str
    channel: str
    recipient_id: str | None = None
    recipient_category: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def epoch(self) -> float:
        return self.ts.timestamp()


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def normalize(raw: dict[str, Any], rates: dict[str, float]) -> Tx:
    """Приводит сырую транзакцию к единому виду.

    Строки очищаются от пробелов, категория и канал приводятся к нижнему регистру, валюта к верхнему.
    Время без часового пояса трактуется как UTC. Сумма пересчитывается в базовую валюту по таблице курсов.
    """
    transaction_id = _clean(raw.get("transaction_id"))
    client_id = _clean(raw.get("client_id"))
    if not transaction_id:
        raise PreprocessingError("transaction_id не задан")
    if not client_id:
        raise PreprocessingError("client_id не задан")

    try:
        amount = float(raw.get("amount"))
    except (TypeError, ValueError) as exc:
        raise PreprocessingError("amount должен быть числом") from exc
    if not math.isfinite(amount) or amount <= 0:
        raise PreprocessingError("amount должен быть положительным конечным числом")

    currency = (_clean(raw.get("currency")) or "").upper()
    if currency not in rates:
        raise PreprocessingError(f"Неподдерживаемая валюта: {currency or 'не задана'}")

    category = (_clean(raw.get("category")) or "").lower()
    if not category:
        raise PreprocessingError("category не задана")
    channel = (_clean(raw.get("channel")) or "unknown").lower()

    ts = raw.get("timestamp")
    if not isinstance(ts, datetime):
        raise PreprocessingError("timestamp должен быть датой и временем")
    ts = ts.replace(tzinfo=timezone.utc) if ts.tzinfo is None else ts.astimezone(timezone.utc)

    recipient_category = _clean(raw.get("recipient_category"))
    return Tx(
        transaction_id=transaction_id,
        client_id=client_id,
        ts=ts,
        amount=amount,
        currency=currency,
        amount_base=amount * rates[currency],
        category=category,
        channel=channel,
        recipient_id=_clean(raw.get("recipient_id")),
        recipient_category=recipient_category.lower() if recipient_category else None,
        extra=dict(raw.get("extra") or {}),
    )
