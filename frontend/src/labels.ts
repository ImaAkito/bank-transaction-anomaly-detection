/** Русские названия кодов, которые используются в данных и модели. Совпадают с app/domain/labels.py. */

export const CATEGORY_LABELS: Record<string, string> = {
  groceries: "Продукты",
  restaurants: "Кафе и рестораны",
  transport: "Транспорт и такси",
  utilities: "Коммунальные платежи",
  entertainment: "Развлечения",
  health: "Здоровье и аптеки",
  clothing: "Одежда и обувь",
  p2p_transfer: "Перевод частному лицу",
  online_shopping: "Интернет-покупки",
  travel: "Путешествия",
  education: "Образование",
  cash_withdrawal: "Снятие наличных",
  electronics: "Электроника",
  jewelry: "Ювелирные изделия",
  crypto_exchange: "Криптобиржа",
  gambling: "Азартные игры",
  retail: "Розничные покупки",
  fuel: "Топливо",
  services: "Услуги",
};

export const CHANNEL_LABELS: Record<string, string> = {
  card_pos: "Оплата картой",
  mobile_app: "Мобильный банк",
  web: "Интернет-банк",
  atm: "Банкомат",
  online: "Онлайн-оплата",
  card_chip: "Карта (чип)",
  card_swipe: "Карта (магнитная полоса)",
};

export const RECIPIENT_LABELS: Record<string, string> = {
  merchant: "Торговая точка",
  utility: "Поставщик услуг",
  person: "Частное лицо",
  atm: "Банкомат",
  exchange: "Биржа",
  gambling: "Букмекер или казино",
};

export const MODEL_KIND_LABELS: Record<string, string> = {
  isolation_forest: "Isolation Forest (без учителя)",
  lightgbm: "LightGBM (с учителем)",
  hybrid: "Гибрид: LightGBM + Isolation Forest",
};

export const categoryLabel = (code: string | null | undefined) => (code ? CATEGORY_LABELS[code] ?? code : "—");
export const channelLabel = (code: string | null | undefined) => (code ? CHANNEL_LABELS[code] ?? code : "—");
export const recipientLabel = (code: string | null | undefined) => (code ? RECIPIENT_LABELS[code] ?? code : "—");
