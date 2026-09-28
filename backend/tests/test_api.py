import time
from datetime import datetime, timedelta, timezone

BASE = dict(client_id="X1", currency="RUB", category="groceries", channel="card_pos",
            recipient_id="M1", recipient_category="merchant")


def history(client, n=40, client_id="X1"):
    start = datetime(2025, 3, 1, tzinfo=timezone.utc)
    last = None
    for i in range(n):
        ts = start + timedelta(days=i // 3, hours=11 + i % 3)
        last = client.post("/api/transactions", json={
            **BASE, "client_id": client_id, "transaction_id": f"{client_id}-h{i}", "timestamp": ts.isoformat(),
            "amount": 1000 + (i % 7) * 40})
        assert last.status_code == 201, last.text
    return start + timedelta(days=n // 3 + 1)


def anomalous(day, tid="X1-anom", client_id="X1"):
    return {**BASE, "client_id": client_id, "transaction_id": tid,
            "timestamp": (day + timedelta(hours=3)).isoformat(), "amount": 45000, "category": "jewelry",
            "channel": "web", "recipient_id": "NEW-1", "recipient_category": "merchant"}


def test_health_and_docs(client):
    body = client.get("/api/health").json()
    assert body["status"] == "ok" and body["model_loaded"]
    assert client.get("/openapi.json").status_code == 200
    assert "anomaly_transactions_processed_total" in client.get("/metrics").text


def test_normal_and_anomalous_transaction(client):
    day = history(client)
    normal = client.post("/api/transactions", json={**BASE, "transaction_id": "n1",
                                                     "timestamp": (day + timedelta(hours=12)).isoformat(),
                                                     "amount": 1050})
    assert normal.status_code == 201
    assert normal.json()["analysis"]["risk_level"] == "low"
    assert normal.json()["analysis"]["status"] == "normal"

    resp = client.post("/api/transactions", json=anomalous(day))
    assert resp.status_code == 201
    a = resp.json()["analysis"]
    assert a["risk_level"] == "high" and a["anomaly_score"] > 0.85
    assert a["status"] == "needs_review" and a["profile_updated"] is False
    texts = " ".join(r["text"] for r in a["reasons"])
    assert "превышает медианную сумму" in texts and "ранее не использовалась" in texts
    assert {"amount", "category", "time"} <= set(a["deviation_types"])
    assert a["factors"] and a["factors"][0]["direction"] == "increases"
    assert set(a["features"]) >= {"log_amount", "hour_freq"}


def test_duplicate_is_idempotent(client):
    day = history(client, 10)
    payload = anomalous(day, "dup")
    first = client.post("/api/transactions", json=payload)
    second = client.post("/api/transactions", json=payload)
    assert first.status_code == 201 and second.status_code == 200
    assert first.json()["analysis"]["anomaly_score"] == second.json()["analysis"]["anomaly_score"]
    assert client.get("/api/transactions", params={"search": "dup"}).json()["total"] == 1


def test_validation_errors(client):
    ok = {**BASE, "transaction_id": "v1", "timestamp": "2025-03-01T10:00:00Z", "amount": 10}
    assert client.post("/api/transactions", json={**ok, "amount": -1}).status_code == 422
    assert client.post("/api/transactions", json={**ok, "currency": "XXX"}).status_code == 422
    assert client.post("/api/transactions", json={**ok, "timestamp": "не дата"}).status_code == 422
    assert client.post("/api/transactions", json={"client_id": "x"}).status_code == 422


def test_list_filters_and_pagination(client):
    day = history(client, 30)
    client.post("/api/transactions", json=anomalous(day, "a1"))
    client.post("/api/transactions", json=anomalous(day + timedelta(days=1), "a2"))
    everything = client.get("/api/transactions", params={"limit": 5}).json()
    assert everything["total"] == 32 and len(everything["items"]) == 5
    high = client.get("/api/transactions", params={"risk": "high"}).json()
    assert high["total"] >= 1 and all(i["analysis"]["risk_level"] == "high" for i in high["items"])
    flagged = client.get("/api/transactions", params={"only_flagged": True, "sort": "score"}).json()
    scores = [i["analysis"]["anomaly_score"] for i in flagged["items"]]
    assert scores == sorted(scores, reverse=True)
    assert client.get("/api/transactions", params={"client_id": "nobody"}).json()["total"] == 0
    assert client.get("/api/transactions", params={"category": "jewelry"}).json()["total"] == 2
    assert client.get("/api/transactions/a1").json()["transaction_id"] == "a1"
    assert client.get("/api/transactions/missing").status_code == 404


def test_review_flow_updates_profile_and_history(client):
    day = history(client, 30)
    client.post("/api/transactions", json=anomalous(day, "r1"))
    before = client.get("/api/clients/X1").json()["profile"]["transactions_in_profile"]
    assert client.get("/api/transactions/r1").json()["analysis"]["profile_updated"] is False

    resp = client.patch("/api/transactions/r1/review",
                        json={"status": "reviewed_normal", "reviewer": "ivanov", "comment": "Подтверждено клиентом"})
    assert resp.status_code == 200
    a = resp.json()["analysis"]
    assert a["status"] == "reviewed_normal" and a["reviewed_by"] == "ivanov" and a["profile_updated"] is True
    assert client.get("/api/clients/X1").json()["profile"]["transactions_in_profile"] == before + 1

    client.patch("/api/transactions/r1/review", json={"status": "reviewed_suspicious"})
    history_rows = client.get("/api/alerts/history", params={"client_id": "X1"}).json()
    assert [h["event_type"] for h in history_rows][::-1][:2] == ["triggered", "status_changed"]
    assert client.patch("/api/transactions/none/review", json={"status": "reviewed_normal"}).status_code == 404
    assert client.patch("/api/transactions/r1/review", json={"status": "bogus"}).status_code == 422


def test_clients_and_stats(client):
    day = history(client, 30)
    history(client, 12, client_id="X2")
    client.post("/api/transactions", json={**anomalous(day), "simulation_label": True})
    clients = client.get("/api/clients").json()
    assert {c["client_id"] for c in clients} == {"X1", "X2"}
    assert clients[0]["client_id"] == "X1" and clients[0]["flagged"] >= 1
    assert client.get("/api/clients", params={"only_flagged": True}).json()[0]["client_id"] == "X1"
    detail = client.get("/api/clients/X1").json()
    assert detail["profile"]["median_amount"] and detail["profile"]["categories"]["groceries"] == 30
    assert detail["recent"][0]["transaction_id"] == "X1-anom"
    assert client.get("/api/clients/none").status_code == 404
    stats = client.get("/api/stats").json()
    assert stats["total_transactions"] == 43 and stats["clients"] == 2
    assert stats["simulation_check"]["true_positive"] == 1
    assert client.get("/api/model").json()["model"]["version"] == "test-model"


def test_enqueue_is_processed_asynchronously(client):
    day = history(client, 15)
    resp = client.post("/api/transactions/enqueue", json=anomalous(day, "q1"))
    assert resp.status_code == 202 and resp.json()["status"] == "queued"
    deadline = time.time() + 10
    while time.time() < deadline:
        if client.get("/api/transactions/q1").status_code == 200:
            break
        time.sleep(0.1)
    assert client.get("/api/transactions/q1").json()["analysis"]["risk_level"] in {"medium", "high"}


def test_websocket_receives_analysis_and_review(client):
    day = history(client, 15)
    with client.websocket_connect("/ws/transactions") as ws:
        client.post("/api/transactions", json=anomalous(day, "w1"))
        event = ws.receive_json()
        assert event["type"] == "transaction_analyzed" and event["data"]["transaction_id"] == "w1"
        client.patch("/api/transactions/w1/review", json={"status": "reviewed_suspicious"})
        event = ws.receive_json()
        assert event["type"] == "transaction_reviewed"
        assert event["data"]["analysis"]["status"] == "reviewed_suspicious"


def test_high_risk_is_held_out_of_profile(client):
    day = history(client, 30)
    before = client.get("/api/clients/X1").json()["profile"]
    client.post("/api/transactions", json=anomalous(day, "h1"))
    after = client.get("/api/clients/X1").json()["profile"]
    assert after["transactions_in_profile"] == before["transactions_in_profile"]
    assert after["transactions_seen"] == before["transactions_seen"] + 1
    assert "jewelry" not in after["categories"]


def test_model_not_loaded_returns_503(client):
    client.app.state.model_store._bundle = None
    resp = client.post("/api/transactions", json={**BASE, "transaction_id": "m", "timestamp": "2025-03-01T10:00:00Z", "amount": 5})
    assert resp.status_code == 503
    assert client.get("/api/health").json()["status"] == "degraded"
