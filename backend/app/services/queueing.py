"""Очередь входящих транзакций: Redis (надёжная очередь с подтверждением) или в памяти процесса."""
import json
import logging
import queue
import threading
from collections.abc import Callable
from typing import Any

from app.services import metrics

log = logging.getLogger(__name__)

Handler = Callable[[dict[str, Any]], None]


class MemoryQueue:
    """Очередь внутри процесса API: для разработки и тестов без Redis."""

    def __init__(self, handler: Handler) -> None:
        self._queue: queue.Queue[dict[str, Any]] = queue.Queue()
        self._handler = handler
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def start(self) -> None:
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="memory-queue", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    def enqueue(self, payload: dict[str, Any]) -> None:
        self._queue.put(payload)

    def depth(self) -> int:
        return self._queue.qsize()

    def join(self) -> None:
        self._queue.join()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                payload = self._queue.get(timeout=0.2)
            except queue.Empty:
                continue
            try:
                self._handler(payload)
            except Exception:
                metrics.TX_ERRORS.labels(stage="queue").inc()
                log.exception("Ошибка обработки сообщения очереди: %s", payload.get("transaction_id"))
            finally:
                self._queue.task_done()


class RedisQueue:
    """Надёжная очередь на списках Redis.

    Сообщение перекладывается из очереди в список «в обработке» (BLMOVE) и удаляется оттуда только
    после успешной обработки. Необработанные сообщения возвращаются в очередь при старте воркера,
    ошибочные попадают в список failed вместе с текстом ошибки.
    """

    def __init__(self, client, name: str, processing_name: str, failed_name: str) -> None:
        self._client = client
        self.name = name
        self.processing_name = processing_name
        self.failed_name = failed_name

    def enqueue(self, payload: dict[str, Any]) -> None:
        self._client.lpush(self.name, json.dumps(payload, ensure_ascii=False, default=str))

    def depth(self) -> int:
        return int(self._client.llen(self.name))

    def failed_depth(self) -> int:
        return int(self._client.llen(self.failed_name))

    def requeue_stale(self) -> int:
        """Возвращает в очередь сообщения, не подтверждённые предыдущим экземпляром воркера."""
        moved = 0
        while self._client.lmove(self.processing_name, self.name, "LEFT", "RIGHT") is not None:
            moved += 1
        if moved:
            log.warning("Возвращено в очередь необработанных сообщений: %s", moved)
        return moved

    def consume_one(self, handler: Handler, timeout: int = 2) -> bool:
        raw = self._client.blmove(self.name, self.processing_name, timeout, "RIGHT", "LEFT")
        if raw is None:
            return False
        try:
            handler(json.loads(raw))
        except Exception as exc:
            metrics.TX_ERRORS.labels(stage="queue").inc()
            log.exception("Ошибка обработки сообщения, оно перемещено в %s", self.failed_name)
            self._client.lpush(
                self.failed_name, json.dumps({"message": raw, "error": repr(exc)}, ensure_ascii=False)
            )
        finally:
            self._client.lrem(self.processing_name, 1, raw)
        return True

    def consume_forever(self, handler: Handler, stop: threading.Event) -> None:
        self.requeue_stale()
        while not stop.is_set():
            try:
                self.consume_one(handler)
            except Exception:
                log.exception("Ошибка связи с Redis, повтор через 2 с")
                stop.wait(2)
