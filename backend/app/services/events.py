"""Шина событий: результаты анализа передаются подписчикам WebSocket."""
import asyncio
import json
import logging
from typing import Any, Protocol

from app.config import Settings

log = logging.getLogger(__name__)


class EventBus(Protocol):
    def publish(self, event: dict[str, Any]) -> None: ...


class ConnectionManager:
    """Реестр WebSocket-подключений интерфейса специалиста."""

    def __init__(self) -> None:
        self._connections: set[Any] = set()
        self._loop: asyncio.AbstractEventLoop | None = None

    def attach_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    async def connect(self, websocket) -> None:
        await websocket.accept()
        self._connections.add(websocket)

    def disconnect(self, websocket) -> None:
        self._connections.discard(websocket)

    @property
    def count(self) -> int:
        return len(self._connections)

    async def broadcast(self, event: dict[str, Any]) -> None:
        payload = json.dumps(event, ensure_ascii=False, default=str)
        for websocket in list(self._connections):
            try:
                await asyncio.wait_for(websocket.send_text(payload), timeout=2.0)
            except Exception:
                self._connections.discard(websocket)

    def broadcast_threadsafe(self, event: dict[str, Any]) -> None:
        """Вызывается из рабочих потоков: передаёт событие в цикл событий сервера."""
        if self._loop is None or self._loop.is_closed() or not self._connections:
            return
        asyncio.run_coroutine_threadsafe(self.broadcast(event), self._loop)


class LocalEventBus:
    def __init__(self, manager: ConnectionManager) -> None:
        self._manager = manager

    def publish(self, event: dict[str, Any]) -> None:
        self._manager.broadcast_threadsafe(event)


class RedisEventBus:
    def __init__(self, client, channel: str) -> None:
        self._client = client
        self._channel = channel

    def publish(self, event: dict[str, Any]) -> None:
        try:
            self._client.publish(self._channel, json.dumps(event, ensure_ascii=False, default=str))
        except Exception:
            log.exception("Не удалось опубликовать событие в Redis")


async def redis_listener(settings: Settings, manager: ConnectionManager) -> None:
    """Подписка API-процесса на результаты, публикуемые воркером, и рассылка в WebSocket."""
    import redis.asyncio as aioredis

    while True:
        client = aioredis.from_url(settings.redis_url, decode_responses=True)
        try:
            pubsub = client.pubsub()
            await pubsub.subscribe(settings.events_channel)
            log.info("Подписка на канал %s", settings.events_channel)
            async for message in pubsub.listen():
                if message.get("type") != "message":
                    continue
                try:
                    await manager.broadcast(json.loads(message["data"]))
                except json.JSONDecodeError:
                    log.warning("Некорректное событие в канале результатов")
        except asyncio.CancelledError:
            await client.aclose()
            raise
        except Exception:
            log.exception("Ошибка подписки на Redis, повтор через 2 с")
            await asyncio.sleep(2)
