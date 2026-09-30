import numpy as np

from app.domain.features import FEATURE_NAMES
from app.ml.explain import build_reasons, shap_factors, summarize
from app.ml.metrics import best_f1_threshold, evaluate
from app.ml.model import load_bundle, save_bundle
from app.simulation.generator import ANOMALY_TYPES, generate_transactions


def test_generator_is_deterministic_and_labeled():
    a = generate_transactions(20, 20, seed=3)
    b = generate_transactions(20, 20, seed=3)
    assert a.equals(b)
    assert a["timestamp"].is_monotonic_increasing
    assert a["transaction_id"].is_unique
    assert 0.003 < a["is_anomaly"].mean() < 0.06
    assert set(a.loc[a["is_anomaly"], "anomaly_type"]) <= set(ANOMALY_TYPES)
    assert (a.loc[~a["is_anomaly"], "anomaly_type"] == "").all()
    assert (a["amount"] > 0).all()


def test_feature_frame_has_no_nans(small_frame):
    _, frame = small_frame
    assert not frame[FEATURE_NAMES].isna().any().any()
    assert np.isfinite(frame[FEATURE_NAMES].values).all()


def test_bundle_roundtrip_and_score_range(model_path, small_frame, tmp_path):
    _, frame = small_frame
    bundle = load_bundle(model_path)
    X = frame[bundle.feature_names].values[:500]
    scores = bundle.score(X)
    assert scores.shape == (500,) and scores.min() >= 0 and scores.max() <= 1
    save_bundle(bundle, tmp_path / "copy.joblib")
    assert np.allclose(load_bundle(tmp_path / "copy.joblib").score(X), scores)


def test_model_separates_anomalies(model_path, small_frame):
    _, frame = small_frame
    bundle = load_bundle(model_path)
    scores = bundle.score(frame[bundle.feature_names].values)
    metrics = evaluate(frame["is_anomaly"].values, scores, bundle.thresholds["medium"])
    assert metrics["roc_auc"] > 0.9 and metrics["pr_auc"] > 0.3


def test_risk_levels(model_path):
    bundle = load_bundle(model_path)
    assert bundle.risk_level(0.1) == "low"
    assert bundle.risk_level(bundle.thresholds["medium"]) == "medium"
    assert bundle.risk_level(0.99) == "high"
    assert bundle.risk_level(0.5, {"medium": 0.4, "high": 0.45}) == "high"


def test_shap_points_at_the_anomalous_feature(model_path):
    bundle = load_bundle(model_path)
    features = {name: 0.0 for name in FEATURE_NAMES}
    features.update({"log_amount": 7.0, "hour_freq": 0.2, "weekday_freq": 0.14, "category_freq": 0.25,
                     "channel_freq": 0.5, "recipient_cat_freq": 0.3, "currency_freq": 0.95,
                     "hour_cos": -0.5, "log_secs_since_last": 10.0, "rate_ratio": 1.0, "log_history_len": 4.5,
                     "amount_to_max": 0.5, "log_ratio_median": 3.0, "amount_zscore": 9.0})
    factors = shap_factors(bundle, features)
    assert factors and factors[0]["direction"] == "increases"
    assert {"log_ratio_median", "amount_zscore"} & {f["feature"] for f in factors[:3]}


def test_reasons_and_summary_texts():
    features = {n: 0.0 for n in FEATURE_NAMES}
    features.update({"amount_zscore": 6.0, "hour_freq": 0.0, "is_night": 1.0, "is_new_category": 0.9,
                     "rate_ratio": 1.0})
    ctx = {"warm": True, "history_len": 50, "median_amount": 1000.0, "amount_ratio": 8.4, "hour": 3,
           "hour_share": 0.0, "count_1h": 0, "count_24h": 1, "avg_daily": 2.0, "category": "jewelry",
           "channel": "web", "currency": "RUB", "recipient_id": None}
    reasons = build_reasons(features, ctx)
    texts = " | ".join(r["text"] for r in reasons)
    assert "в 8,4 раза превышает медианную сумму" in texts
    assert "нетипичное для клиента время" in texts
    assert "ранее не использовалась клиентом" in texts
    types, summary = summarize(reasons, "high")
    assert {"amount", "time", "category"} <= set(types) and "сумма" in summary
    assert summarize([], "low")[1].startswith("Существенных отклонений")


def test_best_f1_threshold():
    y = np.array([0, 0, 1, 1, 0, 1])
    s = np.array([0.1, 0.2, 0.9, 0.8, 0.3, 0.7])
    assert best_f1_threshold(y, s) == 0.7


def test_budget_metrics_do_not_depend_on_threshold():
    from app.ml.metrics import budget_metrics

    y = np.zeros(1000, dtype=int)
    y[[3, 10]] = 1
    scores = np.linspace(0, 1, 1000)
    scores[[3, 10]] = [2.0, 1.5]
    result = budget_metrics(y, scores, fractions=(0.002, 0.01))
    assert result["0.002"]["true_positive"] == 2 and result["0.002"]["precision"] == 1.0
    assert result["0.01"]["recall"] == 1.0 and result["0.01"]["flagged"] == 10


def test_time_folds_are_expanding_and_chronological():
    from app.ml.gbm import time_folds

    stamps = np.arange(1000)[::-1].copy()  # порядок в массиве не совпадает с хронологическим
    folds = time_folds(stamps, n_chunks=5, min_train_chunks=2)
    assert len(folds) == 3
    for train_idx, val_idx in folds:
        assert stamps[train_idx].max() < stamps[val_idx].min()
    assert len(folds[0][0]) == 400 and len(folds[-1][0]) == 800


def test_supervised_and_hybrid_bundles(small_frame, tmp_path):
    from app.domain.features import DEFAULT_FEATURE_NAMES
    from app.ml.dataset import time_split
    from app.ml.model import load_bundle, save_bundle
    from app.ml.train import FEATURES, train_hybrid, train_lightgbm

    FEATURES[:] = DEFAULT_FEATURE_NAMES
    _, frame = small_frame
    train, val, test = time_split(frame)
    for kind, bundle in (("lightgbm", train_lightgbm(train, val, test, seed=1)),
                         ("hybrid", train_hybrid(train, val, test, seed=1, tune=False))):
        assert bundle.kind == kind
        # пороги задаются бюджетом оповещений, а не максимумом F1 на валидации
        share = (bundle.score(val[FEATURES].values) >= bundle.thresholds["medium"]).mean()
        assert 0.005 <= share <= 0.03
        assert bundle.thresholds["high"] >= bundle.thresholds["medium"]
        scores = bundle.score(test[FEATURES].values)
        assert evaluate(test["is_anomaly"].values, scores, bundle.thresholds["medium"])["roc_auc"] > 0.8

        save_bundle(bundle, tmp_path / f"{kind}.joblib")
        loaded = load_bundle(tmp_path / f"{kind}.joblib")
        assert np.allclose(loaded.score(test[FEATURES].values[:200]), scores[:200])

        row = test.loc[test["is_anomaly"]].iloc[0]
        factors = shap_factors(loaded, {name: float(row[name]) for name in FEATURES})
        assert factors and all(f["feature"] in loaded.explain_names for f in factors)
    assert "iforest_score" in loaded.explain_names and loaded.explain_names[-1] == "iforest_score"


def test_monotone_constraints_follow_feature_names():
    from app.ml.gbm import monotone_constraints

    assert monotone_constraints(["log_amount", "pop_region_surprisal", "category_freq", "iforest_score"]) == [0, 1, -1, 1]
    assert monotone_constraints(None) is None
