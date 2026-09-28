"""Воркер очереди: читает транзакции из Redis, анализирует и публикует результат.

Запуск: python -m app.worker
"""
import logging
import signal
import threading

from prometheus_client import start_http_server

from app.config import get_settings
from app.db import init_db
from app.services import metrics
from app.services.container import build_event_bus, build_queue, make_handler, make_redis
from app.services.logging_config import setup_logging
from app.services.pipeline import AnalysisService, ModelStore

log = logging.getLogger("worker")


def main() -> None:
    settings = get_settings()
    setup_logging(settings.log_level, settings.log_json)
    if settings.queue_backend != "redis":
        raise SystemExit("Воркер работает только с QUEUE_BACKEND=redis")
    init_db()

    redis_client = make_redis(settings)
    model_store = ModelStore(settings.model_path)
    if not model_store.try_load():
        raise SystemExit("Модель не загружена, воркер остановлен")
    service = AnalysisService(settings, model_store, build_event_bus(settings, None, redis_client))
    queue = build_queue(settings, service, redis_client)

    start_http_server(settings.worker_metrics_port, registry=metrics.REGISTRY)
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    log.info("Воркер запущен, очередь: %s", settings.queue_name)
    queue.consume_forever(make_handler(service), stop)
    log.info("Воркер остановлен")


if __name__ == "__main__":
    main()
