from datetime import datetime, timezone

from app.domain.labels import CATEGORY_LABELS, CHANNEL_LABELS
from app.simulation.generator import CATEGORIES, CHANNELS, generate_transactions
from app.simulation.simulator import payload_from_row, read_cohort, write_cohort


def test_clients_have_realistic_daily_activity():
    df = generate_transactions(n_clients=40, days=30, seed=1, anomaly_rate=0.0)
    per_day = df.groupby("client_id").size() / 30
    assert per_day.max() < 6 and per_day.median() < 4  # обычный клиент: 1–4 операции в сутки
    assert set(df["currency"]) <= {"BYN", "USD", "EUR", "RUB", "PLN"}
    groceries = df.loc[(df["category"] == "groceries") & (df["currency"] == "BYN"), "amount"]
    assert 5 < groceries.median() < 150  # покупка продуктов — десятки белорусских рублей


def test_cohorts_do_not_reuse_clients():
    first = generate_transactions(n_clients=5, days=3, seed=10, client_offset=0)
    second = generate_transactions(n_clients=5, days=3, seed=11, client_offset=5)
    assert set(first["client_id"]).isdisjoint(second["client_id"])
    assert sorted(second["client_id"].unique())[0] == "C00005"


def test_cohort_state_file(tmp_path):
    path = tmp_path / "state.json"
    assert read_cohort(path) == 0
    write_cohort(path, 3)
    assert read_cohort(path) == 3
    path.write_text("not json", encoding="utf-8")
    assert read_cohort(path) == 0


def test_payload_treats_generated_time_as_local():
    row = {"transaction_id": "t", "client_id": "C1", "timestamp": datetime(2026, 1, 10, 3, 0, tzinfo=timezone.utc),
           "amount": 10.0, "currency": "BYN", "category": "groceries", "channel": "card_pos", "recipient_id": "M",
           "recipient_category": "merchant", "is_anomaly": False, "anomaly_type": ""}
    body = payload_from_row(row, "Europe/Minsk")
    assert body["timestamp"].startswith("2026-01-10T00:00:00") and body["timezone"] == "Europe/Minsk"
    assert payload_from_row(row)["timestamp"].startswith("2026-01-10T03:00:00")


def test_all_generated_codes_have_russian_labels():
    assert set(CATEGORIES) <= set(CATEGORY_LABELS)
    assert set(CHANNELS) <= set(CHANNEL_LABELS)
