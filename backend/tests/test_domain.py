import math
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from app.config import DEFAULT_CURRENCY_RATES
from app.domain.features import FEATURE_GROUPS, FEATURE_NAMES, compute_features
from app.domain.preprocessing import PreprocessingError, normalize
from app.domain.profile import new_profile, summarize, typical_hours, update_activity, update_behavior


def make_tx(i=0, amount=1000.0, hour=12, category="groceries", channel="card_pos", recipient="M1",
            currency="BYN", ts=None, day=0):
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
    assert tx.ts.tzinfo is not None and tx.amount_base == 10 * DEFAULT_CURRENCY_RATES["USD"]


@pytest.mark.parametrize("patch", [{"amount": -5}, {"amount": float("nan")}, {"currency": "XXX"},
                                   {"category": ""}, {"timestamp": "2025-01-01"}, {"client_id": " "}])
def test_normalize_rejects_invalid(patch):
    raw = {"transaction_id": "a", "client_id": "c", "timestamp": datetime(2025, 1, 1), "amount": 10,
           "currency": "BYN", "category": "x", **patch}
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
    novelty = [spike[k] for k in ("is_new_category", "is_new_channel", "is_new_recipient", "is_new_currency")]
    assert len(set(novelty)) == 1 and 0.5 < novelty[0] < 1  # ослаблено зрелостью профиля n / (n + K)
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


def test_novelty_is_weaker_for_young_profiles():
    young, mature = new_profile(), new_profile()
    for i in range(6):
        feed(young, make_tx(i, day=i))
    for i in range(120):
        feed(mature, make_tx(i, day=i // 3))
    probe = make_tx(500, category="jewelry", day=200)
    assert compute_features(young, probe)[0]["is_new_category"] < compute_features(mature, probe)[0]["is_new_category"]


def test_hold_rule_targets_numeric_outliers_only():
    from app.domain.features import should_hold

    profile = new_profile()
    for i in range(40):
        feed(profile, make_tx(i, amount=1000 + (i % 5) * 50, day=i // 4))
    assert should_hold(compute_features(profile, make_tx(99, amount=20000, day=11))[0])
    assert not should_hold(compute_features(profile, make_tx(99, amount=1100, day=11, category="jewelry",
                                                            channel="web", hour=3))[0])


def test_out_of_order_timestamp_is_handled():
    profile = new_profile()
    base = datetime(2025, 3, 1, 12, 0, tzinfo=timezone.utc)
    feed(profile, make_tx(ts=base))
    features, _ = compute_features(profile, make_tx(ts=base - timedelta(hours=1)))
    assert features["log_secs_since_last"] == 0.0


def test_population_surprisal_and_novelty_interaction():
    import pandas as pd

    from app.domain.features import fit_population

    rows = [{"category": "groceries", "channel": "card_pos", "recipient_category": "merchant"} for _ in range(990)]
    rows += [{"category": "jewelry", "channel": "web", "recipient_category": "italy"} for _ in range(10)]
    population = fit_population(pd.DataFrame(rows))
    assert population["n"] == 1000 and population["recipient_categories"]["italy"] == 10

    profile = new_profile()
    for i in range(40):
        feed(profile, make_tx(i, day=i // 4))  # клиент использует только «merchant»-получателей
    common = make_tx(99, day=11)
    rare = normalize(
        {"transaction_id": "r", "client_id": "c", "timestamp": common.ts, "amount": 1000, "currency": "BYN",
         "category": "jewelry", "channel": "web", "recipient_id": "x", "recipient_category": "italy"},
        DEFAULT_CURRENCY_RATES,
    )
    f_common = compute_features(profile, common, population=population)[0]
    f_rare = compute_features(profile, rare, population=population)[0]
    assert f_rare["pop_region_surprisal"] > f_common["pop_region_surprisal"] + 3
    assert f_rare["novel_rare_region"] > 3 and f_rare["novel_rare_category"] > 3
    assert f_common["novel_rare_region"] == 0  # не новый для клиента: 'merchant' уже в профиле, а значение ниже
    # без популяции признаки нейтральны
    f_none = compute_features(profile, rare)[0]
    assert f_none["pop_region_surprisal"] == 0 and f_none["novel_rare_region"] == 0
