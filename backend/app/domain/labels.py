"""Русские названия категорий, каналов и типов получателей для текстов интерфейса и причин срабатывания.

Внутри системы (данные, признаки, модель) используются коды; названия применяются только при выводе.
"""

CATEGORY_LABELS: dict[str, str] = {
    "groceries": "Продукты",
    "restaurants": "Кафе и рестораны",
    "transport": "Транспорт и такси",
    "utilities": "Коммунальные платежи",
    "entertainment": "Развлечения",
    "health": "Здоровье и аптеки",
    "clothing": "Одежда и обувь",
    "p2p_transfer": "Перевод частному лицу",
    "online_shopping": "Интернет-покупки",
    "travel": "Путешествия",
    "education": "Образование",
    "cash_withdrawal": "Снятие наличных",
    "electronics": "Электроника",
    "jewelry": "Ювелирные изделия",
    "crypto_exchange": "Криптобиржа",
    "gambling": "Азартные игры",
    "retail": "Розничные покупки",
    "fuel": "Топливо",
    "services": "Услуги",
}

CHANNEL_LABELS: dict[str, str] = {
    "card_pos": "Оплата картой",
    "mobile_app": "Мобильный банк",
    "web": "Интернет-банк",
    "atm": "Банкомат",
    "online": "Онлайн-оплата",
    "card_chip": "Карта (чип)",
    "card_swipe": "Карта (магнитная полоса)",
}

RECIPIENT_LABELS: dict[str, str] = {
    "merchant": "Торговая точка",
    "utility": "Поставщик услуг",
    "person": "Частное лицо",
    "atm": "Банкомат",
    "exchange": "Биржа",
    "gambling": "Букмекер или казино",
}


def category_label(code: str | None) -> str:
    return CATEGORY_LABELS.get(code or "", code or "—")


def channel_label(code: str | None) -> str:
    return CHANNEL_LABELS.get(code or "", code or "—")
