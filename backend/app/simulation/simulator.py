"""Симулятор банковской информационной системы: последовательно передаёт транзакции в API.

Сначала быстро отправляется «исторический» период (формирует профили клиентов), затем транзакции
поступают с заданной скоростью, как в живом потоке. Время событий берётся из смоделированной шкалы времени.

Запуск: python -m app.simulation.simulator --api http://localhost:8000 --rate 5
"""
import argparse
import logging
import sys
import time
from datetime import datetime, timedelta, timezone

import httpx
import pandas as pd

from app.simulation.generator import generate_transactions

log = logging.getLogger("simulator")


def wait_for_api(client: httpx.Client, api: str, timeout: float = 120.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            body = client.get(f"{api}/api/health", timeout=5).json()
            if body.get("model_loaded"):
                return
            log.info("API доступен, модель ещё не загружена")
        except Exception:
            log.info("Ожидание API...")
        time.sleep(2)
    raise SystemExit("API недоступен")


def payload_from_row(row: dict) -> dict:
    ts = pd.Timestamp(row["timestamp"]).to_pydatetime()
    return {
        "transaction_id": row["transaction_id"],
        "client_id": row["client_id"],
        "timestamp": ts.isoformat(),
        "amount": float(row["amount"]),
        "currency": row["currency"],
        "category": row["category"],
        "channel": row["channel"],
        "recipient_id": row["recipient_id"],
        "recipient_category": row["recipient_category"],
        "simulation_label": bool(row["is_anomaly"]),
        "simulation_anomaly_type": row["anomaly_type"] or None,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", default="http://localhost:8000")
    parser.add_argument("--mode", choices=["enqueue", "sync"], default="enqueue",
                        help="enqueue: через очередь (202), sync: синхронный анализ")
    parser.add_argument("--clients", type=int, default=40)
    parser.add_argument("--history-days", type=int, default=30, help="длительность исторического периода")
    parser.add_argument("--live-days", type=int, default=7, help="длительность «живого» периода")
    parser.add_argument("--rate", type=float, default=5.0, help="транзакций в секунду в живом режиме")
    parser.add_argument("--anomaly-rate", type=float, default=0.02)
    parser.add_argument("--seed", type=int, default=2024)
    parser.add_argument("--loop", action="store_true", help="после завершения начать заново с новым seed")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s", stream=sys.stdout)

    endpoint = "/api/transactions/enqueue" if args.mode == "enqueue" else "/api/transactions"
    seed = args.seed
    with httpx.Client(timeout=30) as client:
        wait_for_api(client, args.api)
        while True:
            total_days = args.history_days + args.live_days
            start = (datetime.now(timezone.utc) - timedelta(days=total_days)).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            df = generate_transactions(
                n_clients=args.clients,
                days=total_days,
                seed=seed,
                start=start,
                anomaly_rate=args.anomaly_rate,
                anomaly_start_day=min(7, args.history_days),
                id_prefix="SIM",
            )
            live_from = start + timedelta(days=args.history_days)
            history = df[df["timestamp"] < live_from]
            live = df[df["timestamp"] >= live_from]
            log.info("Сгенерировано %s транзакций: история %s, живой поток %s (seed=%s)",
                     len(df), len(history), len(live), seed)

            failed = 0
            for i, row in enumerate(history.to_dict("records"), 1):
                response = client.post(f"{args.api}{endpoint}", json=payload_from_row(row))
                failed += response.status_code >= 400
                if i % 1000 == 0:
                    log.info("История: отправлено %s/%s", i, len(history))
            log.info("История отправлена, ошибок: %s. Начинается живой поток (%.1f оп./с)", failed, args.rate)

            interval = 1.0 / args.rate if args.rate > 0 else 0.0
            for i, row in enumerate(live.to_dict("records"), 1):
                started = time.monotonic()
                response = client.post(f"{args.api}{endpoint}", json=payload_from_row(row))
                if response.status_code >= 400:
                    log.warning("Ошибка %s: %s", response.status_code, response.text[:200])
                if i % 200 == 0:
                    log.info("Живой поток: отправлено %s/%s", i, len(live))
                time.sleep(max(0.0, interval - (time.monotonic() - started)))
            log.info("Поток завершён")
            if not args.loop:
                break
            seed += 1


if __name__ == "__main__":
    main()
