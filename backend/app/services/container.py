"""Сборка сервисов приложения (используется API и воркером)."""
import logging
from typing import Any

from app.config import Settings
from app.db import session_factory
from app.schemas import TransactionIn
from app.services.events import ConnectionManager, EventBus, LocalEventBus, RedisEventBus
from app.services.pipeline import AnalysisService, ModelStore
from app.services.queueing import MemoryQueue, RedisQueue

log = logging.getLogger(__name__)


def make_redis(settings: Settings):
    import redis

    return redis.Redis.from_url(settings.redis_url, decode_responses=True)


def build_event_bus(settings: Settings, manager: ConnectionManager | None, redis_client=None) -> EventBus:
    if settings.queue_backend == "redis":
        return RedisEventBus(redis_client or make_redis(settings), settings.events_channel)
    assert manager is not None
    return LocalEventBus(manager)


def make_handler(service: AnalysisService):
    def handle(payload: dict[str, Any]) -> None:
        transaction = TransactionIn.model_validate(payload)
        db = session_factory()()
        try:
            service.process(db, transaction)
        finally:
            db.close()

    return handle


def build_queue(settings: Settings, service: AnalysisService, redis_client=None):
    if settings.queue_backend == "redis":
        return RedisQueue(
            redis_client or make_redis(settings),
            settings.queue_name,
            settings.queue_processing_name,
            settings.queue_failed_name,
        )
    return MemoryQueue(make_handler(service))


__all__ = ["build_event_bus", "build_queue", "make_handler", "make_redis"]
