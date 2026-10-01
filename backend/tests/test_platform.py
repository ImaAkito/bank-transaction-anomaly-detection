"""Часовой пояс, аутентификация и роли, миграции, партиции очереди, дрейф, переобучение, полный объём IBM."""
import json
import threading
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

from app.config import DEFAULT_CURRENCY_RATES
from app.domain.features import compute_features
from app.domain.preprocessing import PreprocessingError, normalize
from app.domain.profile import new_profile, update_activity, update_behavior

BASE = dict(currency="RUB", category="groceries", channel="card_pos", recipient_id="M1", recipient_category="merchant")


# ----------------------------------------------------------------- часовой пояс
def test_time_features_use_client_local_time():
    raw = {"transaction_id": "t", "client_id": "c", "timestamp": datetime(2025, 3, 1, 21, 30, tzinfo=timezone.utc),
           "amount": 100, **BASE}
    utc_tx = normalize(raw, DEFAULT_CURRENCY_RATES)
    msk_tx = normalize({**raw, "timezone": "Europe/Moscow"}, DEFAULT_CURRENCY_RATES)
    assert utc_tx.local.hour == 21 and msk_tx.local.hour == 0  # 21:30 UTC = 00:30 МСК следующего дня
    assert msk_tx.local.weekday() == (utc_tx.local.weekday() + 1) % 7
    f_utc, _ = compute_features(new_profile(), utc_tx)
    f_msk, ctx = compute_features(new_profile(), msk_tx)
    assert f_utc["is_night"] == 0 and f_msk["is_night"] == 1 and ctx["timezone"] == "Europe/Moscow"
    profile = new_profile()
    update_activity(profile, msk_tx.epoch)
    update_behavior(profile, msk_tx)
    assert profile["hour_counts"][0] == 1
    with pytest.raises(PreprocessingError):
        normalize({**raw, "timezone": "Mars/Olympus"}, DEFAULT_CURRENCY_RATES)


def test_client_timezone_is_remembered(client):
    ts = datetime(2025, 3, 1, 21, 30, tzinfo=timezone.utc)
    first = client.post("/api/transactions", json={**BASE, "client_id": "TZ", "transaction_id": "tz1",
                                                   "timestamp": ts.isoformat(), "amount": 100,
                                                   "timezone": "Asia/Vladivostok"}).json()
    assert first["timezone"] == "Asia/Vladivostok" and first["local_time"].startswith("2025-03-02T07:30")
    # следующая операция без пояса использует сохранённый пояс клиента
    second = client.post("/api/transactions", json={**BASE, "client_id": "TZ", "transaction_id": "tz2",
                                                    "timestamp": ts.isoformat(), "amount": 100}).json()
    assert second["timezone"] == "Asia/Vladivostok"
    assert client.get("/api/clients/TZ").json()["timezone"] == "Asia/Vladivostok"
    assert client.post("/api/transactions", json={**BASE, "client_id": "TZ", "transaction_id": "tz3",
                                                  "timestamp": ts.isoformat(), "amount": 1,
                                                  "timezone": "Nowhere/City"}).status_code == 422


# ----------------------------------------------------------------- аутентификация и роли
def _login(client, username, password):
    resp = client.post("/api/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def test_auth_roles_and_api_key(auth_client):
    c = auth_client
    assert c.get("/api/health").status_code == 200  # открытая точка
    assert c.get("/api/transactions").status_code == 401
    assert c.post("/api/auth/login", json={"username": "admin", "password": "wrong"}).status_code == 401
    admin = _login(c, "admin", "admin-pass")
    assert c.get("/api/auth/me", headers=admin).json()["role"] == "admin"

    for name, role in (("viewer1", "viewer"), ("analyst1", "analyst")):
        assert c.post("/api/users", headers=admin, json={"username": name, "password": "secret1", "role": role}).status_code == 201
    viewer, analyst = _login(c, "viewer1", "secret1"), _login(c, "analyst1", "secret1")

    payload = {**BASE, "client_id": "A1", "transaction_id": "auth-1", "timestamp": "2025-03-01T10:00:00Z", "amount": 50}
    assert c.post("/api/transactions", json=payload).status_code == 401
    assert c.post("/api/transactions", json=payload, headers={"X-API-Key": "bad"}).status_code == 401
    assert c.post("/api/transactions", json=payload, headers={"X-API-Key": "ingest-key"}).status_code == 201
    assert c.post("/api/transactions", json={**payload, "transaction_id": "auth-2"}, headers=viewer).status_code == 403

    assert c.get("/api/transactions", headers=viewer).json()["total"] == 1
    review = {"status": "reviewed_suspicious", "reviewer": "someone-else"}
    assert c.patch("/api/transactions/auth-1/review", json=review, headers=viewer).status_code == 403
    resp = c.patch("/api/transactions/auth-1/review", json=review, headers=analyst)
    assert resp.status_code == 200 and resp.json()["analysis"]["reviewed_by"] == "analyst1"  # автор — вошедший

    assert c.get("/api/users", headers=analyst).status_code == 403
    assert c.post("/api/model/reload", headers=analyst).status_code == 403
    assert c.post("/api/model/reload", headers=admin).status_code == 200
    c.patch("/api/users/viewer1", params={"active": False}, headers=admin)
    assert c.post("/api/auth/login", json={"username": "viewer1", "password": "secret1"}).status_code == 401


def test_websocket_requires_token(auth_client):
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect):
        with auth_client.websocket_connect("/ws/transactions") as ws:
            ws.receive_text()
    token = _login(auth_client, "admin", "admin-pass")["Authorization"][7:]
    with auth_client.websocket_connect(f"/ws/transactions?token={token}") as ws:
        auth_client.post("/api/transactions", headers={"X-API-Key": "ingest-key"},
                         json={**BASE, "client_id": "W", "transaction_id": "ws-1", "timestamp": "2025-03-01T10:00:00Z", "amount": 5})
        assert ws.receive_json()["data"]["transaction_id"] == "ws-1"


def test_tokens_are_signed_and_expire():
    from app.security import hash_password, make_token, read_token, verify_password

    stored = hash_password("pa55word")
    assert verify_password("pa55word", stored) and not verify_password("other", stored)
    token, _ = make_token("u", "analyst", "s1", 10)
    assert read_token(token, "s1").role == "analyst"
    assert read_token(token, "s2") is None
    assert read_token(token[:-2] + "xx", "s1") is None
    expired, _ = make_token("u", "analyst", "s1", -1)
    assert read_token(expired, "s1") is None


# ----------------------------------------------------------------- миграции
def test_migrations_match_models(tmp_path):
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext
    from sqlalchemy import create_engine

    from app import models  # noqa: F401
    from app.db import Base, run_migrations

    url = f"sqlite:///{tmp_path}/mig.db"
    run_migrations(url)
    run_migrations(url)  # повторный запуск ничего не меняет
    engine = create_engine(url)
    with engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    assert diff == []


# ----------------------------------------------------------------- партиции очереди
def test_partitioned_queue_keeps_client_order_across_workers():
    import fakeredis

    from app.services.queueing import RedisQueue, partition_of

    server = fakeredis.FakeServer()
    producer = RedisQueue(fakeredis.FakeRedis(server=server, decode_responses=True), "q", "q:p", "q:f", partitions=4)
    workers = [RedisQueue(fakeredis.FakeRedis(server=server, decode_responses=True), "q", "q:p", "q:f",
                          partitions=4, worker_index=i, worker_count=2) for i in range(2)]
    assert sorted(workers[0].owned + workers[1].owned) == [0, 1, 2, 3]
    for i in range(40):
        producer.enqueue({"client_id": f"c{i % 5}", "seq": i})
    assert producer.depth() == 40

    seen: dict[int, list[dict]] = {0: [], 1: []}
    for idx, worker in enumerate(workers):
        while worker.consume_one(seen[idx].append, timeout=1):
            pass
    assert len(seen[0]) + len(seen[1]) == 40 and producer.depth() == 0
    for idx, messages in seen.items():
        for msg in messages:  # клиент обрабатывается только «своим» воркером
            assert partition_of(msg["client_id"], 4) in workers[idx].owned
        for client_id in {m["client_id"] for m in messages}:
            seqs = [m["seq"] for m in messages if m["client_id"] == client_id]
            assert seqs == sorted(seqs)  # порядок операций клиента сохранён
    with pytest.raises(ValueError):
        RedisQueue(fakeredis.FakeRedis(server=server), "q", "q:p", "q:f", partitions=1, worker_count=2, worker_index=0)


# ----------------------------------------------------------------- дрейф и переобучение
def test_drift_detects_shift():
    from app.ml.drift import build_reference, compute_drift

    rng = np.random.default_rng(0)
    base = rng.normal(0, 1, 5000)
    reference = build_reference({"x": base}, rng.random(5000), 0.99)
    same = compute_drift(reference, [{"x": v} for v in rng.normal(0, 1, 2000)], list(rng.random(2000)), 0.99)
    shifted = compute_drift(reference, [{"x": v} for v in rng.normal(2, 1, 2000)], list(rng.random(2000)), 0.99)
    assert same["status"] == "ok" and same["max_psi"] < 0.1
    assert shifted["status"] == "alert" and shifted["features"][0]["feature"] == "x"


def _feed(client, n_clients=12, days=30):
    from app.simulation.generator import generate_transactions
    from app.simulation.simulator import payload_from_row

    df = generate_transactions(n_clients, days, seed=5)
    for row in df.to_dict("records"):
        assert client.post("/api/transactions", json=payload_from_row(row)).status_code in (200, 201)
    return len(df)


def test_drift_endpoint_and_retraining(client, monkeypatch):
    from app.config import get_settings
    from app.db import session_factory
    from app.ml.model import load_bundle
    from app.ml.retrain import retrain

    rows = _feed(client)
    drift = client.get("/api/model/drift").json()
    assert drift["available"] is True and 0 < drift["window"] < rows and drift["features"]
    assert drift["min_history"] == 20  # новые клиенты не участвуют в сравнении

    settings = get_settings().model_copy(update={"retrain_min_transactions": 100})
    before = load_bundle(settings.model_path).version
    db = session_factory()()
    try:
        result = retrain(settings, db, reason="test")
    finally:
        db.close()
    assert result["status"] in {"deployed", "rejected"}, result
    events = client.get("/api/model/events").json()
    assert events and events[0]["event_type"] in {"retrained", "retrain_rejected"}
    if result["status"] == "deployed":
        assert load_bundle(settings.model_path).version != before
        # API перечитывает изменённый файл модели без перезапуска
        assert client.get("/api/model").json()["model"]["version"] == result["version"]

    skipped = retrain(settings.model_copy(update={"retrain_min_transactions": 10**9}), session_factory()(), "test")
    assert skipped["status"] == "skipped"


def test_model_page_lists_experiment_runs(client, tmp_path, monkeypatch):
    run = tmp_path / "experiments" / "results_ibm"
    run.mkdir(parents=True)
    (run / "summary.json").write_text(json.dumps({"seeds": [1], "datasets": [{"rows": 10, "anomaly_share": 0.1}],
                                                  "models": {}, "ablation": {}}), encoding="utf-8")
    client.app.state.settings = client.app.state.settings.model_copy(update={"experiments_dir": str(tmp_path / "experiments")})
    runs = client.get("/api/model").json()["experiment_runs"]
    assert [r["name"] for r in runs] == ["results_ibm"] and runs[0]["rows"] == 10


# ----------------------------------------------------------------- полный объём IBM
def test_large_pipeline_keeps_full_test_and_all_frauds(tmp_path):
    from app.ml.large import build_large_frame, split_by_cutoffs
    from app.simulation.generator import generate_transactions

    df = generate_transactions(30, 30, seed=11, start=datetime(2020, 1, 1, tzinfo=timezone.utc))
    mcc = {c: 5411 for c in df["category"].unique()}
    ibm = pd.DataFrame({
        "User": df["client_id"].str[1:].astype(int), "Card": 0, "Year": df["timestamp"].dt.year,
        "Month": df["timestamp"].dt.month, "Day": df["timestamp"].dt.day, "Time": df["timestamp"].dt.strftime("%H:%M"),
        "Amount": "$" + df["amount"].astype(str), "Use Chip": "Chip Transaction", "Merchant Name": "1",
        "Merchant City": "X", "Merchant State": "CA", "Zip": "1", "MCC": df["category"].map(mcc),
        "Errors?": "", "Is Fraud?": np.where(df["is_anomaly"], "Yes", "No"),
    })
    path = tmp_path / "ibm.csv"
    ibm.to_csv(path, index=False)

    full, info = build_large_frame(path, tmp_path / "parts", parts=4, workers=2, negative_rate=1.0)
    sampled, info2 = build_large_frame(path, tmp_path / "parts", parts=4, workers=2, negative_rate=0.25)
    assert info["rows"] == len(df) == len(full)
    _, _, test_full = split_by_cutoffs(full, info)
    train_s, val_s, test_s = split_by_cutoffs(sampled, info2)
    assert len(test_s) == len(test_full)  # тестовый период не прореживается
    assert sampled["is_anomaly"].sum() == full["is_anomaly"].sum()  # все мошеннические операции сохранены
    assert len(train_s) + len(val_s) < 0.5 * (len(full) - len(test_full))
    assert str(sampled["log_amount"].dtype) == "float32"


def test_drift_ignores_young_clients():
    from app.ml.drift import build_reference, compute_drift

    rng = np.random.default_rng(1)
    mature = np.log1p(rng.integers(20, 200, 3000))
    reference = build_reference({"log_history_len": mature, "x": rng.normal(0, 1, 3000)}, rng.random(3000), 0.99)
    # запуск системы: почти все клиенты новые, их операции в сравнение не попадают
    young = [{"log_history_len": float(np.log1p(k % 10)), "x": float(v)} for k, v in enumerate(rng.normal(5, 1, 900))]
    old = [{"log_history_len": float(np.log1p(50)), "x": float(v)} for v in rng.normal(0, 1, 300)]
    report = compute_drift(reference, young + old, list(rng.random(1200)), 0.99)
    assert report["window"] == 300 and report["status"] == "ok"
    only_young = compute_drift(reference, young, list(rng.random(900)), 0.99)
    assert only_young["available"] is False
