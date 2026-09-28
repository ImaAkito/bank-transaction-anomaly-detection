import math
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from app.config import DEFAULT_CURRENCY_RATES
from app.domain.features import FEATURE_GROUPS, FEATURE_NAMES, compute_features
from app.domain.preprocessing import PreprocessingError, normalize
from app.domain.profile import new_profile, summarize, typical_hours, update_activity, update_behavior


def make_tx(i=0, amount=1000.0, hour=12, category="groceries", channel="card_pos", recipient="M1",
            currency="RUB", ts=None, day=0):
    ts = ts or datetime(2025, 3, 1, hour, 0, tzinfo=timezone.utc) + timedelta(days=day, minutes=i)
    return normalize(
        {"transaction_id": f"t{i}", "client_id": "c", "timestamp": ts, "amount": amount, "currency": currency,
         "category": category, "channel": channel, "recipient_id": recipient, "recipient_category": "merchant"},
        DEFAULT_CURRENCY_RATES,
    )


def feed(profile, tx, hold=False):
    update_activity(profile, tx.epoch)
    if not hold:
        update_behavior(profile, tx)


def test_feature_names_match_groups():
    assert len(FEATURE_NAMES) == len(set(FEATURE_NAMES)) == sum(len(v) for v in FEATURE_GROUPS.values())


def test_normalize_cleans_and_converts():
    tx = normalize(
        {"transaction_id": " a ", "client_id": "c", "timestamp": datetime(2025, 1, 1, 10, 0), "amount": 10,
         "currency": "usd", "category": " Groceries ", "channel": "WEB"},
        DEFAULT_CURRENCY_RATES,
    )
    assert tx.transaction_id == "a" and tx.currency == "USD" and tx.category == "groceries" and tx.channel == "web"
    assert tx.ts.tzinfo is not None and tx.amount_base == 900.0


@pytest.mark.parametrize("patch", [{"amount": -5}, {"amount": float("nan")}, {"currency": "XXX"},
                                   {"category": ""}, {"timestamp": "2025-01-01"}, {"client_id": " "}])
def test_normalize_rejects_invalid(patch):
    raw = {"transaction_id": "a", "client_id": "c", "timestamp": datetime(2025, 1, 1), "amount": 10,
           "currency": "RUB", "category": "x", **patch}
    with pytest.raises(PreprocessingError):
        normalize(raw, DEFAULT_CURRENCY_RATES)


def test_profile_statistics_match_numpy():
    profile = new_profile()
    rng = np.random.default_rng(0)
    amounts = rng.lognormal(7, 0.5, 60)
    for i, a in enumerate(amounts):
        feed(profile, make_tx(i, amount=float(a)))
    logs = np.log1p(amounts)
    assert math.isclose(profile["log_mean"], logs.mean(), rel_tol=1e-9)
    assert math.isclose(profile["log_m2"] / (len(logs) - 1), logs.var(ddof=1), rel_tol=1e-9)
    assert len(profile["amounts"]) == 60 and profile["n"] == 60
    summary = summarize(profile)
    assert math.isclose(summary["median_amount"], float(np.median(amounts)))


def test_profile_window_and_recipient_cap():
    profile = new_profile()
    for i in range(150):
        feed(profile, make_tx(i, recipient=f"R{i}"))
    assert len(profile["amounts"]) == 100
    assert len(profile["recipients"]) == 150
    assert 12 in typical_hours(profile)


def test_cold_start_features_are_neutral():
    profile = new_profile()
    features, ctx = compute_features(profile, make_tx(amount=1e6), min_history=5)
    assert not ctx["warm"]
    assert features["is_new_category"] == 0 and features["amount_zscore"] == 0 and features["log_ratio_median"] == 0


def test_deviations_are_detected_against_history():
    profile = new_profile()
    for i in range(40):
        feed(profile, make_tx(i, amount=1000 + (i % 5) * 50, day=i // 4))
    typical, _ = compute_features(profile, make_tx(99, amount=1050, day=11), min_history=5)
    spike, ctx = compute_features(profile, make_tx(99, amount=20000, day=11, hour=3, category="jewelry",
                                                  channel="web", recipient="NEW", currency="USD"), min_history=5)
    assert spike["log_ratio_median"] > 2.5 and spike["amount_zscore"] > 5
    assert ctx["amount_ratio"] > 15
    assert spike["is_new_category"] == spike["is_new_channel"] == spike["is_new_recipient"] == spike["is_new_currency"] == 1
    assert spike["hour_freq"] < typical["hour_freq"] and spike["is_night"] == 1
    assert typical["is_new_category"] == 0 and abs(typical["amount_zscore"]) < 3


def test_velocity_features_count_recent_operations():
    profile = new_profile()
    base = datetime(2025, 3, 1, 12, 0, tzinfo=timezone.utc)
    for i in range(10):
        feed(profile, make_tx(ts=base + timedelta(days=i)))
    for k in range(4):
        feed(profile, make_tx(ts=base + timedelta(days=10, minutes=k * 2)))
    features, ctx = compute_features(profile, make_tx(ts=base + timedelta(days=10, minutes=10)))
    assert features["tx_count_1h"] == 4 and ctx["count_1h"] == 4


def test_out_of_order_timestamp_is_handled():
    profile = new_profile()
    base = datetime(2025, 3, 1, 12, 0, tzinfo=timezone.utc)
    feed(profile, make_tx(ts=base))
    features, _ = compute_features(profile, make_tx(ts=base - timedelta(hours=1)))
    assert features["log_secs_since_last"] == 0.0
